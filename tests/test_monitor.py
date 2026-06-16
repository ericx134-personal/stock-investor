import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stock_investor.data import Position, Price
from stock_investor.fundamentals import FundamentalSnapshot
from stock_investor.monitor import (
    run_monitor,
    write_alert_history,
    write_decision_history,
    write_monitor_snapshot,
)
from stock_investor.thesis import Thesis


def price_history(start, daily_change, count=300):
    result = []
    value = start
    for offset in range(count):
        variation = (0.001, -0.0005, 0.0003, -0.0002)[offset % 4]
        value *= 1 + daily_change + variation
        result.append(Price(date(2025, 1, 1) + timedelta(days=offset), value))
    return result


def position(symbol, shares=1, max_weight=1.0, sector="Test"):
    return Position(
        symbol, shares, 100, max_weight, 0.8, 0.5, 0.5, sector=sector
    )


class MonitorTests(unittest.TestCase):
    def test_monitor_calculates_portfolio_weights(self):
        results = run_monitor(
            [position("BIG", shares=3), position("SMALL", shares=1)],
            {
                "BIG": price_history(100, 0),
                "SMALL": price_history(100, 0),
            },
        )
        self.assertAlmostEqual(results[0].portfolio_weight, 0.75)
        self.assertAlmostEqual(results[1].portfolio_weight, 0.25)

    def test_monitor_includes_cash_in_portfolio_weights(self):
        result = run_monitor(
            [position("ABC", shares=1)],
            {"ABC": price_history(100, 0)},
            cash_balance=100,
        )[0]
        self.assertAlmostEqual(
            result.portfolio_weight, result.latest_close / (result.latest_close + 100)
        )

    def test_monitor_supports_margin_cash(self):
        positions = [position("ABC", 10)]
        prices = {"ABC": price_history(100, 0)}
        result = run_monitor(positions, prices, cash_balance=-250)[0]
        self.assertGreater(result.portfolio_weight, 1.0)

    def test_monitor_rejects_negative_net_value(self):
        with self.assertRaisesRegex(ValueError, "net value cannot be negative"):
            run_monitor([], {}, cash_balance=-1)

    def test_monitor_calculates_unrealized_return(self):
        result = run_monitor(
            [position("ABC", shares=1)],
            {"ABC": price_history(100, 0)},
        )[0]
        self.assertAlmostEqual(result.unrealized_return, result.latest_close / 100 - 1)

    def test_missing_history_creates_data_review(self):
        result = run_monitor([position("MISSING")], {})[0]
        self.assertEqual(result.alert.action, "DATA_REVIEW")

    def test_stale_history_creates_data_review(self):
        stale = price_history(100, 0.001)
        current = price_history(100, 0.001, count=310)
        result = run_monitor(
            [position("STALE"), position("CURRENT")],
            {"STALE": stale, "CURRENT": current},
        )[0]
        self.assertEqual(result.alert.action, "DATA_REVIEW")
        self.assertIn("behind", result.alert.reasons[0])

    def test_sec_fundamentals_fill_blank_manual_scores(self):
        blank = Position(
            "ABC", 0, 0, 0.2, None, None, 0.5, False, "1234", "Test"
        )
        fundamentals = {
            "ABC": FundamentalSnapshot(
                "ABC",
                "0000001234",
                "2025-02-01",
                "2024-12-31",
                0.9,
                0.8,
                {},
                (),
            )
        }
        result = run_monitor(
            [blank],
            {"ABC": price_history(100, 0.002)},
            fundamentals=fundamentals,
        )[0]
        self.assertEqual(result.alert.action, "BUY_CANDIDATE")

    def test_missing_fundamentals_block_buy_alert(self):
        blank = Position("ABC", 0, 0, 0.2, None, None, None, sector="Test")
        result = run_monitor([blank], {"ABC": price_history(100, 0.002)})[0]
        self.assertEqual(result.alert.action, "DATA_REVIEW")

    def test_v3_treats_missing_revisions_as_neutral_when_other_fundamentals_exist(self):
        blank = Position("ABC", 0, 0, 0.2, 0.9, 0.8, None, sector="Test")
        v1 = run_monitor([blank], {"ABC": price_history(100, 0.002)})[0]
        v3 = run_monitor(
            [blank],
            {"ABC": price_history(100, 0.002)},
            model_version="decision-support-v3",
        )[0]
        self.assertEqual(v1.alert.action, "DATA_REVIEW")
        self.assertEqual(v3.alert.action, "BUY_CANDIDATE")
        self.assertIn("treated as neutral", v3.alert.reasons[-1])

    def test_stale_sec_fundamentals_block_buy_alert(self):
        blank = Position("ABC", 0, 0, 0.2, None, None, 0.5, sector="Test")
        fundamentals = {
            "ABC": FundamentalSnapshot(
                "ABC", "1", "2023-01-01", "2022-12-31", 0.9, 0.8, {}, ()
            )
        }
        result = run_monitor(
            [blank], {"ABC": price_history(100, 0.002)}, fundamentals=fundamentals
        )[0]
        self.assertEqual(result.alert.action, "DATA_REVIEW")

    def test_manual_overrides_are_not_blocked_by_stale_unused_sec_data(self):
        manual = position("ABC", shares=0, max_weight=0.2)
        fundamentals = {
            "ABC": FundamentalSnapshot(
                "ABC", "1", "2023-01-01", "2022-12-31", 0.1, 0.1, {}, ()
            )
        }
        result = run_monitor(
            [manual], {"ABC": price_history(100, 0.002)}, fundamentals=fundamentals
        )[0]
        self.assertEqual(result.alert.action, "BUY_CANDIDATE")

    def test_history_records_actionable_alerts_but_not_holds(self):
        results = run_monitor(
            [
                position("BUY", shares=0, sector="Buy"),
                position("HOLD", sector="Hold"),
            ],
            {
                "BUY": price_history(100, 0.002),
                "HOLD": price_history(100, 0),
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alerts.jsonl"
            write_alert_history(results, path)
            write_alert_history(results, path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([record["symbol"] for record in records], ["BUY"])
        self.assertIn("observed_at", records[0])
        self.assertIn("alert_id", records[0])
        self.assertIn("model_version", records[0])
        self.assertEqual(
            records[0]["signal_date"], records[0]["technicals"]["latest_date"]
        )
        self.assertEqual(records[0]["entry_close"], records[0]["latest_close"])

    def test_snapshot_records_holds_and_model_version(self):
        results = run_monitor(
            [position("HOLD")],
            {"HOLD": price_history(100, 0)},
            model_version="decision-support-v2",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            write_monitor_snapshot(results, path, "decision-support-v2")
            payload = json.loads(path.read_text())
        self.assertEqual(payload["model_version"], "decision-support-v2")
        self.assertEqual(payload["results"][0]["alert"]["action"], "HOLD")
        self.assertEqual(payload["results"][0]["shares"], 1)
        self.assertEqual(payload["results"][0]["average_cost"], 100)
        self.assertEqual(payload["results"][0]["cost_basis"], 100)

    def test_decision_history_records_holds_idempotently(self):
        results = run_monitor(
            [position("HOLD")],
            {"HOLD": price_history(100, 0)},
            model_version="decision-support-v2",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.jsonl"
            self.assertEqual(write_decision_history(results, path, "decision-support-v2"), 1)
            self.assertEqual(write_decision_history(results, path, "decision-support-v2"), 0)
            payload = json.loads(path.read_text().strip())
        self.assertEqual(payload["alert"]["action"], "HOLD")
        self.assertIn("decision_id", payload)

    def test_unknown_sector_blocks_buy_candidate(self):
        unknown = Position("ABC", 0, 0, 0.2, 0.8, 0.5, 0.5)
        result = run_monitor([unknown], {"ABC": price_history(100, 0.002)})[0]
        self.assertEqual(result.alert.action, "DATA_REVIEW")
        self.assertIn("Sector is unknown", result.alert.reasons[0])

    def test_broken_measurable_thesis_creates_trim_review(self):
        held = position("ABC")
        fundamental = FundamentalSnapshot(
            "ABC",
            "1",
            "2026-01-01",
            "2025-12-31",
            0.5,
            0.5,
            {"revenue_growth": -0.2},
            (),
        )
        thesis = Thesis(
            "ABC",
            "Revenue must hold.",
            "ACTIVE",
            None,
            {"revenue_growth_below": -0.1},
        )
        result = run_monitor(
            [held],
            {"ABC": price_history(100, 0.001)},
            fundamentals={"ABC": fundamental},
            theses={"ABC": thesis},
        )[0]
        self.assertEqual(result.alert.action, "TRIM_REVIEW")
        self.assertTrue(
            any("revenue_growth" in reason for reason in result.alert.reasons)
        )

    def test_configured_thesis_file_requires_thesis_for_held_position(self):
        result = run_monitor(
            [position("ABC")],
            {"ABC": price_history(100, 0.001)},
            theses={},
        )[0]
        self.assertEqual(result.alert.action, "REVIEW")
        self.assertIn("no recorded investment thesis", result.alert.reasons[-1])


if __name__ == "__main__":
    unittest.main()
