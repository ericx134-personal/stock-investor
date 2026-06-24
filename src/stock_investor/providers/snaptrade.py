from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..io import atomic_write_text


DEFAULT_BASE_URL = "https://api.snaptrade.com/api/v1"
DEFAULT_BROKER = "FIDELITY"


class SnapTradeProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapTradeCredentials:
    client_id: str
    consumer_key: str
    user_id: str | None = None
    user_secret: str | None = None
    base_url: str = DEFAULT_BASE_URL


def load_snaptrade_credentials(
    require_user: bool = False,
    *,
    env_path: str | Path | None = None,
) -> SnapTradeCredentials:
    environment = _merged_environment(env_path)
    credentials = SnapTradeCredentials(
        client_id=(environment.get("SNAPTRADE_CLIENT_ID") or "").strip(),
        consumer_key=(environment.get("SNAPTRADE_CONSUMER_KEY") or "").strip(),
        user_id=(environment.get("SNAPTRADE_USER_ID") or "").strip() or None,
        user_secret=(environment.get("SNAPTRADE_USER_SECRET") or "").strip() or None,
        base_url=(environment.get("SNAPTRADE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
    )
    missing = []
    if not credentials.client_id:
        missing.append("SNAPTRADE_CLIENT_ID")
    if not credentials.consumer_key:
        missing.append("SNAPTRADE_CONSUMER_KEY")
    if require_user and not credentials.user_id:
        missing.append("SNAPTRADE_USER_ID")
    if require_user and not credentials.user_secret:
        missing.append("SNAPTRADE_USER_SECRET")
    if missing:
        raise SnapTradeProviderError(
            "Missing SnapTrade environment variables: " + ", ".join(missing)
        )
    return credentials


def _merged_environment(env_path: str | Path | None = None) -> dict[str, str]:
    environment = dict(os.environ)
    configured_path = env_path or os.environ.get("STOCK_INVESTOR_SERVICE_ENV")
    path = Path(configured_path) if configured_path else Path("data/private/service.env")
    if path.exists():
        file_values = _parse_service_env(path)
        for key, value in file_values.items():
            environment.setdefault(key, value)
    return environment


def _parse_service_env(path: Path) -> dict[str, str]:
    values = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _unquote_env_value(value.strip())
        if key:
            values[key] = value
    return values


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


class SnapTradeClient:
    def __init__(
        self,
        credentials: SnapTradeCredentials,
        *,
        opener: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self.credentials = credentials
        self._opener = opener or urlopen
        self._clock = clock or time.time

    def register_user(self, user_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/snapTrade/registerUser",
            body={"userId": user_id},
        )

    def login_url(
        self,
        *,
        user_id: str,
        user_secret: str,
        broker: str | None = DEFAULT_BROKER,
        custom_redirect: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "connectionType": "read",
            "darkMode": True,
            "showCloseButton": True,
            "connectionPortalVersion": "v4",
        }
        if broker:
            body["broker"] = broker
        if custom_redirect:
            body["customRedirect"] = custom_redirect
            body["immediateRedirect"] = True
        return self._request(
            "POST",
            "/snapTrade/login",
            query_pairs=(("userId", user_id), ("userSecret", user_secret)),
            body=body,
        )

    def list_accounts(self, *, user_id: str, user_secret: str) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            "/accounts",
            query_pairs=(("userId", user_id), ("userSecret", user_secret)),
        )
        if not isinstance(response, list):
            raise SnapTradeProviderError("SnapTrade accounts response is not a list")
        return response

    def list_account_balances(
        self,
        *,
        account_id: str,
        user_id: str,
        user_secret: str,
    ) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/accounts/{account_id}/balances",
            query_pairs=(("userId", user_id), ("userSecret", user_secret)),
        )
        if not isinstance(response, list):
            raise SnapTradeProviderError("SnapTrade balances response is not a list")
        return response

    def list_account_positions(
        self,
        *,
        account_id: str,
        user_id: str,
        user_secret: str,
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/accounts/{account_id}/positions/all",
            query_pairs=(("userId", user_id), ("userSecret", user_secret)),
        )
        if not isinstance(response, dict):
            raise SnapTradeProviderError("SnapTrade positions response is not an object")
        return response

    def _request(
        self,
        method: str,
        subpath: str,
        *,
        query_pairs: tuple[tuple[str, str], ...] = (),
        body: dict[str, Any] | None = None,
    ) -> Any:
        timestamp = str(int(self._clock()))
        query = _query_string(
            (
                ("clientId", self.credentials.client_id),
                ("timestamp", timestamp),
                *query_pairs,
            )
        )
        resource_path = f"{subpath}?{query}"
        signature = compute_request_signature(
            resource_path,
            self.credentials.consumer_key,
            body,
        )
        data = None
        headers = {
            "Accept": "application/json",
            "Signature": signature,
        }
        if body is not None:
            data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.credentials.base_url}{resource_path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._opener(request, timeout=30) as response:
                content = response.read()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise SnapTradeProviderError(
                f"SnapTrade API {method} {subpath} failed: HTTP {error.code} {detail}"
            ) from error
        except URLError as error:
            raise SnapTradeProviderError(
                f"SnapTrade API {method} {subpath} failed: {error.reason}"
            ) from error
        if not content:
            return None
        try:
            return json.loads(content.decode())
        except json.JSONDecodeError as error:
            raise SnapTradeProviderError("SnapTrade API returned non-JSON data") from error


def compute_request_signature(
    resource_path: str,
    consumer_key: str,
    body: dict[str, Any] | None,
) -> str:
    subpath, query = resource_path.split("?", 1)
    signature_payload = {
        "content": body or None,
        "path": f"/api/v1{subpath}",
        "query": query,
    }
    canonical = json.dumps(signature_payload, separators=(",", ":"), sort_keys=True)
    digest = hmac.new(
        consumer_key.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode()


def fetch_snaptrade_snapshot(
    client: SnapTradeClient,
    *,
    user_id: str,
    user_secret: str,
) -> dict[str, Any]:
    accounts = client.list_accounts(user_id=user_id, user_secret=user_secret)
    account_snapshots = []
    for account in accounts:
        account_id = str(account.get("id") or "")
        if not account_id:
            continue
        balances = client.list_account_balances(
            account_id=account_id,
            user_id=user_id,
            user_secret=user_secret,
        )
        positions = client.list_account_positions(
            account_id=account_id,
            user_id=user_id,
            user_secret=user_secret,
        )
        account_snapshots.append(
            {
                "account": _sanitize_account(account),
                "balances": balances,
                "positions": _normalize_positions(positions),
            }
        )
    return _snapshot_payload(account_snapshots)


def write_snaptrade_snapshot(payload: dict[str, Any], path: str | Path) -> None:
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", path)


def _query_string(pairs: tuple[tuple[str, str], ...]) -> str:
    return urlencode([(key, value) for key, value in pairs if value is not None])


def _sanitize_account(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": account.get("id"),
        "brokerage_authorization": account.get("brokerage_authorization"),
        "name": account.get("name"),
        "number": _mask_account_number(account.get("number")),
        "institution_name": account.get("institution_name"),
        "sync_status": account.get("sync_status"),
        "balance": account.get("balance"),
        "created_date": account.get("created_date"),
        "opening_date": account.get("opening_date"),
        "is_paper": account.get("is_paper"),
    }


def _mask_account_number(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    visible = text[-4:] if len(text) >= 4 else text
    return f"***{visible}"


def _normalize_positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise SnapTradeProviderError("SnapTrade positions results is not a list")
    return [_normalize_position(item) for item in results if isinstance(item, dict)]


def _normalize_position(position: dict[str, Any]) -> dict[str, Any]:
    instrument = position.get("instrument") if isinstance(position.get("instrument"), dict) else {}
    symbol = (
        instrument.get("symbol")
        or instrument.get("raw_symbol")
        or position.get("symbol")
        or position.get("symbol_id")
    )
    return {
        "symbol": str(symbol).upper() if symbol else None,
        "description": instrument.get("description"),
        "instrument_kind": instrument.get("kind"),
        "currency": instrument.get("currency"),
        "exchange": instrument.get("exchange"),
        "units": _first_number(position, "units", "quantity", "qty"),
        "price": _first_number(position, "price", "market_price"),
        "market_value": _first_number(
            position,
            "market_value",
            "marketValue",
            "value",
        ),
        "average_purchase_price": _first_number(
            position,
            "average_purchase_price",
            "averagePurchasePrice",
            "average_cost",
        ),
    }


def _first_number(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _snapshot_payload(accounts: list[dict[str, Any]]) -> dict[str, Any]:
    positions = [
        position
        for account in accounts
        for position in account["positions"]
        if position.get("symbol")
    ]
    return {
        "schema_version": 1,
        "source": "snaptrade",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "account_count": len(accounts),
        "position_count": len(positions),
        "unique_symbols": sorted({position["symbol"] for position in positions}),
        "accounts": accounts,
    }
