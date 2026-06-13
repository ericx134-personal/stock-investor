import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stock_investor.data import Position, Price
from stock_investor.risk import (
    RiskPolicy,
    analyze_portfolio_risk,
    load_risk_policy,
    write_portfolio_risk_history,
)


def history(pattern, count=180, start=100):
    prices = []
    value = start
    for offset in range(count):
        value *= 1 + pattern[offset % len(pattern)]
        prices.append(Price(date(2025, 1, 1) + timedelta(days=offset), value))
    return prices


def position(symbol, shares, sector, theme=None, max_weight=0.5):
    return Position(
        symbol,
        shares,
        100,
        max_weight,
        0.5,
        0.5,
        0.5,
        sector=sector,
        theme=theme,
    )


class RiskTests(unittest.TestCase):
    def test_sector_concentration_blocks_candidate(self):
        positions = [
            position("HELD", 10, "Technology"),
            position("WATCH", 0, "Technology"),
        ]
        prices = {
            "HELD": history([0.01, -0.005, 0.002]),
            "WATCH": history([0.004, -0.003, 0.002]),
        }
        report = analyze_portfolio_risk(positions, prices)
        self.assertFalse(report.positions["WATCH"].buy_allowed)
        self.assertIn("Sector Technology", report.positions["WATCH"].reasons[0])
        self.assertTrue(any(alert.key == "sector:Technology" for alert in report.alerts))

    def test_highly_correlated_exposure_blocks_candidate(self):
        pattern = [0.01, -0.005, 0.003, -0.002]
        positions = [
            position("A", 6, "One"),
            position("B", 4, "Two"),
            position("WATCH", 0, "Three"),
        ]
        prices = {symbol: history(pattern) for symbol in ("A", "B", "WATCH")}
        report = analyze_portfolio_risk(positions, prices)
        assessment = report.positions["WATCH"]
        self.assertFalse(assessment.buy_allowed)
        self.assertAlmostEqual(assessment.correlated_exposure, 1.0)
        self.assertEqual(assessment.correlated_symbols, ("A", "B"))
        self.assertFalse(
            any("WATCH" in alert.key for alert in report.alerts),
            "watchlist candidates must not create held-portfolio pair alerts",
        )

    def test_volatility_produces_conservative_sizing_ceiling(self):
        positions = [position("VOL", 0, "Test", max_weight=0.5)]
        report = analyze_portfolio_risk(
            positions, {"VOL": history([0.03, -0.03, 0.02, -0.02])}
        )
        suggested = report.positions["VOL"].suggested_max_weight
        self.assertIsNotNone(suggested)
        self.assertLess(suggested, 0.10)

    def test_risk_history_is_idempotent(self):
        positions = [position("A", 1, "Same"), position("B", 1, "Same")]
        prices = {
            "A": history([0.01, -0.005, 0.003]),
            "B": history([0.01, -0.005, 0.003]),
        }
        report = analyze_portfolio_risk(positions, prices)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "risk.jsonl"
            write_portfolio_risk_history(report, path)
            write_portfolio_risk_history(report, path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(records), len(report.alerts))

    def test_policy_file_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text('{"sector_limit": 2}')
            with self.assertRaisesRegex(ValueError, "sector_limit"):
                load_risk_policy(path)

    def test_factor_beta_is_aggregated_and_high_exposure_alerts(self):
        factor_pattern = [0.01, -0.005, 0.003, -0.002]
        leveraged_pattern = [value * 2 for value in factor_pattern]
        policy = RiskPolicy(
            factor_proxies={"US_market": "SPY"},
            factor_beta_limit=1.25,
        )
        report = analyze_portfolio_risk(
            [position("HIGH_BETA", 10, "Test")],
            {
                "HIGH_BETA": history(leveraged_pattern),
                "SPY": history(factor_pattern),
            },
            policy=policy,
        )
        self.assertAlmostEqual(
            report.positions["HIGH_BETA"].factor_betas["US_market"], 2.0
        )
        self.assertAlmostEqual(report.factor_exposures["US_market"], 2.0)
        self.assertTrue(
            any(alert.key == "factor:US_market" for alert in report.alerts)
        )

    def test_missing_factor_data_is_explicit(self):
        policy = RiskPolicy(factor_proxies={"US_market": "SPY"})
        report = analyze_portfolio_risk(
            [position("ABC", 1, "Test")],
            {"ABC": history([0.01, -0.005, 0.003])},
            policy=policy,
        )
        self.assertEqual(report.factor_exposures, {})
        self.assertTrue(
            any(alert.key == "factor-data:US_market" for alert in report.alerts)
        )

    def test_negative_cash_creates_gross_exposure_alert(self):
        report = analyze_portfolio_risk(
            [position("ABC", 10, "Test", max_weight=1.0)],
            {"ABC": history([0.01, -0.005, 0.003], start=100)},
            cash_balance=-250,
        )
        self.assertGreater(report.gross_exposure, 1.0)
        self.assertLess(report.cash_weight, 0)
        self.assertTrue(any(alert.key == "gross-exposure" for alert in report.alerts))
        self.assertFalse(
            any(
                reason.startswith("Gross exposure")
                for reason in report.positions["ABC"].reasons
            )
        )

    def test_gross_exposure_can_be_configured_to_block_buys(self):
        report = analyze_portfolio_risk(
            [position("ABC", 10, "Test", max_weight=1.0)],
            {"ABC": history([0.01, -0.005, 0.003], start=100)},
            cash_balance=-250,
            policy=RiskPolicy(gross_exposure_blocks_buy=True),
        )
        self.assertFalse(report.positions["ABC"].buy_allowed)
        self.assertTrue(
            any(
                reason.startswith("Gross exposure")
                for reason in report.positions["ABC"].reasons
            )
        )

    def test_negative_net_portfolio_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "net value cannot be negative"):
            analyze_portfolio_risk(
                [position("ABC", 1, "Test")],
                {"ABC": history([0.01, -0.005, 0.003], start=100)},
                cash_balance=-1000,
            )


if __name__ == "__main__":
    unittest.main()
