import json
import tempfile
import unittest
from pathlib import Path

from stock_investor.data import Price
from stock_investor.kline import (
    append_kline_history,
    build_kline_scorecard,
    classify_kline,
    evaluate_kline_history,
)
from stock_investor.monitor import MonitorResult
from stock_investor.indicators import TechnicalSignals
from stock_investor.scoring import Alert


def technicals(**overrides):
    values = {
        "latest_close": 100,
        "latest_date": "2026-01-01",
        "trend": 0,
        "momentum": 0,
        "drawdown_from_high": 0,
        "sma_200": 100,
        "return_12_to_1": 0,
        "ohlcv_available": True,
        "latest_bar_complete": False,
        "atr_20_percent": 0.03,
        "volume_ratio_20": None,
        "breakout_20": -0.01,
        "close_position_20": 0.9,
        "latest_gap": None,
        "latest_candle_body": None,
    }
    values.update(overrides)
    return TechnicalSignals(**values)


class KlineTests(unittest.TestCase):
    def test_classification_is_explainable_and_not_trade_language(self):
        self.assertEqual(classify_kline(technicals()), "Near 20-day breakout")
        self.assertEqual(
            classify_kline(technicals(breakout_20=-0.3, close_position_20=0.1)),
            "Lower recent range",
        )

    def test_history_is_idempotent(self):
        result = MonitorResult(
            "ABC",
            10,
            90,
            900,
            100,
            1000,
            0.1,
            0,
            None,
            None,
            None,
            technicals(),
            Alert("ABC", "HOLD", 0, ()),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kline.jsonl"
            self.assertEqual(append_kline_history([result], path), 1)
            self.assertEqual(append_kline_history([result], path), 0)
            record = json.loads(path.read_text())
        self.assertEqual(record["feature_version"], "kline-v1")
        self.assertEqual(record["regime"], "Near 20-day breakout")

    def test_forward_outcomes_do_not_assume_regime_direction(self):
        record = {
            "feature_version": "kline-v1",
            "symbol": "ABC",
            "signal_date": "2026-01-01",
            "entry_close": 100,
            "regime": "Lower recent range",
        }
        prices = {
            "ABC": [
                Price(
                    __import__("datetime").date(2026, 1, 2)
                    + __import__("datetime").timedelta(days=offset),
                    100 + offset + 1,
                )
                for offset in range(126)
            ]
        }
        outcomes = evaluate_kline_history([record], prices)
        rows = build_kline_scorecard(outcomes)
        self.assertGreater(outcomes[0]["returns"]["21d"], 0)
        self.assertEqual(rows[0]["feature_version"], "kline-v1")
        self.assertTrue(all(row["positive_rate"] == 1 for row in rows))


if __name__ == "__main__":
    unittest.main()
