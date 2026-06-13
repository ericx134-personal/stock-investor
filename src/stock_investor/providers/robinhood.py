from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..data import Price


def _parse_timestamp(value: object) -> datetime:
    text = str(value).replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        fraction, offset = tail.split("+", 1) if "+" in tail else (tail, "")
        text = f"{head}.{fraction[:6]}" + (f"+{offset}" if offset else "")
    return datetime.fromisoformat(text)


def parse_historical_response(payload: dict) -> dict[str, list[Price]]:
    """Parse an exported Robinhood MCP historical response into monitor prices."""
    results = payload.get("data", {}).get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("Robinhood historical response contains no results")

    prices: dict[str, list[Price]] = {}
    for result in results:
        symbol = str(result.get("symbol", "")).strip().upper()
        interval = str(result.get("interval", "")).strip().lower()
        if not symbol:
            raise ValueError("Robinhood historical result symbol cannot be empty")
        if interval != "day":
            raise ValueError(
                f"{symbol} interval must be day for the daily monitor, received {interval}"
            )
        bars = result.get("bars")
        if not isinstance(bars, list):
            raise ValueError(f"{symbol} bars must be a list")
        history = []
        for bar in bars:
            if bar.get("interpolated") is True:
                continue
            close = float(bar.get("close_price"))
            if close <= 0:
                raise ValueError(f"{symbol} has non-positive close")
            begins_at = str(bar.get("begins_at", ""))
            try:
                observed = _parse_timestamp(begins_at)
            except ValueError as error:
                raise ValueError(f"{symbol} has invalid begins_at") from error
            history.append(
                Price(
                    observed.date(),
                    close,
                    float(bar["open_price"]) if bar.get("open_price") is not None else None,
                    float(bar["high_price"]) if bar.get("high_price") is not None else None,
                    float(bar["low_price"]) if bar.get("low_price") is not None else None,
                    float(bar["volume"]) if bar.get("volume") is not None else None,
                )
            )
        history.sort(key=lambda item: item.date)
        if len({item.date for item in history}) != len(history):
            raise ValueError(f"{symbol} has duplicate price dates")
        prices[symbol] = history
    return prices


def load_historical_response(path: str | Path) -> dict[str, list[Price]]:
    return parse_historical_response(json.loads(Path(path).read_text()))


def extract_historicals_from_session(path: str | Path) -> dict[str, list[Price]]:
    """Extract daily histories and latest regular-session quotes from a session."""
    latest: dict[str, list[Price]] = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        payload = record.get("payload", {})
        invocation = payload.get("invocation", {})
        if (
            record.get("type") != "event_msg"
            or payload.get("type") != "mcp_tool_call_end"
            or invocation.get("server") != "robinhood"
        ):
            continue
        structured = (
            payload.get("result", {}).get("Ok", {}).get("structuredContent", {})
        )
        if invocation.get("tool") == "get_equity_quotes":
            for result in structured.get("data", {}).get("results", []):
                quote = result.get("quote", {})
                symbol = str(quote.get("symbol", "")).strip().upper()
                if not symbol or not quote.get("last_trade_price"):
                    continue
                observed = _parse_timestamp(quote["venue_last_trade_time"])
                close = float(quote["last_trade_price"])
                history = latest.setdefault(symbol, [])
                same_day = next((item for item in history if item.date == observed.date()), None)
                price = Price(
                    observed.date(),
                    close,
                    same_day.open if same_day else None,
                    max(same_day.high, close) if same_day and same_day.high is not None else None,
                    min(same_day.low, close) if same_day and same_day.low is not None else None,
                    same_day.volume if same_day else None,
                )
                history = [item for item in history if item.date != price.date]
                history.append(price)
                latest[symbol] = sorted(history, key=lambda item: item.date)
            continue
        if invocation.get("tool") != "get_equity_historicals":
            continue
        results = structured.get("data", {}).get("results", [])
        daily_results = [
            result for result in results if str(result.get("interval", "")).lower() == "day"
        ]
        if not daily_results:
            continue
        parsed = parse_historical_response({"data": {"results": daily_results}})
        for symbol, history in parsed.items():
            existing = {
                item.date: item for item in latest.get(symbol, [])
            }
            existing.update({item.date: item for item in history})
            latest[symbol] = [existing[item] for item in sorted(existing)]
    if not latest:
        raise ValueError("session contains no structured Robinhood daily historicals")
    return latest
