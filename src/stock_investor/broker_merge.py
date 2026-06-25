from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import atomic_write_text


SCHEMA_VERSION = 1


def load_broker_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    source = Path(path)
    if not source.exists():
        return None
    payload = json.loads(source.read_text())
    return payload if isinstance(payload, dict) else None


def merge_broker_universe(
    *,
    snaptrade_snapshot: dict[str, Any] | None = None,
    moomoo_watchlists: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Merge read-only broker holdings and watchlist symbols with attribution."""
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    holdings_by_symbol: dict[str, dict[str, Any]] = {}
    for source in _snaptrade_sources(snaptrade_snapshot):
        symbol = source["symbol"]
        row = holdings_by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "description": source.get("description"),
                "instrument_kinds": set(),
                "shares": 0.0,
                "market_value": 0.0,
                "_avg_cost_weight": 0.0,
                "_avg_cost_value": 0.0,
                "sources": [],
            },
        )
        if not row.get("description") and source.get("description"):
            row["description"] = source["description"]
        if source.get("instrument_kind"):
            row["instrument_kinds"].add(source["instrument_kind"])
        units = source.get("shares") or 0.0
        row["shares"] += units
        row["market_value"] += source.get("market_value") or 0.0
        average_cost = source.get("average_cost")
        if average_cost is not None and units:
            weight = abs(units)
            row["_avg_cost_weight"] += weight
            row["_avg_cost_value"] += average_cost * weight
        row["sources"].append(source)

    holdings = [_finalize_holding(row) for row in holdings_by_symbol.values()]
    holdings.sort(key=lambda item: (-abs(item.get("market_value") or 0.0), item["symbol"]))

    watchlist_rows = _moomoo_watchlist_rows(moomoo_watchlists)
    held_symbols = {item["symbol"] for item in holdings}
    watchlist_only = [
        row
        for symbol, row in sorted(watchlist_rows.items())
        if symbol not in held_symbols
    ]
    watchlist_overlap = [
        {
            "symbol": symbol,
            "groups": row["groups"],
            "source": row["source"],
        }
        for symbol, row in sorted(watchlist_rows.items())
        if symbol in held_symbols
    ]
    sources = _source_summary(snaptrade_snapshot, moomoo_watchlists)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "sources": sources,
        "holdings": holdings,
        "watchlist_only": watchlist_only,
        "watchlist_overlap": watchlist_overlap,
        "counts": {
            "holding_symbols": len(holdings),
            "watchlist_only_symbols": len(watchlist_only),
            "watchlist_overlap_symbols": len(watchlist_overlap),
            "source_positions": sum(len(item["sources"]) for item in holdings),
            "sources": len(sources),
        },
    }


def write_broker_universe(payload: dict[str, Any], path: str | Path) -> None:
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", path)


def build_broker_universe_from_files(
    *,
    output_path: str | Path,
    snaptrade_accounts_path: str | Path | None = None,
    moomoo_watchlists_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = merge_broker_universe(
        snaptrade_snapshot=load_broker_json(snaptrade_accounts_path),
        moomoo_watchlists=load_broker_json(moomoo_watchlists_path),
    )
    write_broker_universe(payload, output_path)
    return payload


def _snaptrade_sources(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    sources = []
    for account_snapshot in snapshot.get("accounts") or []:
        if not isinstance(account_snapshot, dict):
            continue
        account = account_snapshot.get("account") or {}
        if not isinstance(account, dict):
            account = {}
        account_identity = _account_identity(account)
        for position in account_snapshot.get("positions") or []:
            if not isinstance(position, dict):
                continue
            symbol = _symbol(position.get("symbol"))
            shares = _number(position.get("units"))
            if not symbol or shares is None or abs(shares) < 1e-12:
                continue
            price = _number(position.get("price"))
            market_value = _number(position.get("market_value"))
            if market_value is None and price is not None:
                market_value = shares * price
            sources.append(
                {
                    "source": "snaptrade",
                    "broker": account_identity["broker"],
                    "account_name": account_identity["account_name"],
                    "account_number": account_identity["account_number"],
                    "symbol": symbol,
                    "description": position.get("description"),
                    "instrument_kind": position.get("instrument_kind"),
                    "shares": shares,
                    "price": price,
                    "market_value": market_value,
                    "average_cost": _number(position.get("average_purchase_price")),
                }
            )
    return sources


def _account_identity(account: dict[str, Any]) -> dict[str, str | None]:
    return {
        "broker": _text(account.get("institution_name")) or "Unknown",
        "account_name": _text(account.get("name")),
        "account_number": _text(account.get("number")),
    }


def _finalize_holding(row: dict[str, Any]) -> dict[str, Any]:
    avg_cost = None
    if row["_avg_cost_weight"]:
        avg_cost = row["_avg_cost_value"] / row["_avg_cost_weight"]
    return {
        "symbol": row["symbol"],
        "description": row.get("description"),
        "instrument_kinds": sorted(row["instrument_kinds"]),
        "shares": round(row["shares"], 8),
        "market_value": round(row["market_value"], 2),
        "average_cost": None if avg_cost is None else round(avg_cost, 6),
        "source_count": len(row["sources"]),
        "sources": sorted(
            row["sources"],
            key=lambda item: (
                str(item.get("broker") or ""),
                str(item.get("account_name") or ""),
                str(item.get("account_number") or ""),
            ),
        ),
    }


def _moomoo_watchlist_rows(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    items_by_symbol: dict[str, dict[str, Any]] = {}
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = _symbol(item.get("symbol"))
        if not symbol:
            continue
        current = items_by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": item.get("name"),
                "market": item.get("market"),
                "groups": set(),
                "source": "moomoo-opend",
            },
        )
        group_name = _text(item.get("group_name"))
        if group_name:
            current["groups"].add(group_name)
        if not current.get("name") and item.get("name"):
            current["name"] = item.get("name")
        if not current.get("market") and item.get("market"):
            current["market"] = item.get("market")
    for group in payload.get("groups") or []:
        if not isinstance(group, dict):
            continue
        group_name = _text(group.get("group_name") or group.get("name"))
        for value in group.get("symbols") or []:
            symbol = _symbol(value)
            if not symbol:
                continue
            current = items_by_symbol.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": None,
                    "market": None,
                    "groups": set(),
                    "source": "moomoo-opend",
                },
            )
            if group_name:
                current["groups"].add(group_name)
    return {
        symbol: {
            **row,
            "groups": sorted(row["groups"]),
        }
        for symbol, row in items_by_symbol.items()
    }


def _source_summary(
    snaptrade_snapshot: dict[str, Any] | None,
    moomoo_watchlists: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    sources = []
    if isinstance(snaptrade_snapshot, dict):
        sources.append(
            {
                "source": "snaptrade",
                "captured_at": snaptrade_snapshot.get("captured_at"),
                "account_count": snaptrade_snapshot.get("account_count"),
                "position_count": snaptrade_snapshot.get("position_count"),
            }
        )
    if isinstance(moomoo_watchlists, dict):
        sources.append(
            {
                "source": "moomoo-opend",
                "captured_at": moomoo_watchlists.get("captured_at"),
                "group_count": moomoo_watchlists.get("group_count"),
                "symbol_count": moomoo_watchlists.get("symbol_count"),
            }
        )
    return sources


def _symbol(value: Any) -> str | None:
    text = _text(value)
    return text.upper() if text else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
