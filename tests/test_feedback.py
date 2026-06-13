import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_investor.cli import _list_alerts
from stock_investor.feedback import append_feedback, load_latest_feedback


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.alerts = Path(self.directory.name) / "alerts.jsonl"
        self.feedback = Path(self.directory.name) / "feedback.jsonl"
        self.alerts.write_text(json.dumps({"alert_id": "alert-1"}) + "\n")

    def tearDown(self):
        self.directory.cleanup()

    def test_feedback_is_append_only_and_latest_record_wins(self):
        with patch(
            "stock_investor.feedback.datetime"
        ) as clock:
            clock.now.return_value.isoformat.side_effect = [
                "2026-01-01T00:00:00+00:00",
                "2026-01-02T00:00:00+00:00",
            ]
            append_feedback(
                self.alerts,
                self.feedback,
                "alert-1",
                "UNSURE",
                "WATCHING",
                "Needs research",
            )
            append_feedback(
                self.alerts,
                self.feedback,
                "alert-1",
                "HELPFUL",
                "ACTED",
                "Position reduced",
            )

        records = self.feedback.read_text().splitlines()
        latest = load_latest_feedback(self.feedback)["alert-1"]
        self.assertEqual(len(records), 2)
        self.assertEqual(latest.label, "HELPFUL")
        self.assertEqual(latest.response, "ACTED")
        self.assertEqual(latest.note, "Position reduced")

    def test_feedback_rejects_unknown_alert(self):
        with self.assertRaisesRegex(ValueError, "unknown alert_id"):
            append_feedback(
                self.alerts, self.feedback, "missing", "HELPFUL"
            )

    def test_feedback_rejects_unknown_label_or_response(self):
        with self.assertRaisesRegex(ValueError, "label must be"):
            append_feedback(self.alerts, self.feedback, "alert-1", "GOOD")
        with self.assertRaisesRegex(ValueError, "response must be"):
            append_feedback(
                self.alerts, self.feedback, "alert-1", "HELPFUL", "BOUGHT"
            )

    def test_missing_feedback_file_loads_as_empty(self):
        self.assertEqual(load_latest_feedback(self.feedback), {})

    def test_list_alerts_shows_id_action_and_latest_feedback(self):
        self.alerts.write_text(
            json.dumps(
                {
                    "alert_id": "alert-1",
                    "signal_date": "2026-01-01",
                    "symbol": "ABC",
                    "alert": {"action": "BUY_CANDIDATE", "score": 0.72},
                }
            )
            + "\n"
        )
        append_feedback(
            self.alerts, self.feedback, "alert-1", "HELPFUL", "WATCHING"
        )
        with patch("builtins.print") as output:
            _list_alerts(str(self.alerts), str(self.feedback), 20)
        self.assertIn("alert-1", output.call_args.args[0])
        self.assertIn("BUY_CANDIDATE", output.call_args.args[0])
        self.assertIn("HELPFUL/WATCHING", output.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
