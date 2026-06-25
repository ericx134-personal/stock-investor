from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .data import Position


def build_candidate_boundary(
    positions: list[Position],
    current_direction_forecasts: list[dict[str, Any]],
    *,
    broker_universe: dict[str, Any] | None = None,
    moomoo_watchlists: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Document and guard the line between holdings and research candidates."""
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    held_symbols = {
        position.symbol
        for position in positions
        if position.shares > 0
    }
    csv_watchlist_symbols = {
        position.symbol
        for position in positions
        if position.shares == 0
    }
    broker_watchlist_only = _broker_watchlist_only_symbols(broker_universe)
    if not broker_watchlist_only:
        broker_watchlist_only = _moomoo_symbols(moomoo_watchlists) - held_symbols
    research_candidate_symbols = csv_watchlist_symbols | broker_watchlist_only
    forecast_symbols = {
        _symbol(record.get("symbol"))
        for record in current_direction_forecasts
        if _symbol(record.get("symbol"))
    }
    forecast_violations = sorted(forecast_symbols - held_symbols)
    return {
        "schema_version": "candidate-boundary-v1",
        "generated_at": generated_at,
        "forecast_scope": "held_positions_only",
        "held_symbols": sorted(held_symbols),
        "csv_watchlist_symbols": sorted(csv_watchlist_symbols),
        "broker_watchlist_only_symbols": sorted(broker_watchlist_only),
        "research_candidate_symbols": sorted(research_candidate_symbols),
        "current_direction_forecast_symbols": sorted(forecast_symbols),
        "direction_forecast_violations": forecast_violations,
        "counts": {
            "held_symbols": len(held_symbols),
            "csv_watchlist_symbols": len(csv_watchlist_symbols),
            "broker_watchlist_only_symbols": len(broker_watchlist_only),
            "research_candidate_symbols": len(research_candidate_symbols),
            "current_direction_forecast_symbols": len(forecast_symbols),
            "direction_forecast_violations": len(forecast_violations),
        },
        "notes": [
            "Current direction forecasts must remain scoped to held positions.",
            "Watchlist-only symbols are research candidates until explicitly promoted into portfolio/positions.csv.",
        ],
    }


def _broker_watchlist_only_symbols(payload: dict[str, Any] | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    return {
        symbol
        for item in payload.get("watchlist_only") or []
        if isinstance(item, dict)
        if (symbol := _symbol(item.get("symbol")))
    }


def _moomoo_symbols(payload: dict[str, Any] | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    symbols = {
        _symbol(item.get("symbol"))
        for item in payload.get("items") or []
        if isinstance(item, dict)
    }
    symbols.update(_symbol(value) for value in payload.get("unique_symbols") or [])
    return {symbol for symbol in symbols if symbol}


def _symbol(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.upper() if text else None
