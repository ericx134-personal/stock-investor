import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from stock_investor.providers.alpaca import fetch_daily_bars, write_prices_csv


class AlpacaTests(unittest.TestCase):
    def test_fetch_daily_bars_uses_adjustments_and_pagination(self):
        calls = []

        def transport(url, headers):
            calls.append((url, headers))
            query = parse_qs(urlparse(url).query)
            if "page_token" not in query:
                return {
                    "bars": {
                        "ABC": [{"t": "2026-01-02T05:00:00Z", "c": 10.5}]
                    },
                    "next_page_token": "next",
                }
            return {
                "bars": {"ABC": [{"t": "2026-01-03T05:00:00Z", "c": 11.0}]},
                "next_page_token": None,
            }

        prices = fetch_daily_bars(
            ["SPY", "ABC", "SPY"],
            "2025-01-01",
            "2026-01-01",
            "key",
            "secret",
            transport=transport,
        )
        first_query = parse_qs(urlparse(calls[0][0]).query)
        self.assertEqual(first_query["adjustment"], ["all"])
        self.assertEqual(first_query["feed"], ["iex"])
        self.assertEqual(first_query["symbols"], ["ABC,SPY"])
        self.assertEqual(calls[0][1]["APCA-API-KEY-ID"], "key")
        self.assertEqual([item.close for item in prices["ABC"]], [10.5, 11.0])

    def test_write_prices_csv_round_trip_shape(self):
        def transport(url, headers):
            return {
                "bars": {"ABC": [{"t": "2026-01-02T05:00:00Z", "c": 10.5}]},
                "next_page_token": None,
            }

        prices = fetch_daily_bars(
            ["ABC"], "2025-01-01", "2026-01-01", "key", "secret", transport=transport
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.csv"
            write_prices_csv(prices, path)
            content = path.read_text()
        self.assertEqual(
            content,
            "date,symbol,close,open,high,low,volume\n"
            "2026-01-02,ABC,10.5,10.5,10.5,10.5,\n",
        )


if __name__ == "__main__":
    unittest.main()
