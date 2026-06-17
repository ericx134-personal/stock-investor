from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..data import Price


BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
Transport = Callable[[str], dict]
Sleep = Callable[[float], None]
FailureSink = Callable[["YahooProviderFailure"], None]


@dataclass(frozen=True)
class YahooProviderFailure:
    symbol: str
    failure_class: str
    message: str
    retryable: bool
    attempt: int
    max_attempts: int
    will_retry: bool


class YahooChartError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


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
    retry_delays: tuple[float, ...] = (1.0, 3.0, 8.0),
    sleep: Sleep = time.sleep,
    on_failure: FailureSink | None = None,
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
    max_attempts = len(retry_delays) + 1
    for symbol in sorted(set(item.strip().upper() for item in symbols if item.strip())):
        for attempt in range(1, max_attempts + 1):
            try:
                history = _fetch_symbol_history(symbol, query, transport)
                if history:
                    prices[symbol] = history
                break
            except Exception as error:
                failure_class, retryable = _classify_failure(error)
                will_retry = retryable and attempt < max_attempts
                failure = YahooProviderFailure(
                    symbol=symbol,
                    failure_class=failure_class,
                    message=str(error),
                    retryable=retryable,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    will_retry=will_retry,
                )
                if on_failure:
                    on_failure(failure)
                if will_retry:
                    sleep(float(retry_delays[attempt - 1]))
                    continue
                break
    return prices


def _fetch_symbol_history(
    symbol: str,
    query: str,
    transport: Transport,
) -> list[Price]:
    payload = transport(f"{BASE_URL}/{symbol}?{query}")
    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise YahooChartError(
            str(error.get("code") or "chart_error"),
            str(error.get("description") or ""),
        )
    result = (chart.get("result") or [None])[0]
    if not result:
        return []
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    history = []
    for index, timestamp in enumerate(timestamps):
        close = _optional_index_float(quote.get("close"), index)
        if close is None or float(close) <= 0:
            continue
        open_price = _optional_index_float(quote.get("open"), index)
        high = _optional_index_float(quote.get("high"), index)
        low = _optional_index_float(quote.get("low"), index)
        high, low = _valid_price_envelope(float(close), open_price, high, low)
        observed_date = date.fromisoformat(
            time.strftime("%Y-%m-%d", time.gmtime(timestamp))
        )
        history.append(
            Price(
                observed_date,
                float(close),
                open_price,
                high,
                low,
                _optional_index_float(quote.get("volume"), index),
            )
        )
    return sorted(history, key=lambda item: item.date)


def _classify_failure(error: Exception) -> tuple[str, bool]:
    if isinstance(error, HTTPError):
        if error.code == 429:
            return "rate_limited", True
        if error.code in {408, 425} or 500 <= error.code <= 599:
            return "server_or_timeout", True
        return "client_error", False
    if isinstance(error, (URLError, TimeoutError, ConnectionError)):
        return "network", True
    if isinstance(error, json.JSONDecodeError):
        return "invalid_response", True
    if isinstance(error, YahooChartError):
        normalized = f"{error.code} {error}".lower()
        if "not found" in normalized or "no data" in normalized:
            return "no_data", False
        if (
            "rate" in normalized
            or "timeout" in normalized
            or "unavailable" in normalized
        ):
            return "provider_temporary", True
        return "provider_error", False
    return "invalid_response", False


def _optional_index_float(values: list | None, index: int) -> float | None:
    if values is None or index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _valid_price_envelope(
    close: float,
    open_price: float | None,
    high: float | None,
    low: float | None,
) -> tuple[float | None, float | None]:
    price_points = [
        value
        for value in (close, open_price, high, low)
        if value is not None
    ]
    if high is not None:
        high = max(price_points)
    if low is not None:
        low = min(price_points)
    return high, low


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
