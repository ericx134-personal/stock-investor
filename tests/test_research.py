import unittest
from pathlib import Path

from stock_investor.research import (
    build_false_discovery_warnings,
    build_multiple_testing_ledger,
    load_evaluation_periods,
    validate_evaluation_periods,
)


class ResearchLedgerTests(unittest.TestCase):
    def test_multiple_testing_ledger_counts_experiment_families(self):
        ledger = build_multiple_testing_ledger(
            {
                "wave_experiment_scorecard": 18,
                "wave_conditional_scorecard": 54,
                "direction_rate_comparison": 1,
            }
        )
        self.assertEqual(ledger["ledger_version"], "multiple-testing-ledger-v1")
        self.assertGreaterEqual(ledger["total_hypothesis_count"], 73)
        structural = [
            row
            for row in ledger["rows"]
            if row["id"] == "wave_conditional_scorecard"
        ][0]
        self.assertEqual(structural["multiple_testing_risk"], "HIGH")
        self.assertEqual(structural["family_multiple_testing_risk"], "HIGH")
        self.assertFalse(structural["promoted_signal_allowed"])
        self.assertEqual(structural["promotion_status"], "LEDGER_ONLY")

    def test_false_discovery_warnings_block_large_families_from_promotion(self):
        ledger = build_multiple_testing_ledger(
            {
                "wave_experiment_scorecard": 18,
                "wave_conditional_scorecard": 54,
                "direction_rate_comparison": 1,
            }
        )
        warnings = build_false_discovery_warnings(ledger)
        by_family = {row["family"]: row for row in warnings}
        self.assertEqual(by_family["structural_wave"]["risk"], "HIGH")
        self.assertEqual(by_family["structural_wave"]["status"], "BLOCK_PROMOTION")
        self.assertNotIn("calibration_audit", by_family)

    def test_fixed_evaluation_periods_keep_sealed_period_in_future(self):
        path = Path(__file__).parents[1] / "models" / "evaluation-periods-v1.json"
        payload = load_evaluation_periods(path)
        self.assertEqual(
            [period["name"] for period in payload["periods"]],
            ["train", "development", "sealed_test"],
        )
        self.assertEqual(payload["periods"][-1]["status"], "sealed_future")
        self.assertGreater(
            payload["periods"][-1]["start"],
            payload["source_price_cutoff_used_for_design"],
        )

    def test_evaluation_period_validation_rejects_seen_sealed_data(self):
        with self.assertRaisesRegex(ValueError, "after inspected source data"):
            validate_evaluation_periods(
                {
                    "schema_version": "evaluation-periods-v1",
                    "source_price_cutoff_used_for_design": "2026-06-16",
                    "periods": [
                        {"name": "train", "start": "2024-01-01", "end": "2025-01-01"},
                        {
                            "name": "development",
                            "start": "2025-01-02",
                            "end": "2026-01-01",
                        },
                        {
                            "name": "sealed_test",
                            "start": "2026-06-01",
                            "end": None,
                            "status": "sealed_future",
                        },
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
