import tempfile
import unittest
import json
from datetime import date, timedelta
from pathlib import Path

from stock_investor.dashboard import _price_plan, build_dashboard


class DashboardTests(unittest.TestCase):
    def test_price_plan_uses_structural_zone_and_refuses_wait(self):
        wave = {
            "support_zone_low": 90,
            "support_zone_high": 94,
            "resistance_zone_low": 108,
            "resistance_zone_high": 112,
        }
        buy = _price_plan("BUY", wave, 100)
        sell = _price_plan("SELL", wave, 100)
        self.assertEqual((buy["low"], buy["high"], buy["midpoint"]), (90, 94, 92))
        self.assertEqual((sell["low"], sell["high"], sell["midpoint"]), (108, 112, 110))
        self.assertIn("below the current price", buy["proximity"])
        self.assertIn("above the current price", sell["proximity"])
        breakout = _price_plan("SELL", wave, 118)
        self.assertEqual(breakout["label"], "Breakout retest zone")
        self.assertEqual(breakout["plan_class"], "breakout")
        self.assertIn("invalidated", breakout["interpretation"])
        self.assertIn("below the current price", breakout["proximity"])
        self.assertIsNone(_price_plan("WAIT", wave, 100))

    def test_dashboard_prioritizes_and_escapes_alerts(self):
        with tempfile.TemporaryDirectory() as directory:
            alerts = Path(directory) / "alerts.jsonl"
            alerts.write_text(
                '{"symbol":"ABC","portfolio_weight":0.2,"latest_close":10,'
                '"observed_at":"2026-01-01","alert":{"action":"TRIM_REVIEW",'
                '"score":-0.4,"reasons":["Drawdown < review"]},'
                '"technicals":{"drawdown_from_high":-0.3,"return_12_to_1":0.1}}\n'
            )
            scorecard = Path(directory) / "scorecard.json"
            scorecard.write_text(
                '[{"action":"TRIM_REVIEW","horizon":"21d","observations":4,'
                '"directional_success_rate":0.75,"mean_directional_return":0.1}]'
            )
            decision_scorecard = Path(directory) / "decision-scorecard.json"
            decision_scorecard.write_text(
                '[{"model_version":"test-v1","action":"HOLD","horizon":"21d",'
                '"observations":3,"positive_rate":0.67,"mean_excess_return":0.04,'
                '"directional_success_rate":0.67}]'
            )
            direction_scorecard = Path(directory) / "direction-scorecard.json"
            direction_scorecard.write_text(
                '[{"forecast_version":"wave-direction-v1","direction":"BUY",'
                '"horizon":"21d","forecast_episodes":3,'
                '"observations":1,"pending":2,"mean_probability":0.8,'
                '"directional_success_rate":1.0,"brier_score":0.04}]'
            )
            model_health = Path(directory) / "model-health.json"
            model_health.write_text(
                json.dumps(
                    {
                        "overall_status": "PENDING",
                        "failed_gates": [],
                        "pending_gates": ["matured_directional_evidence"],
                        "blocking_failures": [],
                        "gates": [
                            {
                                "id": "read_only",
                                "status": "PASS",
                                "actual": True,
                                "threshold": True,
                                "detail": "No brokerage writes.",
                            }
                        ],
                    }
                )
            )
            price_health = Path(directory) / "price-health.json"
            price_health.write_text(
                json.dumps(
                    {
                        "symbols": [
                            {
                                "symbol": "ABC",
                                "status": "FRESH",
                                "latest_date": "2026-01-01",
                                "age_calendar_days": 1,
                                "ohlcv_coverage_rate": 0.9,
                                "source": "Test provider",
                                "source_confidence": "DECLARED",
                            }
                        ]
                    }
                )
            )
            page = build_dashboard(
                alerts,
                scorecard_path=scorecard,
                decision_scorecard_path=decision_scorecard,
                direction_forecast_scorecard_path=direction_scorecard,
                model_health_path=model_health,
                price_health_path=price_health,
            )
        self.assertIn("ABC", page)
        self.assertIn("TRIM REVIEW", page)
        self.assertIn("Drawdown &lt; review", page)
        self.assertIn("100%", page)
        self.assertIn("75%", page)
        self.assertIn("Bearish / trim review", page)
        self.assertIn("K-line evidence", page)
        self.assertIn("Priority Board", page)
        self.assertIn('class="decision-board"', page)
        self.assertIn('class="signal-column buy-column"', page)
        self.assertIn('class="signal-column sell-column"', page)
        self.assertIn('<details class="signal-column wait-column">', page)
        self.assertNotIn('<details class="signal-column wait-column" open>', page)
        self.assertIn("WAIT is folded by default", page)
        self.assertIn("All-Decision Forward Evidence", page)
        self.assertIn("Displayed Direction Forecast Validation", page)
        self.assertIn("Explicit Model-Health Gates", page)
        self.assertIn("Per-Symbol Price Freshness", page)
        self.assertIn("Test provider · declared", page)
        self.assertIn("Read Only", page)
        self.assertIn("wave-direction-v1", page)
        self.assertIn("<td>3</td><td>1</td><td>2</td>", page)
        self.assertIn("Brier score", page)
        self.assertIn("BUY/SELL Calibration Curves", page)
        self.assertIn("Directional Classification Metrics", page)
        self.assertIn("Largest False Direction Episodes", page)
        self.assertIn("Includes HOLD and ordinary REVIEW decisions", page)
        self.assertIn('class="holding-row trim_review signal-wait"', page)
        self.assertIn('data-detail-target="holding-detail-0"', page)
        self.assertIn('id="holding-drawer"', page)
        self.assertIn('data-tab-target="research"', page)
        self.assertIn("Gain / loss", page)
        self.assertIn("<strong>WAIT</strong><b>--</b>", page)
        self.assertIn("no wave analog", page)
        self.assertNotIn("Prioritized Signals", page)

    def test_dashboard_does_not_blend_evidence_across_model_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "model_version": "decision-support-v2",
                        "observed_at": "2026-01-01",
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {
                                    "action": "TRIM_REVIEW",
                                    "score": -0.4,
                                    "reasons": [],
                                },
                            }
                        ],
                    }
                )
            )
            scorecard = Path(directory) / "scorecard.json"
            scorecard.write_text(
                '[{"model_version":"decision-support-v1","action":"TRIM_REVIEW",'
                '"horizon":"21d","observations":4,"directional_success_rate":0.75,'
                '"mean_directional_return":0.1}]'
            )
            comparison = Path(directory) / "comparison.json"
            comparison.write_text(
                json.dumps(
                    {
                        "baseline": {"actionable_rate": 0.8},
                        "candidate": {"actionable_rate": 0.6},
                        "actionable_count_change": -5,
                        "changed_symbols": {"ABC": {}},
                    }
                )
            )
            coverage = Path(directory) / "coverage.json"
            coverage.write_text(
                json.dumps(
                    {
                        "quality_coverage_rate": 0.5,
                        "valuation_coverage_rate": 0.25,
                        "revisions_coverage_rate": 0.0,
                        "v3_buy_ready_symbols": ["ABC"],
                    }
                )
            )
            page = build_dashboard(
                snapshot,
                scorecard_path=scorecard,
                comparison_path=comparison,
                fundamental_coverage_path=coverage,
            )
        self.assertIn("decision-support-v2", page)
        self.assertNotIn("75%", page)
        self.assertIn("Model Experiment", page)
        self.assertIn("Fundamental Coverage", page)
        self.assertIn("ABC", page)

    def test_dashboard_separates_exploratory_wave_history_from_live_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "model_version": "decision-support-v3",
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0.1, "reasons": []},
                            }
                        ],
                    }
                )
            )
            wave_snapshot = root / "wave-snapshot.json"
            wave_snapshot.write_text(
                json.dumps(
                    {
                        "waves": {
                            "ABC": {
                                "regime": "Advancing wave",
                                "active_wave_return": 0.12,
                                "wave_age_sessions": 30,
                            }
                        }
                    }
                )
            )
            experiment = root / "wave-experiment-scorecard.json"
            experiment.write_text(
                json.dumps(
                    [
                        {
                            "regime": "Advancing wave",
                            "horizon": "63d",
                            "positive_rate": 0.7,
                            "positive_rate_ci_low": 0.55,
                            "positive_rate_ci_high": 0.85,
                            "directional_symbols": 10,
                            "symbol_positive_return_rate": 0.8,
                            "symbol_positive_return_ci_low": 0.55,
                            "symbol_positive_return_ci_high": 0.95,
                            "top_symbol_return_observation_share": 0.1,
                            "beat_benchmark_rate": 0.6,
                            "beat_benchmark_ci_low": 0.31,
                            "beat_benchmark_ci_high": 0.83,
                            "benchmark_symbols": 10,
                            "symbol_positive_excess_rate": 0.6,
                            "symbol_positive_excess_ci_low": 0.31,
                            "symbol_positive_excess_ci_high": 0.83,
                            "top_symbol_observation_share": 0.1,
                            "median_return": 0.08,
                            "mean_max_gain": 0.2,
                            "mean_max_loss": -0.1,
                            "observations": 10,
                        }
                    ]
                )
            )
            conditional = root / "wave-conditional-scorecard.json"
            conditional.write_text(
                json.dumps(
                    [
                        {
                            "regime": "Advancing wave",
                            "horizon": "63d",
                            "wave_age_bucket": "EXTENDED",
                            "wave_magnitude_bucket": "DEVELOPING",
                            "positive_rate": 0.8,
                            "beat_benchmark_rate": 0.8,
                            "beat_benchmark_ci_low": 0.3,
                            "beat_benchmark_ci_high": 0.95,
                            "benchmark_symbols": 4,
                            "symbol_positive_excess_rate": 0.75,
                            "symbol_positive_excess_ci_low": 0.3,
                            "symbol_positive_excess_ci_high": 0.95,
                            "top_symbol_observation_share": 0.25,
                            "median_return": 0.1,
                            "mean_max_gain": 0.2,
                            "mean_max_loss": -0.1,
                            "observations": 5,
                        }
                    ]
                )
            )
            page = build_dashboard(
                snapshot,
                wave_snapshot_path=wave_snapshot,
                wave_experiment_scorecard_path=experiment,
                wave_conditional_scorecard_path=conditional,
            )
        self.assertIn("Historical Wave Experiment", page)
        self.assertIn("Current Wave Analog Ranking", page)
        self.assertIn("Live Structural Wave Evidence", page)
        self.assertIn("Exploratory historical 63d analogs", page)
        self.assertIn("60% (31%–83%) beat SPY", page)
        self.assertIn("cross-stock breadth", page)
        self.assertIn("Cross-stock breadth (95% CI)", page)
        self.assertIn("Inconclusive", page)
        self.assertIn('id="tab-research" class="tab-view"', page)
        self.assertIn('id="holding-detail-0" class="holding-detail" hidden', page)
        self.assertIn("not a promoted prediction model", page)
        self.assertIn("Conditional Wave Precision Audit", page)
        self.assertIn("Leave-one-symbol-out", page)
        self.assertIn("Conditional precision refused", page)
        self.assertIn("<strong>BUY</strong><b>57%</b>", page)
        self.assertIn("57% shrunk confidence; raw analog rate 70%", page)
        self.assertIn("shrunk robust evidence", page)
        self.assertIn("direction gate", page)

    def test_review_outcome_without_directional_rate_does_not_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "model_version": "decision-support-v3",
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "REVIEW", "score": -0.1, "reasons": []},
                            }
                        ],
                    }
                )
            )
            scorecard = root / "decision-scorecard.json"
            scorecard.write_text(
                '[{"model_version":"decision-support-v3","action":"REVIEW",'
                '"horizon":"21d","observations":5,"positive_rate":0.6,'
                '"directional_success_rate":null}]'
            )
            page = build_dashboard(snapshot, decision_scorecard_path=scorecard)
        self.assertIn("60% positive-return rate across 5 matured outcomes", page)

    def test_research_tab_shows_direction_rate_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            comparison = root / "direction-rate-comparison.json"
            comparison.write_text(
                json.dumps(
                    [
                        {
                            "comparison_version": "direction-rate-comparison-v1",
                            "source": "BROAD",
                            "direction": "BUY",
                            "horizon": "63d",
                            "regime": "Advancing wave",
                            "wave_age_bucket": None,
                            "wave_magnitude_bucket": None,
                            "observations": 20,
                            "directional_symbols": 12,
                            "raw_probability": 0.8,
                            "shrunk_probability": 0.65,
                            "wilson_lower_probability": 0.6,
                        }
                    ]
                )
            )
            page = build_dashboard(
                snapshot,
                direction_rate_comparison_path=comparison,
            )
        self.assertIn("Raw vs Shrunk vs Wilson Direction Rates", page)
        self.assertIn("<td>80.0%</td><td>65.0%</td><td>60.0%</td>", page)
        self.assertIn("raw rates are not promoted directly", page)

    def test_research_tab_shows_time_decayed_wave_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            time_decay = root / "wave-time-decay-scorecard.json"
            time_decay.write_text(
                json.dumps(
                    [
                        {
                            "decay_version": "wave-time-decay-v1",
                            "regime": "Advancing wave",
                            "horizon": "21d",
                            "weighted_positive_rate": 0.66,
                            "weighted_mean_return": 0.12,
                            "weighted_mean_excess_return": 0.04,
                            "weighted_observations": 8.5,
                            "symbols": 9,
                            "observations": 12,
                            "top_symbol_weight_share": 0.2,
                        }
                    ]
                )
            )
            page = build_dashboard(
                snapshot,
                wave_time_decay_scorecard_path=time_decay,
            )
        self.assertIn("Time-Decayed Wave Experiment", page)
        self.assertIn("older analogs decay with a one-year half-life", page)
        self.assertIn("<td>66.0%</td><td>12.0%</td><td>4.0%</td>", page)

    def test_research_tab_shows_multiple_testing_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            ledger = root / "multiple-testing-ledger.json"
            ledger.write_text(
                json.dumps(
                    {
                        "ledger_version": "multiple-testing-ledger-v1",
                        "total_hypothesis_count": 33,
                        "family_hypothesis_counts": {"structural_wave": 33},
                        "rows": [
                            {
                                "family": "structural_wave",
                                "id": "wave_conditional_scorecard",
                                "hypothesis_count": 33,
                                "multiple_testing_risk": "HIGH",
                                "family_hypothesis_count": 33,
                                "family_multiple_testing_risk": "HIGH",
                                "predeclared": True,
                                "promotion_status": "LEDGER_ONLY",
                            }
                        ],
                    }
                )
            )
            page = build_dashboard(snapshot, multiple_testing_ledger_path=ledger)
        self.assertIn("Multiple-Testing Ledger", page)
        self.assertIn("Total tested rows", page)
        self.assertIn("family-level false-discovery controls", page)
        self.assertIn("<td>structural_wave</td><td>wave_conditional_scorecard</td>", page)

    def test_robust_conditional_direction_can_override_inconclusive_broad_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            wave_snapshot = root / "waves.json"
            start = date(2025, 1, 1)
            wave_snapshot.write_text(
                json.dumps(
                    {
                        "waves": {
                            "ABC": {
                                "regime": "Advancing wave",
                                "wave_age_sessions": 15,
                                "active_wave_return": 0.1,
                                "reversal_threshold": 0.08,
                                "last_pivot_date": (start + timedelta(days=110)).isoformat(),
                                "last_pivot_price": 110,
                                "support_zone_low": 106,
                                "support_zone_high": 112,
                                "resistance_zone_low": 124,
                                "resistance_zone_high": 130,
                            }
                        }
                    }
                )
            )
            broad = root / "broad.json"
            broad.write_text(
                json.dumps(
                    [
                        {
                            "regime": "Advancing wave",
                            "horizon": "21d",
                            "observations": 20,
                            "positive_rate": 0.4,
                            "median_return": -0.01,
                            "mean_max_gain": 0.1,
                            "mean_max_loss": -0.1,
                        }
                    ]
                )
            )
            conditional = root / "conditional.json"
            conditional.write_text(
                json.dumps(
                    [
                        {
                            "regime": "Advancing wave",
                            "horizon": "21d",
                            "wave_age_bucket": "MATURE",
                            "wave_magnitude_bucket": "DEVELOPING",
                            "observations": 18,
                            "directional_symbols": 14,
                            "positive_rate": 0.83,
                            "positive_rate_ci_low": 0.6,
                            "positive_rate_ci_high": 0.95,
                            "symbol_positive_return_rate": 0.79,
                            "symbol_positive_return_ci_low": 0.52,
                            "symbol_positive_return_ci_high": 0.92,
                            "top_symbol_return_observation_share": 0.12,
                            "median_return": 0.1,
                            "mean_max_gain": 0.2,
                            "mean_max_loss": -0.05,
                        }
                    ]
                )
            )
            prices = root / "prices.csv"
            prices.write_text(
                "date,symbol,close,open,high,low,volume\n"
                + "".join(
                    f"{(start + timedelta(days=index)).isoformat()},ABC,{100 + index * 0.15:.2f},"
                    f"{99.5 + index * 0.15:.2f},{101 + index * 0.15:.2f},"
                    f"{99 + index * 0.15:.2f},{100000 + index * 100}\n"
                    for index in range(130)
                )
            )
            page = build_dashboard(
                snapshot,
                wave_snapshot_path=wave_snapshot,
                wave_experiment_scorecard_path=broad,
                wave_conditional_scorecard_path=conditional,
                prices_path=prices,
            )
        self.assertIn("<strong>BUY</strong><b>66%</b>", page)
        self.assertIn("66% shrunk confidence; raw analog rate 83%", page)
        self.assertIn('class="price-target">$106.00–$112.00</small>', page)
        self.assertIn("<h3>$106.00–$112.00</h3>", page)
        self.assertIn('class="info-tip"', page)
        self.assertIn('class="target-zone buy"', page)
        self.assertIn("Buy zone $106.00–$112.00", page)
        self.assertIn("Conditional age/magnitude evidence used", page)
        self.assertIn("direction gate <b>BUY</b>", page)
        self.assertIn('class="kline-chart"', page)
        self.assertIn("126-session daily K-line", page)
        self.assertIn("Support zone", page)
        self.assertIn("Your position", page)
        self.assertIn("Average cost", page)
        self.assertIn("Cost basis", page)
        self.assertIn('<details class="advanced-details">', page)
        self.assertNotIn('<details class="advanced-details" open>', page)

    def test_poor_data_quality_blocks_kline_chart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            quality = root / "price-health.json"
            quality.write_text(
                json.dumps(
                    {
                        "symbols": [
                            {"symbol": "ABC", "data_quality_status": "POOR"}
                        ]
                    }
                )
            )
            page = build_dashboard(snapshot, price_health_path=quality)
        self.assertIn("K-line chart blocked by the data-quality gate", page)


if __name__ == "__main__":
    unittest.main()
