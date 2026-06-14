import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from stock_investor.diagnostics import (
    analyze_fundamental_coverage,
    analyze_alert_burden,
    build_model_health_summary,
    build_price_health_report,
    compare_monitor_files,
    infer_price_source,
    load_monitor_records,
)
from stock_investor.data import Position
from stock_investor.data import Price
from stock_investor.fundamentals import FundamentalSnapshot


def record(symbol, action, reasons):
    return {"symbol": symbol, "alert": {"action": action, "reasons": reasons}}


class DiagnosticTests(unittest.TestCase):
    def test_price_health_reports_each_symbol_and_honest_source_confidence(self):
        report = build_price_health_report(
            {
                "A": [
                    Price(date(2026, 1, 7), 9, 8, 10, 7, 90),
                    Price(date(2026, 1, 9), 15, 14, 25, 14, 100),
                    Price(date(2026, 1, 10), 30, 29, 31, 29, 110),
                ]
            },
            {"A", "B"},
            as_of=date(2026, 1, 10),
            source=infer_price_source("robinhood-prices.csv"),
            expected_sessions={
                date(2026, 1, 7),
                date(2026, 1, 8),
                date(2026, 1, 9),
                date(2026, 1, 10),
            },
            expected_session_source="SPY",
        )
        self.assertEqual(report["status_counts"], {"FRESH": 1, "MISSING": 1})
        self.assertFalse(report["all_held_symbols_fresh"])
        self.assertEqual(report["symbols"][0]["ohlcv_coverage_rate"], 1)
        self.assertEqual(report["source"]["confidence"], "INFERRED")
        self.assertEqual(report["symbols"][0]["missing_session_count"], 1)
        self.assertEqual(report["symbols"][0]["missing_session_dates"], ["2026-01-08"])
        self.assertEqual(report["symbols_with_missing_sessions"], ["A"])
        self.assertEqual(report["symbols_with_suspicious_ohlcv"], ["A"])
        self.assertEqual(report["symbols"][0]["suspicious_intraday_range_count"], 1)
        self.assertEqual(report["symbols_with_suspicious_close_gaps"], ["A"])
        self.assertEqual(
            report["symbols"][0]["suspicious_close_gaps"][-1]["classification"],
            "POSSIBLE_CORPORATE_ACTION",
        )
        self.assertEqual(
            infer_price_source("prices.csv", "licensed-provider")["confidence"],
            "DECLARED",
        )

    def test_model_health_separates_failures_from_pending_evidence(self):
        summary = build_model_health_summary(
            read_only=True,
            price_coverage_rate=1.0,
            prices_fresh=True,
            kline_coverage_rate=0.9,
            wave_coverage_rate=0.9,
            diagnostic={"actionable_rate": 0.6, "data_review_rate": 0.1},
            fundamental_coverage_rate=0.9,
            direction_forecast_scorecard=[],
        )
        self.assertEqual(summary["schema_version"], "model-health-v1")
        self.assertEqual(summary["overall_status"], "DEGRADED")
        self.assertEqual(summary["failed_gates"], ["alert_selectivity"])
        self.assertEqual(
            summary["pending_gates"],
            ["matured_directional_evidence", "two_sided_directional_evidence"],
        )
        self.assertEqual(summary["blocking_failures"], [])

    def test_model_health_blocks_required_price_failure(self):
        summary = build_model_health_summary(
            read_only=True,
            price_coverage_rate=0.9,
            prices_fresh=True,
            kline_coverage_rate=0.9,
            wave_coverage_rate=0.9,
            diagnostic={"actionable_rate": 0.1, "data_review_rate": 0.1},
            fundamental_coverage_rate=0.9,
            direction_forecast_scorecard=[
                {"direction": "BUY", "observations": 20},
                {"direction": "SELL", "observations": 20},
            ],
        )
        self.assertEqual(summary["overall_status"], "BLOCKED")
        self.assertEqual(summary["blocking_failures"], ["price_coverage"])

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
