import json
import tempfile
import unittest
from pathlib import Path

from stock_investor.diagnostics import (
    analyze_fundamental_coverage,
    analyze_alert_burden,
    compare_monitor_files,
    load_monitor_records,
)
from stock_investor.data import Position
from stock_investor.fundamentals import FundamentalSnapshot


def record(symbol, action, reasons):
    return {"symbol": symbol, "alert": {"action": action, "reasons": reasons}}


class DiagnosticTests(unittest.TestCase):
    def test_latest_symbol_alerts_measure_fatigue_and_causes(self):
        report = analyze_alert_burden(
            [
                record("A", "REVIEW", ["Drawdown is -30%; review the thesis."]),
                record("A", "TRIM_REVIEW", ["Position weight 20% exceeds the limit."]),
                record("B", "DATA_REVIEW", ["Fundamental coverage is incomplete."]),
                record("C", "HOLD", ["No configured action threshold has been reached."]),
            ]
        )
        self.assertEqual(report["symbols"], 3)
        self.assertEqual(report["action_counts"]["TRIM_REVIEW"], 1)
        self.assertEqual(report["reason_counts"]["position_limit"], 1)
        self.assertAlmostEqual(report["actionable_rate"], 1 / 3)
        self.assertAlmostEqual(report["data_review_rate"], 1 / 3)
        self.assertAlmostEqual(report["hold_rate"], 1 / 3)
        self.assertTrue(report["data_quality_burden"])
        self.assertFalse(report["alert_fatigue_risk"])

    def test_more_than_half_actionable_flags_alert_fatigue(self):
        report = analyze_alert_burden(
            [
                record("A", "REVIEW", []),
                record("B", "TRIM_REVIEW", []),
                record("C", "DATA_REVIEW", []),
            ]
        )
        self.assertTrue(report["alert_fatigue_risk"])

    def test_full_snapshot_counts_holds_in_selectivity_denominator(self):
        payload = {
            "model_version": "test-v2",
            "observed_at": "2026-01-01T00:00:00Z",
            "results": [
                record("A", "REVIEW", []),
                record("B", "HOLD", []),
                record("C", "HOLD", []),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.json"
            candidate = Path(directory) / "candidate.json"
            baseline.write_text(json.dumps(payload))
            candidate_payload = dict(payload)
            candidate_payload["results"] = [record("A", "HOLD", [])] * 3
            candidate.write_text(json.dumps(candidate_payload))
            records = load_monitor_records(baseline)
            comparison = compare_monitor_files(baseline, candidate)
        self.assertEqual(len(records), 3)
        self.assertAlmostEqual(comparison["baseline"]["actionable_rate"], 1 / 3)
        self.assertAlmostEqual(comparison["candidate"]["actionable_rate"], 0)
        self.assertEqual(comparison["action_transitions"]["REVIEW -> HOLD"], 1)

    def test_fundamental_coverage_separates_v1_and_v3_readiness(self):
        positions = [
            Position("A", 1, 1, 0.1, 0.5, 0.5, None),
            Position("B", 1, 1, 0.1, None, None, 0.2),
        ]
        fundamentals = {
            "B": FundamentalSnapshot("B", "1", "", "", 0.5, None, {}, ())
        }
        report = analyze_fundamental_coverage(positions, fundamentals)
        self.assertEqual(report["v1_buy_ready_symbols"], [])
        self.assertEqual(report["v3_buy_ready_symbols"], ["A"])
        self.assertEqual(report["gap_symbols"]["valuation"], ["B"])


if __name__ == "__main__":
    unittest.main()
