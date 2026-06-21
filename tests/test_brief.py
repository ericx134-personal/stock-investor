import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stock_investor.brief import (
    build_brief,
    build_portfolio_learning_review,
    write_brief,
)


def write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")


class BriefTests(unittest.TestCase):
    def test_brief_includes_recent_records_and_feedback_but_not_old_records(self):
        now = datetime(2026, 6, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alerts = root / "alerts.jsonl"
            risk = root / "risk.jsonl"
            filings = root / "filings.jsonl"
            feedback = root / "feedback.jsonl"
            write_jsonl(
                alerts,
                [
                    {
                        "alert_id": "new",
                        "observed_at": "2026-06-11T12:00:00+00:00",
                        "signal_date": "2026-06-11",
                        "symbol": "ABC",
                        "alert": {
                            "action": "TRIM_REVIEW",
                            "score": -0.4,
                            "reasons": ["Position exceeds its configured limit."],
                        },
                    },
                    {
                        "alert_id": "old",
                        "observed_at": "2026-06-01T12:00:00+00:00",
                        "symbol": "OLD",
                        "alert": {"action": "BUY_CANDIDATE", "score": 0.8},
                    },
                ],
            )
            write_jsonl(
                risk,
                [
                    {
                        "key": "sector:Technology",
                        "observed_at": "2026-06-11T10:00:00+00:00",
                        "severity": "HIGH",
                        "message": "Technology exposure was above its limit.",
                    },
                    {
                        "key": "sector:Technology",
                        "observed_at": "2026-06-11T12:00:00+00:00",
                        "severity": "HIGH",
                        "message": "Technology exposure is above its limit.",
                    }
                ],
            )
            write_jsonl(
                filings,
                [
                    {
                        "filed_at": "2026-06-11",
                        "symbol": "ABC",
                        "importance": "HIGH",
                        "event_categories": ["MATERIAL_CYBERSECURITY_INCIDENT"],
                    }
                ],
            )
            write_jsonl(
                feedback,
                [
                    {
                        "feedback_id": "feedback-1",
                        "alert_id": "new",
                        "label": "HELPFUL",
                        "response": "WATCHING",
                        "note": "",
                        "recorded_at": "2026-06-11T13:00:00+00:00",
                    }
                ],
            )
            result = build_brief(1, alerts, risk, filings, feedback, now)

        self.assertIn("ABC: TRIM_REVIEW", result)
        self.assertIn("feedback HELPFUL/WATCHING", result)
        self.assertIn("Position exceeds its configured limit", result)
        self.assertIn("Technology exposure", result)
        self.assertNotIn("Technology exposure was", result)
        self.assertIn("MATERIAL_CYBERSECURITY_INCIDENT", result)
        self.assertNotIn("OLD", result)

    def test_empty_brief_is_explicit_and_writable(self):
        now = datetime(2026, 6, 12, tzinfo=timezone.utc)
        result = build_brief(7, now=now)
        self.assertIn("No new action alerts", result)
        self.assertIn("No new monitored SEC filings", result)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brief.md"
            write_brief(result, path)
            self.assertEqual(path.read_text(), result)

    def test_brief_rejects_invalid_period(self):
        with self.assertRaisesRegex(ValueError, "at least 1"):
            build_brief(0)

    def test_portfolio_learning_review_summarizes_accountability(self):
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)

        result = build_portfolio_learning_review(
            model_health={"overall_status": "DEGRADED"},
            price_health={"symbols": [{"latest_date": "2026-06-30"}]},
            first_observed_forecasts={
                "tracked_count": 3,
                "changed_since_first_count": 2,
                "first_direction_counts": {"BUY": 1, "WAIT": 2},
            },
            forecast_action_segments={
                "episode_segment_counts": {"ACTED_ON_PROXY": 4},
                "segment_definitions": {
                    "ACTED_ON_PROXY": {"label": "Acted-on proxy"}
                },
            },
            direction_forecast_scorecard=[
                {"forecast_episodes": 4, "observations": 1, "pending": 3}
            ],
            forecast_calibration_curves=[{"status": "PENDING"}],
            direction_error_cohorts=[
                {
                    "direction": "SELL",
                    "horizon": "21d",
                    "false_signal_rate": 0.5,
                    "false_signal_count": 2,
                }
            ],
            now=now,
        )

        self.assertIn("Monthly Portfolio Learning Review", result)
        self.assertIn("Model health: DEGRADED", result)
        self.assertIn("Latest price date: 2026-06-30", result)
        self.assertIn("3 tracked, 2 changed", result)
        self.assertIn("Acted-on proxy: 4 forecast episodes", result)
        self.assertIn("do not read them as causal trade evidence", result)
        self.assertIn("SELL 21d: 50.0% false-signal rate", result)


if __name__ == "__main__":
    unittest.main()
