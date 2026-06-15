import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stock_investor.data import Price
from stock_investor.evaluation import (
    build_directional_forecast_scorecard,
    build_forecast_calibration_scorecard,
    build_scorecard,
    evaluate_alerts,
    evaluate_decisions,
    evaluate_directional_forecasts,
    write_outcomes,
    write_scorecard,
)
from stock_investor.feedback import AlertFeedback


def prices(symbol, daily_change, count=160):
    result = []
    value = 100.0
    for offset in range(count):
        value *= 1 + daily_change
        result.append(Price(date(2025, 1, 1) + timedelta(days=offset), value))
    return symbol, result


def alert(action, symbol="ABC", signal_date="2025-01-10", entry_close=100):
    return {
        "alert_id": f"{symbol}-{action}",
        "model_version": "test-v1",
        "symbol": symbol,
        "signal_date": signal_date,
        "entry_close": entry_close,
        "alert": {"action": action},
    }


def decision(action, symbol="ABC", signal_date="2025-01-10", entry_close=100):
    record = alert(action, symbol, signal_date, entry_close)
    record["decision_id"] = record.pop("alert_id")
    return record


def forecast(direction, symbol="ABC", signal_date="2025-01-10", entry_close=100):
    return {
        "forecast_id": f"{symbol}-{direction}-{signal_date}",
        "forecast_version": "wave-direction-v1",
        "symbol": symbol,
        "signal_date": signal_date,
        "entry_close": entry_close,
        "direction": direction,
        "probability": 0.8 if direction != "WAIT" else None,
    }


class EvaluationTests(unittest.TestCase):
    def test_buy_outcome_uses_only_later_prices_and_benchmark(self):
        stock_symbol, stock = prices("ABC", 0.01)
        benchmark_symbol, benchmark = prices("SPY", 0.005)
        entry = next(item.close for item in stock if item.date.isoformat() == "2025-01-10")
        outcomes = evaluate_alerts(
            [alert("BUY_CANDIDATE", entry_close=entry)],
            {stock_symbol: stock, benchmark_symbol: benchmark},
            "SPY",
        )
        outcome = outcomes[0]
        self.assertAlmostEqual(outcome.returns["21d"], 1.01**21 - 1)
        self.assertGreater(outcome.excess_returns["21d"], 0)
        self.assertGreater(outcome.directional_returns["21d"], 0)

    def test_trim_directional_return_rewards_subsequent_decline(self):
        symbol, history = prices("ABC", -0.005)
        entry = next(item.close for item in history if item.date.isoformat() == "2025-01-10")
        outcome = evaluate_alerts(
            [alert("TRIM_REVIEW", entry_close=entry)], {symbol: history}
        )[0]
        self.assertLess(outcome.returns["21d"], 0)
        self.assertGreater(outcome.directional_returns["21d"], 0)

    def test_pending_outcome_is_retained(self):
        symbol, history = prices("ABC", 0.001, count=20)
        entry = history[9].close
        outcome = evaluate_alerts(
            [alert("BUY_CANDIDATE", entry_close=entry)], {symbol: history}
        )[0]
        self.assertEqual(outcome.status, "PENDING")
        self.assertIsNone(outcome.returns["21d"])

    def test_non_investment_and_missing_close_alerts_are_skipped(self):
        symbol, history = prices("ABC", 0.001)
        records = [
            alert("DATA_REVIEW"),
            alert("BUY_CANDIDATE", entry_close=None),
        ]
        self.assertEqual(evaluate_alerts(records, {symbol: history}), [])

    def test_decision_evaluation_includes_hold_but_not_data_review(self):
        symbol, history = prices("ABC", 0.001)
        outcomes = evaluate_decisions(
            [
                decision("HOLD", entry_close=history[9].close),
                decision("DATA_REVIEW", entry_close=history[9].close),
            ],
            {symbol: history},
        )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].action, "HOLD")
        self.assertGreater(outcomes[0].directional_returns["21d"], 0)

    def test_review_decision_records_return_without_inventing_direction(self):
        symbol, history = prices("ABC", -0.001)
        outcome = evaluate_decisions(
            [decision("REVIEW", entry_close=history[9].close)],
            {symbol: history},
        )[0]
        self.assertLess(outcome.returns["21d"], 0)
        self.assertIsNone(outcome.directional_returns["21d"])

    def test_scorecard_separates_versions_actions_and_horizons(self):
        symbol, history = prices("ABC", 0.001)
        entry = next(item.close for item in history if item.date.isoformat() == "2025-01-10")
        outcomes = evaluate_alerts(
            [alert("BUY_CANDIDATE", entry_close=entry)], {symbol: history}
        )
        rows = build_scorecard(outcomes)
        row = next(item for item in rows if item.horizon == "21d")
        self.assertEqual(row.observations, 1)
        self.assertEqual(row.directional_success_rate, 1.0)

    def test_feedback_is_joined_to_outcome_and_scorecard(self):
        symbol, history = prices("ABC", 0.001)
        feedback = AlertFeedback(
            "feedback-1",
            "ABC-BUY_CANDIDATE",
            "HELPFUL",
            "ACTED",
            "Opened a starter position",
            "2026-01-01T00:00:00+00:00",
        )
        outcomes = evaluate_alerts(
            [alert("BUY_CANDIDATE", entry_close=history[9].close)],
            {symbol: history},
            feedback={feedback.alert_id: feedback},
        )
        row = next(item for item in build_scorecard(outcomes) if item.horizon == "21d")
        self.assertEqual(outcomes[0].feedback_note, "Opened a starter position")
        self.assertEqual(row.feedback_observations, 1)
        self.assertEqual(row.helpful_rate, 1.0)
        self.assertEqual(row.acted_rate, 1.0)

    def test_overlapping_daily_alerts_are_one_episode(self):
        symbol, history = prices("ABC", 0.001)
        first_entry = history[9].close
        second_entry = history[10].close
        records = [
            alert("BUY_CANDIDATE", signal_date="2025-01-10", entry_close=first_entry),
            alert("BUY_CANDIDATE", signal_date="2025-01-11", entry_close=second_entry),
        ]
        outcomes = evaluate_alerts(records, {symbol: history})
        self.assertEqual(len(outcomes), 1)

    def test_episode_separation_can_be_disabled_for_diagnostics(self):
        symbol, history = prices("ABC", 0.001)
        records = [
            alert("BUY_CANDIDATE", signal_date="2025-01-10", entry_close=history[9].close),
            alert("BUY_CANDIDATE", signal_date="2025-01-11", entry_close=history[10].close),
        ]
        outcomes = evaluate_alerts(records, {symbol: history}, minimum_episode_sessions=0)
        self.assertEqual(len(outcomes), 2)

    def test_outcomes_file_is_replaced_with_current_evaluation(self):
        symbol, history = prices("ABC", 0.001)
        entry = next(item.close for item in history if item.date.isoformat() == "2025-01-10")
        outcomes = evaluate_alerts(
            [alert("BUY_CANDIDATE", entry_close=entry)], {symbol: history}
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outcomes.json"
            write_outcomes(outcomes, path)
            payload = json.loads(path.read_text())
        self.assertEqual(payload[0]["alert_id"], "ABC-BUY_CANDIDATE")

    def test_scorecard_file_is_machine_readable(self):
        symbol, history = prices("ABC", 0.001)
        outcomes = evaluate_alerts(
            [alert("BUY_CANDIDATE", entry_close=history[9].close)],
            {symbol: history},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scorecard.json"
            write_scorecard(build_scorecard(outcomes), path)
            payload = json.loads(path.read_text())
        self.assertEqual(payload[0]["model_version"], "test-v1")

    def test_directional_forecasts_score_buy_sell_and_wait_honestly(self):
        up_symbol, up = prices("UP", 0.01)
        down_symbol, down = prices("DOWN", -0.01)
        wait_symbol, wait = prices("WAIT", 0.001)
        outcomes = evaluate_directional_forecasts(
            [
                forecast("BUY", up_symbol, entry_close=up[9].close),
                forecast("SELL", down_symbol, entry_close=down[9].close),
                forecast("WAIT", wait_symbol, entry_close=wait[9].close),
            ],
            {up_symbol: up, down_symbol: down, wait_symbol: wait},
        )
        by_direction = {item["direction"]: item for item in outcomes}
        self.assertGreater(by_direction["BUY"]["directional_returns"]["21d"], 0)
        self.assertGreater(by_direction["SELL"]["directional_returns"]["21d"], 0)
        self.assertIsNone(by_direction["WAIT"]["directional_returns"]["21d"])
        rows = build_directional_forecast_scorecard(outcomes)
        buy = next(
            row
            for row in rows
            if row["direction"] == "BUY" and row["horizon"] == "21d"
        )
        self.assertEqual(buy["directional_success_rate"], 1.0)
        self.assertAlmostEqual(buy["brier_score"], 0.04)

    def test_overlapping_directional_forecasts_are_one_episode(self):
        symbol, history = prices("ABC", 0.001)
        outcomes = evaluate_directional_forecasts(
            [
                forecast("BUY", signal_date="2025-01-10", entry_close=history[9].close),
                forecast("BUY", signal_date="2025-01-11", entry_close=history[10].close),
            ],
            {symbol: history},
        )
        self.assertEqual(len(outcomes), 1)

    def test_pending_forecast_scorecard_retains_displayed_probability(self):
        symbol, history = prices("ABC", 0.001, count=20)
        outcomes = evaluate_directional_forecasts(
            [forecast("BUY", entry_close=history[9].close)], {symbol: history}
        )
        row = next(
            item
            for item in build_directional_forecast_scorecard(outcomes)
            if item["horizon"] == "21d"
        )
        self.assertEqual(row["observations"], 0)
        self.assertEqual(row["pending"], 1)
        self.assertEqual(row["mean_probability"], 0.8)

    def test_calibration_scorecard_uses_fixed_buckets_and_pending_gate(self):
        symbol, history = prices("ABC", 0.001)
        outcomes = evaluate_directional_forecasts(
            [forecast("BUY", entry_close=history[9].close)], {symbol: history}
        )
        rows = build_forecast_calibration_scorecard(outcomes)
        row = next(item for item in rows if item["horizon"] == "21d")
        self.assertEqual(row["probability_bucket"], "80-89%")
        self.assertEqual(row["observations"], 1)
        self.assertEqual(row["status"], "PENDING")

    def test_calibration_scorecard_passes_only_with_broad_mature_sample(self):
        outcomes = []
        for offset in range(20):
            item = forecast("BUY", symbol=f"S{offset % 5}")
            item["returns"] = {"21d": 0.1}
            item["directional_returns"] = {"21d": 0.1}
            item["probability"] = 0.95
            outcomes.append(item)
        row = build_forecast_calibration_scorecard(outcomes)[0]
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["symbols"], 5)


if __name__ == "__main__":
    unittest.main()
