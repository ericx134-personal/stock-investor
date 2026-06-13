import json
import tempfile
import unittest
from pathlib import Path

from stock_investor.data import load_positions
from stock_investor.robinhood import (
    import_robinhood_snapshot,
    load_robinhood_cash,
    sanitize_robinhood_snapshot,
    write_robinhood_baseline,
    write_robinhood_import,
)


class RobinhoodImportTests(unittest.TestCase):
    def test_sanitizer_whitelists_fields_and_drops_account_identifiers(self):
        sanitized = sanitize_robinhood_snapshot(
            {
                "accounts": [
                    {
                        "account_number": "SECRET",
                        "nickname": "Main",
                        "cash": -25,
                        "buying_power": 100,
                        "positions": [
                            {
                                "symbol": " aapl ",
                                "quantity": "2",
                                "average_cost": "100",
                                "instrument_id": "SECRET-ID",
                            }
                        ],
                    }
                ]
            },
            captured_at="2026-06-12T00:00:00+00:00",
        )
        encoded = json.dumps(sanitized)
        self.assertNotIn("SECRET", encoded)
        self.assertNotIn("nickname", encoded)
        self.assertEqual(sanitized["accounts"][0]["positions"][0]["symbol"], "AAPL")
        self.assertEqual(sanitized["accounts"][0]["cash"], -25)

    def test_import_aggregates_accounts_and_preserves_metadata_and_watchlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            metadata = root / "metadata.csv"
            output = root / "positions.csv"
            summary_output = root / "summary.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {
                                "cash": 100,
                                "buying_power": 150,
                                "positions": [
                                    {
                                        "symbol": "aapl",
                                        "quantity": 2,
                                        "average_cost": 100,
                                    },
                                    {
                                        "symbol": "AAPL260101C00150000",
                                        "asset_type": "option",
                                        "quantity": 1,
                                        "average_cost": 5,
                                    },
                                ],
                            },
                            {
                                "cash": 50,
                                "buying_power": 75,
                                "positions": [
                                    {
                                        "symbol": "AAPL",
                                        "quantity": 1,
                                        "average_cost": 130,
                                    }
                                ],
                            },
                        ]
                    }
                )
            )
            metadata.write_text(
                "symbol,shares,average_cost,max_portfolio_weight,quality,"
                "valuation,revisions,thesis_broken,cik,sector,theme\n"
                "AAPL,1,90,0.2,,,,false,320193,Technology,AI\n"
                "MSFT,0,0,0.1,,,,false,789019,Technology,AI\n"
            )
            positions, summary = import_robinhood_snapshot(snapshot, metadata)
            write_robinhood_import(positions, summary, output, summary_output)
            loaded = {item.symbol: item for item in load_positions(output)}
            summary_payload = json.loads(summary_output.read_text())
            imported_cash = load_robinhood_cash(summary_output)

        self.assertEqual(loaded["AAPL"].shares, 3)
        self.assertEqual(loaded["AAPL"].average_cost, 110)
        self.assertEqual(loaded["AAPL"].sector, "Technology")
        self.assertEqual(loaded["MSFT"].shares, 0)
        self.assertEqual(summary_payload["total_cash"], 150)
        self.assertEqual(summary_payload["total_buying_power"], 225)
        self.assertEqual(summary_payload["skipped_non_equity_positions"], 1)
        self.assertEqual(imported_cash, 150)
        self.assertNotIn("account", summary_payload)

    def test_new_holding_uses_conservative_blank_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {
                                "positions": [
                                    {
                                        "symbol": "NEW",
                                        "quantity": "2.5",
                                        "average_cost": "40",
                                    }
                                ]
                            }
                        ]
                    }
                )
            )
            position = import_robinhood_snapshot(path)[0][0]
        self.assertEqual(position.max_portfolio_weight, 0.10)
        self.assertIsNone(position.sector)
        self.assertIsNone(position.quality)

    def test_import_preserves_negative_margin_cash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(
                '{"accounts":[{"cash":-250,"buying_power":100,'
                '"positions":[{"symbol":"ABC","quantity":10,"average_cost":20}]}]}'
            )
            _, summary = import_robinhood_snapshot(path)
            summary_path = Path(directory) / "summary.json"
            write_robinhood_import([], summary, Path(directory) / "positions.csv", summary_path)
            imported_cash = load_robinhood_cash(summary_path)
        self.assertEqual(summary.total_cash, -250)
        self.assertEqual(imported_cash, -250)

    def test_import_rejects_bad_or_empty_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text('{"accounts": []}')
            with self.assertRaisesRegex(ValueError, "non-empty accounts"):
                import_robinhood_snapshot(path)
            path.write_text(
                '{"accounts":[{"positions":[{"symbol":"ABC","quantity":-1,'
                '"average_cost":10}]}]}'
            )
            with self.assertRaisesRegex(ValueError, "cannot be negative"):
                import_robinhood_snapshot(path)

    def test_baseline_history_skips_unchanged_portfolio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                '{"accounts":[{"cash":10,"buying_power":20,'
                '"positions":[{"symbol":"ABC","quantity":2,"average_cost":5}]}]}'
            )
            positions, summary = import_robinhood_snapshot(snapshot)
            history = root / "baseline.jsonl"
            first = write_robinhood_baseline(positions, summary, history)
            second = write_robinhood_baseline(positions, summary, history)
            record = json.loads(history.read_text().strip())
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(record["holdings"][0]["symbol"], "ABC")
        self.assertNotIn("account", json.dumps(record))


if __name__ == "__main__":
    unittest.main()
