import json
import tempfile
import unittest
from pathlib import Path

from stock_investor.broker_merge import (
    build_broker_universe_from_files,
    merge_broker_universe,
)


class BrokerMergeTests(unittest.TestCase):
    def test_merges_snaptrade_holdings_with_source_attribution(self):
        snapshot = {
            "captured_at": "2026-06-25T12:00:00+00:00",
            "account_count": 2,
            "position_count": 3,
            "accounts": [
                {
                    "account": {
                        "institution_name": "Robinhood",
                        "name": "Individual",
                        "number": "***1111",
                    },
                    "positions": [
                        {
                            "symbol": "hood",
                            "description": "Robinhood Markets",
                            "instrument_kind": "stock",
                            "units": 10,
                            "price": 100,
                            "market_value": 1000,
                            "average_purchase_price": 20,
                        }
                    ],
                },
                {
                    "account": {
                        "institution_name": "Fidelity",
                        "name": "401k",
                        "number": "***2222",
                    },
                    "positions": [
                        {
                            "symbol": "HOOD",
                            "instrument_kind": "stock",
                            "units": 5,
                            "price": 110,
                            "market_value": 550,
                            "average_purchase_price": 50,
                        },
                        {
                            "symbol": "FXAIX",
                            "instrument_kind": "mutualfund",
                            "units": "2.5",
                            "market_value": "500.50",
                        },
                    ],
                },
            ],
        }

        payload = merge_broker_universe(
            snaptrade_snapshot=snapshot,
            generated_at="2026-06-25T12:01:00+00:00",
        )

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["counts"]["holding_symbols"], 2)
        hood = next(item for item in payload["holdings"] if item["symbol"] == "HOOD")
        self.assertEqual(hood["shares"], 15.0)
        self.assertEqual(hood["market_value"], 1550.0)
        self.assertAlmostEqual(hood["average_cost"], 30.0)
        self.assertEqual(hood["source_count"], 2)
        self.assertEqual(
            {(item["broker"], item["account_number"]) for item in hood["sources"]},
            {("Robinhood", "***1111"), ("Fidelity", "***2222")},
        )
        fxaix = next(item for item in payload["holdings"] if item["symbol"] == "FXAIX")
        self.assertIsNone(fxaix["average_cost"])

    def test_splits_moomoo_watchlist_only_and_overlap_symbols(self):
        snaptrade = {
            "accounts": [
                {
                    "account": {"institution_name": "Robinhood"},
                    "positions": [{"symbol": "HOOD", "units": 1, "market_value": 100}],
                }
            ]
        }
        moomoo = {
            "source": "moomoo-opend",
            "captured_at": "2026-06-25T12:00:00+00:00",
            "group_count": 2,
            "symbol_count": 3,
            "groups": [
                {"group_name": "Robinhood", "symbols": ["HOOD", "AFRM"]},
                {"group_name": "401k", "symbols": ["FXAIX"]},
            ],
            "items": [
                {
                    "group_name": "Robinhood",
                    "symbol": "HOOD",
                    "market": "US",
                    "name": "Robinhood Markets",
                },
                {
                    "group_name": "Robinhood",
                    "symbol": "AFRM",
                    "market": "US",
                    "name": "Affirm Holdings",
                },
                {
                    "group_name": "401k",
                    "symbol": "FXAIX",
                    "market": "US",
                    "name": "Fidelity 500 Index",
                },
            ],
        }

        payload = merge_broker_universe(
            snaptrade_snapshot=snaptrade,
            moomoo_watchlists=moomoo,
            generated_at="2026-06-25T12:01:00+00:00",
        )

        self.assertEqual(payload["counts"]["watchlist_only_symbols"], 2)
        self.assertEqual(
            [item["symbol"] for item in payload["watchlist_only"]],
            ["AFRM", "FXAIX"],
        )
        self.assertEqual(payload["watchlist_overlap"], [{"symbol": "HOOD", "groups": ["Robinhood"], "source": "moomoo-opend"}])

    def test_build_from_missing_files_writes_empty_private_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "brokers" / "merged-universe.json"

            payload = build_broker_universe_from_files(output_path=output)

            self.assertTrue(output.exists())
            self.assertEqual(payload["counts"]["holding_symbols"], 0)
            self.assertEqual(payload["holdings"], [])
            self.assertEqual(json.loads(output.read_text())["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
