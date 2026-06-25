from __future__ import annotations

import importlib
import json
import socket
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..data import Price
from ..io import atomic_write_text


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11111
GROUP_PACING_THRESHOLD = 8
GROUP_PACING_SECONDS = 3.2
HIGH_FREQUENCY_RETRY_SECONDS = 31.0
HISTORY_PAGE_SIZE = 1000
SNAPSHOT_BATCH_SIZE = 400


class MoomooProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class MoomooWatchlistItem:
    group_name: str
    code: str
    symbol: str
    market: str | None
    name: str | None = None


@dataclass(frozen=True)
class MoomooProviderFailure:
    symbol: str
    operation: str
    message: str


FailureSink = Any


def fetch_moomoo_watchlists(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    group_names: tuple[str, ...] = (),
    sdk: Any | None = None,
    check_connection: bool = True,
    rate_limit_pause_seconds: float = GROUP_PACING_SECONDS,
    high_frequency_retry_seconds: float = HIGH_FREQUENCY_RETRY_SECONDS,
) -> dict:
    """Read Moomoo/OpenD watchlists through the quote API only."""
    sdk = sdk or _load_sdk()
    if check_connection:
        _ensure_opend_available(host, port)
    quote_context = sdk.OpenQuoteContext(host=host, port=port)
    try:
        groups = tuple(group_names) or _discover_groups(
            quote_context,
            sdk,
            high_frequency_retry_seconds=high_frequency_retry_seconds,
        )
        if not groups:
            raise MoomooProviderError(
                "No Moomoo watchlist groups were found; pass --group explicitly."
            )
        items = []
        for group_name in groups:
            if len(groups) > GROUP_PACING_THRESHOLD and rate_limit_pause_seconds > 0:
                time.sleep(rate_limit_pause_seconds)
            table = _call_with_retry(
                lambda group_name=group_name: quote_context.get_user_security(group_name),
                sdk,
                f"get_user_security({group_name})",
                high_frequency_retry_seconds=high_frequency_retry_seconds,
            )
            items.extend(_items_from_table(group_name, table))
        return _payload(items, host, port)
    finally:
        close = getattr(quote_context, "close", None)
        if callable(close):
            close()


def fetch_moomoo_daily_bars(
    symbols: list[str],
    start: str,
    end: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    sdk: Any | None = None,
    check_connection: bool = True,
    max_count: int = HISTORY_PAGE_SIZE,
    on_failure: FailureSink | None = None,
) -> dict[str, list[Price]]:
    """Fetch adjusted daily K-line bars from a local Moomoo/OpenD session."""
    if not symbols:
        raise ValueError("at least one symbol is required")
    sdk = sdk or _load_sdk()
    if check_connection:
        _ensure_opend_available(host, port)
    quote_context = sdk.OpenQuoteContext(host=host, port=port)
    try:
        result: dict[str, list[Price]] = {}
        for symbol in _unique_symbols(symbols):
            code = _market_code(symbol)
            try:
                bars = _fetch_symbol_daily_bars(
                    quote_context, sdk, code, start, end, max_count
                )
            except MoomooProviderError as error:
                if on_failure:
                    on_failure(MoomooProviderFailure(symbol, "history", str(error)))
                continue
            if bars:
                result[symbol] = bars
        return result
    finally:
        close = getattr(quote_context, "close", None)
        if callable(close):
            close()


def fetch_moomoo_latest_quotes(
    symbols: list[str],
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    sdk: Any | None = None,
    check_connection: bool = True,
    on_failure: FailureSink | None = None,
) -> dict[str, dict]:
    """Fetch latest quote snapshots from a local Moomoo/OpenD session."""
    if not symbols:
        raise ValueError("at least one symbol is required")
    sdk = sdk or _load_sdk()
    if check_connection:
        _ensure_opend_available(host, port)
    quote_context = sdk.OpenQuoteContext(host=host, port=port)
    try:
        quotes: dict[str, dict] = {}
        symbols_by_code = {_market_code(symbol): symbol for symbol in _unique_symbols(symbols)}
        codes = list(symbols_by_code)
        for index in range(0, len(codes), SNAPSHOT_BATCH_SIZE):
            batch = codes[index : index + SNAPSHOT_BATCH_SIZE]
            table = _snapshot_table_for_codes(
                quote_context,
                sdk,
                batch,
                symbols_by_code,
                on_failure,
            )
            for row in _records(table):
                code = _first_text(row, "code", "stock_code")
                if not code:
                    continue
                _, symbol = _normalize_code(code)
                normalized = symbols_by_code.get(code.strip().upper(), symbol)
                quote = _quote_from_snapshot(normalized, row)
                if quote:
                    quotes[normalized] = quote
        return quotes
    finally:
        close = getattr(quote_context, "close", None)
        if callable(close):
            close()


def write_moomoo_watchlists(payload: dict, path: str | Path) -> None:
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", path)


def _unique_symbols(symbols: list[str]) -> list[str]:
    return sorted({item.strip().upper() for item in symbols if item and item.strip()})


def _market_code(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if "." in normalized:
        return normalized
    return f"US.{normalized}"


def _fetch_symbol_daily_bars(
    quote_context: Any,
    sdk: Any,
    code: str,
    start: str,
    end: str,
    max_count: int,
) -> list[Price]:
    page_req_key = None
    seen_page_keys: set[bytes] = set()
    bars: dict[date, Price] = {}
    for _ in range(100):
        response = quote_context.request_history_kline(
            code,
            start=start,
            end=end,
            ktype=sdk.KLType.K_DAY,
            autype=sdk.AuType.QFQ,
            max_count=max_count,
            page_req_key=page_req_key,
        )
        table, page_req_key = _unwrap_paged_response(
            response, sdk, f"request_history_kline({code})"
        )
        for row in _records(table):
            price = _price_from_kline_row(row)
            if price:
                bars[price.date] = price
        if not page_req_key or page_req_key in seen_page_keys:
            break
        seen_page_keys.add(page_req_key)
    return [bars[day] for day in sorted(bars)]


def _snapshot_table_for_codes(
    quote_context: Any,
    sdk: Any,
    codes: list[str],
    symbols_by_code: dict[str, str],
    on_failure: FailureSink | None,
) -> list[dict[str, Any]]:
    try:
        return _call_with_retry(
            lambda codes=codes: quote_context.get_market_snapshot(codes),
            sdk,
            "get_market_snapshot",
            high_frequency_retry_seconds=HIGH_FREQUENCY_RETRY_SECONDS,
        )
    except MoomooProviderError as batch_error:
        rows = []
        for code in codes:
            try:
                table = _call_with_retry(
                    lambda code=code: quote_context.get_market_snapshot([code]),
                    sdk,
                    f"get_market_snapshot({code})",
                    high_frequency_retry_seconds=HIGH_FREQUENCY_RETRY_SECONDS,
                )
            except MoomooProviderError as error:
                if on_failure:
                    on_failure(
                        MoomooProviderFailure(
                            symbols_by_code.get(code, code), "snapshot", str(error)
                        )
                    )
                continue
            rows.extend(_records(table))
        if not rows and on_failure:
            for code in codes:
                on_failure(
                    MoomooProviderFailure(
                        symbols_by_code.get(code, code), "snapshot", str(batch_error)
                    )
                )
        return rows


def _unwrap_paged_response(response: Any, sdk: Any, operation: str) -> tuple[Any, bytes | None]:
    if not isinstance(response, tuple) or len(response) < 2:
        raise MoomooProviderError(f"{operation} returned an unexpected response shape")
    ret, data = response[0], response[1]
    ok = getattr(sdk, "RET_OK", 0)
    if ret != ok:
        raise MoomooProviderError(f"{operation} failed: {data}")
    page_req_key = response[2] if len(response) > 2 and response[2] else None
    return data, page_req_key


def _price_from_kline_row(row: dict[str, Any]) -> Price | None:
    raw_date = _first_text(row, "time_key", "time", "date")
    close = _optional_float(row.get("close"))
    if not raw_date or close is None or close <= 0:
        return None
    observed_date = date.fromisoformat(str(raw_date)[:10])
    open_price = _optional_float(row.get("open"))
    high = _optional_float(row.get("high"))
    low = _optional_float(row.get("low"))
    price_points = [value for value in (close, open_price, high, low) if value is not None]
    if high is not None:
        high = max(price_points)
    if low is not None:
        low = min(price_points)
    return Price(
        observed_date,
        close,
        open_price,
        high,
        low,
        _optional_float(row.get("volume")),
    )


def _quote_from_snapshot(symbol: str, row: dict[str, Any]) -> dict | None:
    last_price = _optional_float(row.get("last_price"))
    previous_close = _optional_float(row.get("prev_close_price"))
    current_price = _latest_session_price(row) or last_price
    if current_price is None or current_price <= 0:
        return None
    today_return = (
        current_price / previous_close - 1
        if previous_close is not None and previous_close > 0
        else None
    )
    return {
        "symbol": symbol,
        "price": current_price,
        "previous_close": previous_close,
        "today_return": today_return,
        "intraday_path": [],
        "regular_market_time": _first_text(row, "update_time"),
        "exchange_timezone": None,
        "source": "Moomoo OpenD market snapshot",
        "source_confidence": "DECLARED",
    }


def _latest_session_price(row: dict[str, Any]) -> float | None:
    for key in (
        "overnight_price",
        "after_price",
        "pre_price",
        "last_price",
    ):
        value = _optional_float(row.get(key))
        if value is not None and value > 0:
            return value
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip().lower() in {"", "nan", "none"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_sdk() -> Any:
    try:
        return importlib.import_module("moomoo")
    except ImportError as error:
        raise MoomooProviderError(
            "The optional moomoo-api package is not installed. Install it and "
            "run local OpenD before using import-moomoo-watchlist."
        ) from error


def _ensure_opend_available(host: str, port: int) -> None:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return
    except OSError as error:
        raise MoomooProviderError(
            "Moomoo OpenD is not reachable at "
            f"{host}:{port}. Start and log in to local OpenD, then retry. "
            "The moomoo-api Python package alone is not enough because "
            "watchlists live behind the user's Moomoo/OpenD session."
        ) from error


def _discover_groups(
    quote_context: Any,
    sdk: Any,
    *,
    high_frequency_retry_seconds: float,
) -> tuple[str, ...]:
    getter = getattr(quote_context, "get_user_security_group", None)
    if not callable(getter):
        raise MoomooProviderError(
            "This Moomoo SDK does not expose get_user_security_group; pass --group."
        )
    table = _call_with_retry(
        getter,
        sdk,
        "get_user_security_group",
        high_frequency_retry_seconds=high_frequency_retry_seconds,
    )
    groups = []
    for row in _records(table):
        name = _first_text(row, "group_name", "name", "group")
        if name:
            groups.append(name)
    return tuple(dict.fromkeys(groups))


def _call_with_retry(
    call: Any,
    sdk: Any,
    operation: str,
    *,
    high_frequency_retry_seconds: float,
) -> Any:
    try:
        return _unwrap_response(call(), sdk, operation)
    except MoomooProviderError as error:
        if high_frequency_retry_seconds > 0 and _is_high_frequency_error(error):
            time.sleep(high_frequency_retry_seconds)
            return _unwrap_response(call(), sdk, operation)
        raise


def _is_high_frequency_error(error: MoomooProviderError) -> bool:
    return "high frequency" in str(error).lower()


def _unwrap_response(response: Any, sdk: Any, operation: str) -> Any:
    if not isinstance(response, tuple) or len(response) < 2:
        raise MoomooProviderError(f"{operation} returned an unexpected response shape")
    ret, data = response[0], response[1]
    ok = getattr(sdk, "RET_OK", 0)
    if ret != ok:
        raise MoomooProviderError(f"{operation} failed: {data}")
    return data


def _items_from_table(group_name: str, table: Any) -> list[MoomooWatchlistItem]:
    items = []
    for row in _records(table):
        code = _first_text(row, "code", "stock_code", "security", "symbol")
        if not code:
            continue
        market, symbol = _normalize_code(code)
        items.append(
            MoomooWatchlistItem(
                group_name=group_name,
                code=code.strip().upper(),
                symbol=symbol,
                market=market,
                name=_first_text(row, "name", "stock_name", "security_name"),
            )
        )
    return items


def _records(table: Any) -> list[dict[str, Any]]:
    if table is None:
        return []
    if hasattr(table, "to_dict"):
        records = table.to_dict("records")
        if isinstance(records, list):
            return [dict(row) for row in records if isinstance(row, dict)]
    if isinstance(table, list):
        return [dict(row) for row in table if isinstance(row, dict)]
    if isinstance(table, dict):
        values = list(table.values())
        if values and all(isinstance(value, list) for value in values):
            return [
                {key: value[index] for key, value in table.items()}
                for index in range(min(len(value) for value in values))
            ]
        return [table]
    raise MoomooProviderError("Moomoo watchlist response is not table-like")


def _first_text(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _normalize_code(code: str) -> tuple[str | None, str]:
    normalized = code.strip().upper()
    if "." not in normalized:
        return None, normalized
    market, symbol = normalized.split(".", 1)
    return market or None, symbol


def _payload(
    items: list[MoomooWatchlistItem],
    host: str,
    port: int,
) -> dict:
    group_map: dict[str, list[MoomooWatchlistItem]] = {}
    for item in items:
        group_map.setdefault(item.group_name, []).append(item)
    unique_symbols = sorted({item.symbol for item in items})
    return {
        "schema_version": 1,
        "source": "moomoo-opend",
        "host": host,
        "port": port,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "group_count": len(group_map),
        "symbol_count": len(unique_symbols),
        "unique_symbols": unique_symbols,
        "groups": [
            {
                "group_name": group_name,
                "symbol_count": len({item.symbol for item in group_items}),
                "symbols": sorted({item.symbol for item in group_items}),
            }
            for group_name, group_items in sorted(group_map.items())
        ],
        "items": [
            asdict(item)
            for item in sorted(items, key=lambda item: (item.group_name, item.code))
        ],
    }
