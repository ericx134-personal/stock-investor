import tempfile
import unittest
from pathlib import Path

from stock_investor.data import write_prices_csv
from stock_investor.providers.robinhood import (
    extract_historicals_from_session,
    parse_historical_response,
)


class RobinhoodProviderTests(unittest.TestCase):
    def test_parse_filters_interpolated_bars_and_normalizes_symbols(self):
        prices = parse_historical_response(
            {
                "data": {
                    "results": [
                        {
                            "symbol": " aapl ",
                            "interval": "day",
                            "bars": [
                                {
                                    "begins_at": "2026-01-03T00:00:00Z",
                                    "close_price": "11",
                                    "open_price": "10",
                                    "high_price": "12",
                                    "low_price": "9",
                                    "volume": 100,
                                },
                                {
                                    "begins_at": "2026-01-02T00:00:00Z",
                                    "close_price": "10",
                                    "interpolated": True,
                                },
                                {
                                    "begins_at": "2026-01-01T00:00:00Z",
                                    "close_price": "9",
                                },
                            ],
                        }
                    ]
                }
            }
        )
        self.assertEqual([item.close for item in prices["AAPL"]], [9, 11])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prices.csv"
            write_prices_csv(prices, output)
            content = output.read_text()
        self.assertEqual(
            content,
            "date,symbol,close,open,high,low,volume\n"
            "2026-01-01,AAPL,9.0,,,,\n"
            "2026-01-03,AAPL,11.0,10.0,12.0,9.0,100.0\n",
        )

    def test_parse_requires_daily_bars(self):
        with self.assertRaisesRegex(ValueError, "interval must be day"):
            parse_historical_response(
                {
                    "data": {
                        "results": [
                            {"symbol": "ABC", "interval": "week", "bars": []}
                        ]
                    }
                }
            )

    def test_extract_historicals_from_session_ignores_other_mcp_data(self):
        result = {
            "type": "event_msg",
            "payload": {
                "type": "mcp_tool_call_end",
                "invocation": {
                    "server": "robinhood",
                    "tool": "get_equity_historicals",
                },
                "result": {
                    "Ok": {
                        "structuredContent": {
                            "data": {
                                "results": [
                                    {
                                        "symbol": "ABC",
                                        "interval": "day",
                                        "bars": [
                                            {
                                                "begins_at": "2026-01-01T00:00:00Z",
                                                "close_price": "10",
                                            }
                                        ],
                                    }
                                ]
                            }
                        }
                    }
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text('{"type":"event_msg","payload":{"type":"other"}}\n')
            with path.open("a") as handle:
                import json

                handle.write(json.dumps(result) + "\n")
            prices = extract_historicals_from_session(path)
        self.assertEqual(prices["ABC"][0].close, 10)

    def test_extract_historicals_reconciles_latest_regular_quote(self):
        quote = {
            "type": "event_msg",
            "payload": {
                "type": "mcp_tool_call_end",
                "invocation": {"server": "robinhood", "tool": "get_equity_quotes"},
                "result": {
                    "Ok": {
                        "structuredContent": {
                            "data": {
                                "results": [
                                    {
                                        "quote": {
                                            "symbol": "ABC",
                                            "last_trade_price": "12",
                                            "venue_last_trade_time": (
                                                "2026-01-02T20:00:00.123456789Z"
                                            ),
                                        }
                                    }
                                ]
                            }
                        }
                    }
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text(__import__("json").dumps(quote) + "\n")
            prices = extract_historicals_from_session(path)
        self.assertEqual(prices["ABC"][0].close, 12)


if __name__ == "__main__":
    unittest.main()
