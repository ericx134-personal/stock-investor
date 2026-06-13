import unittest

from stock_investor.scoring import SignalSnapshot, evaluate
from stock_investor.model import get_model_policy


def snapshot(**overrides):
    values = {
        "symbol": "TEST",
        "portfolio_weight": 0.05,
        "max_portfolio_weight": 0.10,
        "drawdown_from_high": -0.05,
        "trend": 0.0,
        "momentum": 0.0,
        "quality": 0.0,
        "valuation": 0.0,
        "revisions": 0.0,
        "thesis_broken": False,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


class EvaluateTests(unittest.TestCase):
    def test_aligned_signals_create_buy_candidate(self):
        alert = evaluate(
            snapshot(
                trend=0.8,
                momentum=0.7,
                quality=0.9,
                valuation=0.5,
                revisions=0.6,
            )
        )
        self.assertEqual(alert.action, "BUY_CANDIDATE")

    def test_concentration_creates_trim_review(self):
        alert = evaluate(snapshot(portfolio_weight=0.20))
        self.assertEqual(alert.action, "TRIM_REVIEW")
        self.assertIn("exceeds", alert.reasons[0])

    def test_held_position_uses_add_candidate(self):
        alert = evaluate(
            snapshot(
                is_held=True,
                portfolio_weight=0.05,
                max_portfolio_weight=0.20,
                trend=0.8,
                momentum=0.7,
                quality=0.9,
                valuation=0.5,
                revisions=0.6,
            )
        )
        self.assertEqual(alert.action, "ADD_CANDIDATE")

    def test_near_limit_position_does_not_create_add_candidate(self):
        alert = evaluate(
            snapshot(
                is_held=True,
                portfolio_weight=0.17,
                max_portfolio_weight=0.20,
                trend=0.8,
                momentum=0.7,
                quality=0.9,
                valuation=0.5,
                revisions=0.6,
            )
        )
        self.assertEqual(alert.action, "HOLD")

    def test_incomplete_fundamentals_block_buy_candidate(self):
        alert = evaluate(
            snapshot(
                fundamentals_complete=False,
                trend=0.8,
                momentum=0.7,
                quality=0.9,
                valuation=0.5,
                revisions=0.6,
            )
        )
        self.assertEqual(alert.action, "DATA_REVIEW")

    def test_broken_thesis_takes_priority(self):
        alert = evaluate(
            snapshot(thesis_broken=True, is_held=True, trend=1.0, quality=1.0)
        )
        self.assertEqual(alert.action, "TRIM_REVIEW")

    def test_broken_watchlist_thesis_does_not_suggest_trim(self):
        alert = evaluate(snapshot(thesis_broken=True, is_held=False))
        self.assertEqual(alert.action, "REVIEW")

    def test_drawdown_triggers_review_not_blind_sell(self):
        alert = evaluate(snapshot(drawdown_from_high=-0.25, quality=0.8))
        self.assertEqual(alert.action, "REVIEW")

    def test_invalid_normalized_signal_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(snapshot(momentum=1.1))

    def test_v2_requires_confirmed_deterioration_for_review(self):
        policy = get_model_policy("decision-support-v2")
        alert = evaluate(
            snapshot(drawdown_from_high=-0.35, trend=0.1, revisions=0.1),
            policy,
        )
        self.assertEqual(alert.action, "HOLD")
        self.assertIn("not yet confirmed", alert.reasons[0])

    def test_v2_reviews_confirmed_or_severe_deterioration(self):
        policy = get_model_policy("decision-support-v2")
        confirmed = evaluate(
            snapshot(drawdown_from_high=-0.35, trend=-0.6), policy
        )
        severe = evaluate(snapshot(drawdown_from_high=-0.55), policy)
        self.assertEqual(confirmed.action, "REVIEW")
        self.assertEqual(severe.action, "REVIEW")

    def test_v2_preserves_concentration_trim_review(self):
        alert = evaluate(
            snapshot(portfolio_weight=0.20),
            get_model_policy("decision-support-v2"),
        )
        self.assertEqual(alert.action, "TRIM_REVIEW")


if __name__ == "__main__":
    unittest.main()
