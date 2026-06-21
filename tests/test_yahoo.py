import unittest
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from stock_investor.data import Price
from stock_investor.cli import _clip_price_histories
from stock_investor.providers.yahoo import (
    fetch_yahoo_daily_bars,
    fetch_yahoo_latest_quotes,
    merge_price_histories,
)


def ts(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


class YahooProviderTests(unittest.TestCase):
    def test_clip_price_histories_respects_account_history_start(self):
        prices = {
            "HOOD": [
                Price(date(2024, 6, 1), 20.0),
                Price(date(2024, 6, 21), 22.0),
            ],
            "SPY": [Price(date(2024, 5, 31), 500.0)],
        }

        clipped = _clip_price_histories(prices, "2024-06-20")

        self.assertEqual(list(clipped), ["HOOD"])
        self.assertEqual([item.date for item in clipped["HOOD"]], [date(2024, 6, 21)])

    def test_fetch_daily_bars_parses_chart_payload(self):
        calls = []

        def transport(url):
            calls.append(url)
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [ts("2026-06-15"), ts("2026-06-16")],
                            "indicators": {
                                "quote": [
                                    {
                                        "close": [98.12, 96.17],
                                        "open": [94.0, 97.0],
                                        "high": [99.0, 98.0],
                                        "low": [93.0, 95.0],
                                        "volume": [1000, 1200],
                                    }
                                ]
                            },
                        }
                    ]
                }
            }

        prices = fetch_yahoo_daily_bars(
            ["HOOD"], "2026-06-01", "2026-06-17", transport=transport
        )
        query = parse_qs(urlparse(calls[0]).query)
        self.assertEqual(query["interval"], ["1d"])
        self.assertEqual([item.close for item in prices["HOOD"]], [98.12, 96.17])
        self.assertEqual(prices["HOOD"][0].volume, 1000)

    def test_fetch_latest_quotes_parses_chart_meta(self):
        calls = []

        def transport(url):
            calls.append(url)
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 101.5,
                                "chartPreviousClose": 100.0,
                                "regularMarketTime": 1780000000,
                                "exchangeTimezoneName": "America/New_York",
                            },
                            "timestamp": [1780000000, 1780000060],
                            "indicators": {"quote": [{"close": [100.5, 101.5]}]},
                        }
                    ]
                }
            }

        quotes = fetch_yahoo_latest_quotes(["HOOD"], transport=transport)
        query = parse_qs(urlparse(calls[0]).query)
        self.assertEqual(query["interval"], ["1m"])
        self.assertEqual(query["range"], ["1d"])
        self.assertEqual(quotes["HOOD"]["price"], 101.5)
        self.assertEqual(quotes["HOOD"]["previous_close"], 100.0)
        self.assertAlmostEqual(quotes["HOOD"]["today_return"], 0.015)
        self.assertEqual(
            quotes["HOOD"]["intraday_path"],
            [
                {"time": 1780000000, "price": 100.5},
                {"time": 1780000060, "price": 101.5},
            ],
        )
        self.assertEqual(quotes["HOOD"]["source"], "Yahoo Finance chart quote")

    def test_fetch_latest_quotes_skips_unavailable_symbol_without_aborting(self):
        calls = []
        failures = []

        def transport(url):
            calls.append(url)
            if "BBBY+" in url:
                raise HTTPError(url, 404, "Not Found", {}, None)
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 101.5,
                                "chartPreviousClose": 100.0,
                            },
                            "timestamp": [1780000000],
                            "indicators": {"quote": [{"close": [101.5]}]},
                        }
                    ]
                }
            }

        quotes = fetch_yahoo_latest_quotes(
            ["BBBY+", "HOOD"], transport=transport, on_failure=failures.append
        )

        self.assertIn("BBBY+", calls[0])
        self.assertIn("HOOD", calls[1])
        self.assertNotIn("BBBY+", quotes)
        self.assertEqual(quotes["HOOD"]["price"], 101.5)
        self.assertEqual(failures[0].symbol, "BBBY+")
        self.assertEqual(failures[0].failure_class, "client_error")
        self.assertFalse(failures[0].will_retry)

    def test_fetch_daily_bars_normalizes_implausible_yahoo_envelopes(self):
        prices = fetch_yahoo_daily_bars(
            ["PLTR"],
            "2026-06-01",
            "2026-06-17",
            transport=lambda url: {
                "chart": {
                    "result": [
                        {
                            "timestamp": [ts("2026-06-16")],
                            "indicators": {
                                "quote": [
                                    {
                                        "close": [133.25],
                                        "open": [134.59],
                                        "high": [134.50],
                                        "low": [129.62],
                                    }
                                ]
                            },
                        }
                    ]
                }
            },
        )
        self.assertEqual(prices["PLTR"][0].high, 134.59)
        self.assertEqual(prices["PLTR"][0].low, 129.62)

    def test_fetch_daily_bars_skips_missing_symbols(self):
        prices = fetch_yahoo_daily_bars(
            ["MISSING"],
            "2026-06-01",
            "2026-06-17",
            transport=lambda url: {"chart": {"result": None}},
        )
        self.assertEqual(prices, {})

    def test_fetch_daily_bars_retries_retryable_network_failures(self):
        calls = []
        sleeps = []
        failures = []

        def transport(url):
            calls.append(url)
            if len(calls) == 1:
                raise URLError("temporary DNS failure")
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [ts("2026-06-16")],
                            "indicators": {"quote": [{"close": [96.17]}]},
                        }
                    ]
                }
            }

        prices = fetch_yahoo_daily_bars(
            ["HOOD"],
            "2026-06-01",
            "2026-06-17",
            transport=transport,
            retry_delays=(0.0,),
            sleep=sleeps.append,
            on_failure=failures.append,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.0])
        self.assertEqual(prices["HOOD"][0].close, 96.17)
        self.assertEqual(failures[0].failure_class, "network")
        self.assertTrue(failures[0].will_retry)

    def test_fetch_daily_bars_classifies_exhausted_rate_limits(self):
        failures = []

        def transport(url):
            raise HTTPError(url, 429, "Too Many Requests", {}, None)

        prices = fetch_yahoo_daily_bars(
            ["HOOD"],
            "2026-06-01",
            "2026-06-17",
            transport=transport,
            retry_delays=(0.0, 0.0),
            sleep=lambda seconds: None,
            on_failure=failures.append,
        )
        self.assertEqual(prices, {})
        self.assertEqual([failure.failure_class for failure in failures], ["rate_limited"] * 3)
        self.assertEqual([failure.will_retry for failure in failures], [True, True, False])

    def test_fetch_daily_bars_classifies_non_retryable_chart_errors(self):
        failures = []

        prices = fetch_yahoo_daily_bars(
            ["OLD"],
            "2026-06-01",
            "2026-06-17",
            transport=lambda url: {
                "chart": {
                    "result": None,
                    "error": {
                        "code": "Not Found",
                        "description": "No data found for symbol",
                    },
                }
            },
            retry_delays=(0.0, 0.0),
            sleep=lambda seconds: None,
            on_failure=failures.append,
        )
        self.assertEqual(prices, {})
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].failure_class, "no_data")
        self.assertFalse(failures[0].retryable)
        self.assertFalse(failures[0].will_retry)

    def test_merge_price_histories_preserves_old_unavailable_symbols(self):
        existing = {
            "OLD": [Price(datetime(2026, 6, 12).date(), 10)],
            "HOOD": [Price(datetime(2026, 6, 12).date(), 93.19)],
        }
        updates = {"HOOD": [Price(datetime(2026, 6, 15).date(), 98.12)]}
        merged = merge_price_histories(existing, updates)
        self.assertEqual([item.close for item in merged["HOOD"]], [93.19, 98.12])
        self.assertEqual(merged["OLD"][0].close, 10)


if __name__ == "__main__":
    unittest.main()
