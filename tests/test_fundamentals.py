import tempfile
import unittest
from pathlib import Path

from stock_investor.fundamentals import (
    calculate_fundamentals,
    load_fundamentals,
    write_fundamentals,
)


def fact(val, end, filed, unit="USD"):
    return {
        "val": val,
        "end": end,
        "filed": filed,
        "form": "10-K",
        "fp": "FY",
        "unit": unit,
    }


def concept(label, unit, values):
    return {label: {"units": {unit: values}}}


def complete_payload():
    gaap = {}
    gaap.update(
        concept(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "USD",
            [
                fact(1_000, "2024-12-31", "2025-02-15"),
                fact(1_200, "2025-12-31", "2026-02-15"),
            ],
        )
    )
    gaap.update(concept("NetIncomeLoss", "USD", [fact(180, "2025-12-31", "2026-02-15")]))
    gaap.update(
        concept(
            "NetCashProvidedByUsedInOperatingActivities",
            "USD",
            [fact(240, "2025-12-31", "2026-02-15")],
        )
    )
    gaap.update(
        concept(
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "USD",
            [fact(60, "2025-12-31", "2026-02-15")],
        )
    )
    gaap.update(concept("Assets", "USD", [fact(1_500, "2025-12-31", "2026-02-15")]))
    gaap.update(
        concept("Liabilities", "USD", [fact(600, "2025-12-31", "2026-02-15")])
    )
    gaap.update(
        concept(
            "CommonStockSharesOutstanding",
            "shares",
            [fact(100, "2025-12-31", "2026-02-15", "shares")],
        )
    )
    return {"facts": {"us-gaap": gaap}}


def ifrs_payload():
    def ifrs_fact(val, end, filed, unit="CNY"):
        item = fact(val, end, filed, unit)
        item["form"] = "20-F"
        return item

    ifrs = {}
    for label, values in {
        "Revenue": [
            ifrs_fact(1_000, "2024-12-31", "2025-04-01"),
            ifrs_fact(1_200, "2025-12-31", "2026-04-01"),
        ],
        "ProfitLoss": [ifrs_fact(180, "2025-12-31", "2026-04-01")],
        "CashFlowsFromUsedInOperatingActivities": [
            ifrs_fact(240, "2025-12-31", "2026-04-01")
        ],
        "PurchaseOfPropertyPlantAndEquipment": [
            ifrs_fact(-60, "2025-12-31", "2026-04-01")
        ],
        "Assets": [ifrs_fact(1_500, "2025-12-31", "2026-04-01")],
        "Liabilities": [ifrs_fact(600, "2025-12-31", "2026-04-01")],
    }.items():
        ifrs.update(concept(label, "CNY", values))
    ifrs.update(
        concept(
            "NumberOfSharesOutstanding",
            "shares",
            [ifrs_fact(100, "2025-12-31", "2026-04-01", "shares")],
        )
    )
    return {"facts": {"ifrs-full": ifrs}}


class FundamentalTests(unittest.TestCase):
    def test_complete_facts_produce_scores_and_provenance(self):
        result = calculate_fundamentals("ABC", "1234", complete_payload(), 20)
        self.assertTrue(result.complete)
        self.assertGreater(result.quality, 0)
        self.assertGreater(result.valuation, 0)
        self.assertEqual(result.filed_at, "2026-02-15")
        self.assertEqual(result.cik, "0000001234")

    def test_incomplete_facts_refuse_to_invent_scores(self):
        result = calculate_fundamentals("ABC", "1234", {"facts": {}}, 20)
        self.assertIsNone(result.quality)
        self.assertIsNone(result.valuation)
        self.assertIn("Insufficient", result.warnings[0])

    def test_mismatched_period_facts_are_not_mixed(self):
        payload = complete_payload()
        payload["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"][0]["end"] = (
            "2024-12-31"
        )
        result = calculate_fundamentals("ABC", "1234", payload, 20)
        self.assertIsNone(result.metrics["net_margin"])

    def test_market_price_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            calculate_fundamentals("ABC", "1234", complete_payload(), 0)

    def test_ifrs_20f_supports_quality_but_refuses_unsafe_adr_valuation(self):
        result = calculate_fundamentals("ADR", "1234", ifrs_payload(), 20)
        self.assertGreater(result.quality, 0)
        self.assertIsNone(result.valuation)
        self.assertEqual(result.taxonomy, "ifrs-full")
        self.assertEqual(result.reporting_currency, "CNY")
        self.assertEqual(result.annual_form, "20-F")
        self.assertIn("ADR-ratio", " ".join(result.warnings))

    def test_fundamental_file_round_trip(self):
        snapshot = calculate_fundamentals("ABC", "1234", complete_payload(), 20)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fundamentals.json"
            write_fundamentals({"ABC": snapshot}, path)
            loaded = load_fundamentals(path)
        self.assertEqual(loaded["ABC"], snapshot)


if __name__ == "__main__":
    unittest.main()
