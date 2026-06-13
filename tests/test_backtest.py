import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stock_investor.backtest import (
    backtest_trend_momentum,
    backtest_trend_momentum_oos,
    write_oos_report,
)
from stock_investor.data import Price


def history(daily_change, count=500):
    prices = []
    value = 100.0
    for offset in range(count):
        value *= 1 + daily_change
        prices.append(Price(date(2024, 1, 1) + timedelta(days=offset), value))
    return prices


class BacktestTests(unittest.TestCase):
    def test_uptrend_enters_and_earns_positive_return(self):
        result = backtest_trend_momentum("UP", history(0.001))
        self.assertGreater(result.strategy_return, 0)
        self.assertGreater(result.exposure, 0.9)
        self.assertEqual(result.trades, 1)

    def test_downtrend_stays_in_cash(self):
        result = backtest_trend_momentum("DOWN", history(-0.001))
        self.assertEqual(result.strategy_return, 0)
        self.assertEqual(result.exposure, 0)
        self.assertLess(result.buy_and_hold_return, 0)

    def test_backtest_requires_out_of_sample_days(self):
        with self.assertRaisesRegex(ValueError, "more than"):
            backtest_trend_momentum("SHORT", history(0.001, count=252))

    def test_backtest_rejects_negative_cost(self):
        with self.assertRaisesRegex(ValueError, "costs"):
            backtest_trend_momentum("UP", history(0.001), transaction_cost_bps=-1)

    def test_oos_excludes_pre_test_returns_and_uses_prior_data(self):
        prices = history(0.01, count=300)
        flat_start = 270
        flat_close = prices[flat_start - 1].close
        prices[flat_start:] = [
            Price(item.date, flat_close) for item in prices[flat_start:]
        ]
        result = backtest_trend_momentum_oos(
            "UP_THEN_FLAT", prices, prices[flat_start].date
        )
        self.assertEqual(result.evaluation_type, "DEDICATED_OUT_OF_SAMPLE")
        self.assertEqual(result.pre_test_sessions, flat_start)
        self.assertEqual(result.test_sessions, 30)
        self.assertEqual(result.buy_and_hold_return, 0)
        self.assertAlmostEqual(result.strategy_return, -0.001)
        self.assertEqual(result.trades, 1)

    def test_oos_requires_sufficient_pre_test_history(self):
        prices = history(0.001, count=500)
        with self.assertRaisesRegex(ValueError, "pre-test"):
            backtest_trend_momentum_oos("UP", prices, prices[100].date)

    def test_oos_report_is_model_versioned_and_cannot_be_overwritten(self):
        prices = history(0.001, count=500)
        start = prices[300].date
        result = backtest_trend_momentum_oos("UP", prices, start)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oos.json"
            write_oos_report([result], path, start, None, 21, 10)
            payload = json.loads(path.read_text())
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                write_oos_report([result], path, start, None, 21, 10)
        self.assertEqual(payload["model_version"], "decision-support-v1")
        self.assertEqual(payload["results"][0]["test_sessions"], 200)


if __name__ == "__main__":
    unittest.main()
