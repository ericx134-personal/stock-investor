import unittest

from stock_investor.research import build_multiple_testing_ledger


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


if __name__ == "__main__":
    unittest.main()
