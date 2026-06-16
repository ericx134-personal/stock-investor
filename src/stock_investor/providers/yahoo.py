from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..data import Price


BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
Transport = Callable[[str], dict]


def _request_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "stock-investor/1.0"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def _unix_utc(day: str) -> int:
    return int(
        datetime.combine(
            date.fromisoformat(day),
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).timestamp()
    )


def fetch_yahoo_daily_bars(
    symbols: list[str],
    start: str,
    end: str,
    *,
    transport: Transport = _request_json,
) -> dict[str, list[Price]]:
    """Fetch daily bars from Yahoo Finance's no-credential chart endpoint."""
    if not symbols:
        raise ValueError("at least one symbol is required")
    prices: dict[str, list[Price]] = {}
    query = urlencode(
        {
            "period1": _unix_utc(start),
            "period2": _unix_utc(end),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    for symbol in sorted(set(item.strip().upper() for item in symbols if item.strip())):
        payload = transport(f"{BASE_URL}/{symbol}?{query}")
        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            continue
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        history = []
        for index, timestamp in enumerate(timestamps):
            close = _optional_index_float(quote.get("close"), index)
            if close is None or float(close) <= 0:
                continue
            observed_date = date.fromisoformat(
                time.strftime("%Y-%m-%d", time.gmtime(timestamp))
            )
            history.append(
                Price(
                    observed_date,
                    float(close),
                    _optional_index_float(quote.get("open"), index),
                    _optional_index_float(quote.get("high"), index),
                    _optional_index_float(quote.get("low"), index),
                    _optional_index_float(quote.get("volume"), index),
                )
            )
        if history:
            prices[symbol] = sorted(history, key=lambda item: item.date)
    return prices


def _optional_index_float(values: list | None, index: int) -> float | None:
    if values is None or index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def merge_price_histories(
    existing: dict[str, list[Price]],
    updates: dict[str, list[Price]],
) -> dict[str, list[Price]]:
    merged = {
        symbol: {price.date: price for price in history}
        for symbol, history in existing.items()
    }
    for symbol, history in updates.items():
        merged.setdefault(symbol, {}).update({price.date: price for price in history})
    return {
        symbol: [by_date[day] for day in sorted(by_date)]
        for symbol, by_date in sorted(merged.items())
    }
