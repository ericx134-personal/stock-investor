from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..data import Price
from ..io import atomic_text_writer


BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"
Transport = Callable[[str, dict[str, str]], dict]


def _request_json(url: str, headers: dict[str, str]) -> dict:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_daily_bars(
    symbols: list[str],
    start: str,
    end: str,
    key_id: str,
    secret_key: str,
    feed: str = "iex",
    transport: Transport = _request_json,
) -> dict[str, list[Price]]:
    """Fetch adjusted daily bars from Alpaca's official Market Data API."""
    if not symbols:
        raise ValueError("at least one symbol is required")
    headers = {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
    }
    query = {
        "symbols": ",".join(sorted(set(symbols))),
        "timeframe": "1Day",
        "start": start,
        "end": end,
        "limit": "10000",
        "adjustment": "all",
        "feed": feed,
        "sort": "asc",
    }
    prices: dict[str, list[Price]] = {}

    while True:
        payload = transport(f"{BASE_URL}?{urlencode(query)}", headers)
        for symbol, bars in payload.get("bars", {}).items():
            prices.setdefault(symbol, []).extend(
                Price(
                    date.fromisoformat(bar["t"][:10]),
                    float(bar["c"]),
                    float(bar.get("o", bar["c"])),
                    float(bar.get("h", bar["c"])),
                    float(bar.get("l", bar["c"])),
                    float(bar["v"]) if bar.get("v") is not None else None,
                )
                for bar in bars
            )
        token = payload.get("next_page_token")
        if not token:
            break
        query["page_token"] = token

    return prices


def write_prices_csv(prices: dict[str, list[Price]], path: str | Path) -> None:
    output = Path(path)
    with atomic_text_writer(output, newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("date", "symbol", "close", "open", "high", "low", "volume"))
        for symbol in sorted(prices):
            for price in sorted(prices[symbol], key=lambda item: item.date):
                writer.writerow(
                    (
                        price.date.isoformat(),
                        symbol,
                        price.close,
                        "" if price.open is None else price.open,
                        "" if price.high is None else price.high,
                        "" if price.low is None else price.low,
                        "" if price.volume is None else price.volume,
                    )
                )
