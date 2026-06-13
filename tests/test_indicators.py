import unittest
from datetime import date, timedelta

from stock_investor.data import Price
from stock_investor.indicators import calculate_technicals


def history(daily_change, count=300):
    prices = []
    value = 100.0
    for offset in range(count):
        value *= 1 + daily_change
        prices.append(Price(date(2025, 1, 1) + timedelta(days=offset), value))
    return prices


def kline_history(daily_change, count=300):
    prices = []
    value = 100.0
    for offset in range(count):
        previous = value
        value *= 1 + daily_change
        prices.append(
            Price(
                date(2025, 1, 1) + timedelta(days=offset),
                value,
                previous,
                max(previous, value) * 1.01,
                min(previous, value) * 0.99,
                1000 + offset,
            )
        )
    return prices


class IndicatorTests(unittest.TestCase):
    def test_uptrend_produces_positive_trend_and_momentum(self):
        signals = calculate_technicals(history(0.002))
        self.assertGreater(signals.trend, 0)
        self.assertGreater(signals.momentum, 0)
        self.assertAlmostEqual(signals.drawdown_from_high, 0)

    def test_insufficient_history_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least 252"):
            calculate_technicals(history(0.001, count=100))

    def test_momentum_is_clamped(self):
        signals = calculate_technicals(history(0.02))
        self.assertEqual(signals.momentum, 1.0)

    def test_full_kline_history_produces_explainable_features(self):
        signals = calculate_technicals(kline_history(0.002))
        self.assertTrue(signals.ohlcv_available)
        self.assertTrue(signals.latest_bar_complete)
        self.assertGreater(signals.atr_20_percent, 0)
        self.assertGreater(signals.volume_ratio_20, 1)
        self.assertGreater(signals.close_position_20, 0.5)
        self.assertIsNotNone(signals.latest_gap)

    def test_close_only_history_marks_kline_features_unavailable(self):
        signals = calculate_technicals(history(0.002))
        self.assertFalse(signals.ohlcv_available)
        self.assertIsNone(signals.atr_20_percent)

    def test_live_close_can_use_prior_completed_klines(self):
        prices = kline_history(0.002)
        latest = prices[-1]
        prices[-1] = Price(latest.date, latest.close)
        signals = calculate_technicals(prices)
        self.assertTrue(signals.ohlcv_available)
        self.assertFalse(signals.latest_bar_complete)
        self.assertIsNotNone(signals.breakout_20)
        self.assertIsNone(signals.latest_gap)
