import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from stock_investor.data import Price
from stock_investor.providers.yahoo import (
    fetch_yahoo_daily_bars,
    merge_price_histories,
)


def ts(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


class YahooProviderTests(unittest.TestCase):
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

    def test_fetch_daily_bars_skips_missing_symbols(self):
        prices = fetch_yahoo_daily_bars(
            ["MISSING"],
            "2026-06-01",
            "2026-06-17",
            transport=lambda url: {"chart": {"result": None}},
        )
        self.assertEqual(prices, {})

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
