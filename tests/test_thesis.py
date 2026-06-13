import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from stock_investor.fundamentals import FundamentalSnapshot
from stock_investor.thesis import Thesis, assess_thesis, load_theses


def fundamentals(metrics):
    return FundamentalSnapshot("ABC", "1", "2026-01-01", "2025-12-31", 0.5, 0.5, metrics, ())


class ThesisTests(unittest.TestCase):
    def test_metric_floor_breaks_thesis(self):
        thesis = Thesis(
            "ABC",
            "Growth must remain healthy.",
            "ACTIVE",
            "2027-01-01",
            {"revenue_growth_below": 0.05},
        )
        result = assess_thesis(
            thesis, fundamentals({"revenue_growth": 0.01}), date(2026, 6, 1)
        )
        self.assertTrue(result.broken)
        self.assertIn("below the thesis floor", result.reasons[0])

    def test_metric_ceiling_breaks_thesis(self):
        thesis = Thesis(
            "ABC", "Risk ceiling.", "ACTIVE", None, {"equity_ratio_above": 0.8}
        )
        result = assess_thesis(
            thesis, fundamentals({"equity_ratio": 0.9}), date(2026, 6, 1)
        )
        self.assertTrue(result.broken)

    def test_due_review_is_not_automatically_broken(self):
        thesis = Thesis("ABC", "Review periodically.", "ACTIVE", "2026-01-01", {})
        result = assess_thesis(thesis, None, date(2026, 6, 1))
        self.assertTrue(result.review_due)
        self.assertFalse(result.broken)

    def test_closed_thesis_is_broken_for_monitoring(self):
        thesis = Thesis("ABC", "Position should be closed.", "CLOSED", None, {})
        result = assess_thesis(thesis, None, date(2026, 6, 1))
        self.assertTrue(result.broken)

    def test_missing_metric_creates_warning_not_false_break(self):
        thesis = Thesis("ABC", "Cash flow.", "ACTIVE", None, {"free_cash_flow_margin_below": 0.1})
        result = assess_thesis(thesis, fundamentals({}), date(2026, 6, 1))
        self.assertFalse(result.broken)
        self.assertIn("unavailable", result.warnings[0])

    def test_load_theses_validates_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "theses.json"
            path.write_text(json.dumps({"ABC": {"summary": "x", "status": "INVALID"}}))
            with self.assertRaisesRegex(ValueError, "invalid thesis status"):
                load_theses(path)

    def test_unsupported_rule_is_rejected(self):
        thesis = Thesis("ABC", "x", "ACTIVE", None, {"revenue_growth_equals": 0.1})
        with self.assertRaisesRegex(ValueError, "unsupported"):
            assess_thesis(thesis, fundamentals({}), date(2026, 6, 1))


if __name__ == "__main__":
    unittest.main()
