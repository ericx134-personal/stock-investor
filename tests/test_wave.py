import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stock_investor.data import Price
from stock_investor.wave import (
    append_directional_forecast_history,
    append_wave_history,
    build_direction_rate_comparison_scorecard,
    build_directional_forecasts,
    build_price_zone_replay,
    build_price_zone_replay_scorecard,
    build_wave_conditional_scorecard,
    build_wave_scorecard,
    build_wave_walk_forward_outcomes,
    build_wave_walk_forward_scorecard,
    calculate_wave,
    classify_wave_directional_evidence,
    classify_wave_walk_forward_evidence,
    evaluate_wave_history,
    load_wave_history,
    load_directional_forecast_history,
    shrink_direction_probability,
    wave_age_bucket,
    wave_magnitude_bucket,
)


def wave_history():
    values = []
    anchors = [(0, 100), (45, 145), (85, 112), (130, 170), (175, 135), (230, 190)]
    for (start, left), (end, right) in zip(anchors[:-1], anchors[1:]):
        for offset in range(start, end):
            fraction = (offset - start) / (end - start)
            values.append(left + (right - left) * fraction)
    values.extend([190 + offset * 0.4 for offset in range(70)])
    return [
        Price(date(2025, 1, 1) + timedelta(days=offset), value)
        for offset, value in enumerate(values)
    ]


class WaveTests(unittest.TestCase):
    def test_confirmed_pivots_describe_active_multiweek_wave(self):
        signal = calculate_wave("ABC", wave_history())
        self.assertGreaterEqual(signal.pivot_count, 4)
        self.assertEqual(signal.direction, "ADVANCING")
        self.assertEqual(signal.last_pivot_type, "LOW")
        self.assertGreater(signal.wave_age_sessions, 20)
        self.assertGreater(signal.active_wave_return, 0)
        self.assertIsNotNone(signal.support)
        self.assertIsNotNone(signal.resistance)
        self.assertLess(signal.support_zone_low, signal.support_zone_high)
        self.assertLess(signal.resistance_zone_low, signal.resistance_zone_high)

    def test_wave_history_and_long_horizon_evaluation_are_idempotent(self):
        signal = calculate_wave("ABC", wave_history())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wave.jsonl"
            self.assertEqual(append_wave_history({"ABC": signal}, path), 1)
            self.assertEqual(append_wave_history({"ABC": signal}, path), 0)
            records = load_wave_history(path)
        outcomes = evaluate_wave_history(records, {"ABC": wave_history()})
        scorecard = build_wave_scorecard(outcomes)
        self.assertEqual(json.loads(json.dumps(records))[0]["feature_version"], "wave-v1")
        self.assertEqual(set(outcomes[0]["returns"]), {"21d", "63d", "126d"})
        self.assertEqual(scorecard, [])

    def test_short_history_refuses_to_invent_wave(self):
        with self.assertRaisesRegex(ValueError, "at least 126"):
            calculate_wave("ABC", wave_history()[:100])

    def test_walk_forward_wave_experiment_is_causal_and_non_overlapping(self):
        history = wave_history()
        spy = [
            Price(item.date, 200 + index * 0.1)
            for index, item in enumerate(history)
        ]
        outcomes = build_wave_walk_forward_outcomes({"ABC": history, "SPY": spy})
        extended = history + [
            Price(history[-1].date + timedelta(days=offset + 1), 218 + offset)
            for offset in range(30)
        ]
        extended_spy = spy + [
            Price(spy[-1].date + timedelta(days=offset + 1), 230 + offset * 0.1)
            for offset in range(30)
        ]
        extended_outcomes = build_wave_walk_forward_outcomes(
            {"ABC": extended, "SPY": extended_spy}
        )
        extended_by_key = {
            (item["signal_date"], item["horizon"]): item
            for item in extended_outcomes
        }
        for outcome in outcomes:
            same = extended_by_key[(outcome["signal_date"], outcome["horizon"])]
            self.assertEqual(outcome["regime"], same["regime"])
            self.assertEqual(outcome["forward_return"], same["forward_return"])
            self.assertTrue(outcome["non_overlapping_within_symbol_horizon"])
            self.assertIsNotNone(outcome["excess_return"])
        for horizon in (21, 63, 126):
            dates = [
                date.fromisoformat(item["signal_date"])
                for item in outcomes
                if item["horizon"] == f"{horizon}d"
            ]
            self.assertTrue(
                all((right - left).days >= horizon for left, right in zip(dates, dates[1:]))
            )
        scorecard = build_wave_walk_forward_scorecard(outcomes)
        self.assertTrue(scorecard)
        self.assertIn("median_return", scorecard[0])
        self.assertIn("mean_max_gain", scorecard[0])
        self.assertIn("mean_max_loss", scorecard[0])
        self.assertIn("beat_benchmark_rate", scorecard[0])
        self.assertIn("symbol_positive_excess_rate", scorecard[0])
        self.assertIn("symbol_positive_excess_ci_low", scorecard[0])
        self.assertIn("symbol_positive_excess_ci_high", scorecard[0])
        self.assertIn("top_symbol_observation_share", scorecard[0])
        self.assertIn("evidence_classification", scorecard[0])
        self.assertIn("symbol_positive_return_rate", scorecard[0])
        self.assertIn("symbol_positive_return_ci_low", scorecard[0])
        self.assertIn("symbol_positive_return_ci_high", scorecard[0])
        self.assertIn("directional_evidence_classification", scorecard[0])
        self.assertIn("directional_leave_one_out_rate", scorecard[0])
        self.assertIn("relative_leave_one_out_rate", scorecard[0])
        self.assertGreater(scorecard[0]["benchmark_symbols"], 0)
        self.assertLessEqual(
            scorecard[0]["beat_benchmark_ci_low"],
            scorecard[0]["beat_benchmark_rate"],
        )
        self.assertGreaterEqual(
            scorecard[0]["beat_benchmark_ci_high"],
            scorecard[0]["beat_benchmark_rate"],
        )
        self.assertGreaterEqual(scorecard[0]["beat_benchmark_ci_low"], 0)
        self.assertLessEqual(scorecard[0]["beat_benchmark_ci_high"], 1)
        self.assertGreaterEqual(scorecard[0]["symbol_positive_excess_ci_low"], 0)
        self.assertLessEqual(scorecard[0]["symbol_positive_excess_ci_high"], 1)

    def test_robust_evidence_requires_pooled_and_cross_symbol_agreement(self):
        robust_caution = {
            "observations": 20,
            "benchmark_symbols": 12,
            "top_symbol_observation_share": 0.15,
            "beat_benchmark_ci_low": 0.1,
            "beat_benchmark_ci_high": 0.4,
            "symbol_positive_excess_ci_low": 0.1,
            "symbol_positive_excess_ci_high": 0.4,
        }
        self.assertEqual(
            classify_wave_walk_forward_evidence(robust_caution), "CAUTION"
        )
        self.assertEqual(
            classify_wave_walk_forward_evidence(
                {**robust_caution, "benchmark_symbols": 3}
            ),
            "INCONCLUSIVE",
        )
        self.assertEqual(
            classify_wave_walk_forward_evidence(
                {**robust_caution, "symbol_positive_excess_ci_high": 0.7}
            ),
            "INCONCLUSIVE",
        )

    def test_predeclared_conditional_buckets_and_thin_sample_refusal(self):
        self.assertEqual(wave_age_bucket(10), "EARLY")
        self.assertEqual(wave_age_bucket(11), "MATURE")
        self.assertEqual(wave_age_bucket(26), "EXTENDED")
        self.assertEqual(wave_magnitude_bucket(0.119, 0.08)[1], "DEVELOPING")
        self.assertEqual(wave_magnitude_bucket(0.12, 0.08)[1], "ESTABLISHED")
        self.assertEqual(wave_magnitude_bucket(-0.25, 0.08)[1], "EXTENDED")
        outcomes = [
            {
                "symbol": f"S{index}",
                "regime": "Advancing wave",
                "horizon": "21d",
                "wave_age_sessions": 8,
                "active_wave_return": 0.1,
                "reversal_threshold": 0.08,
                "forward_return": 0.1,
                "excess_return": 0.05,
                "max_gain": 0.15,
                "max_loss": -0.02,
            }
            for index in range(7)
        ]
        row = build_wave_conditional_scorecard(outcomes)[0]
        self.assertEqual(row["wave_age_bucket"], "EARLY")
        self.assertEqual(row["wave_magnitude_bucket"], "DEVELOPING")
        self.assertEqual(row["evidence_classification"], "INCONCLUSIVE")
        self.assertEqual(row["directional_evidence_classification"], "WAIT")

    def test_directional_evidence_requires_pooled_and_cross_symbol_agreement(self):
        robust_sell = {
            "observations": 20,
            "directional_symbols": 12,
            "top_symbol_return_observation_share": 0.15,
            "positive_rate_ci_low": 0.1,
            "positive_rate_ci_high": 0.4,
            "symbol_positive_return_ci_low": 0.1,
            "symbol_positive_return_ci_high": 0.4,
        }
        self.assertEqual(classify_wave_directional_evidence(robust_sell), "SELL")
        self.assertEqual(
            classify_wave_directional_evidence(
                {
                    **robust_sell,
                    "positive_rate_ci_low": 0.6,
                    "positive_rate_ci_high": 0.9,
                    "symbol_positive_return_ci_low": 0.6,
                    "symbol_positive_return_ci_high": 0.9,
                }
            ),
            "BUY",
        )
        self.assertEqual(
            classify_wave_directional_evidence(
                {**robust_sell, "symbol_positive_return_ci_high": 0.7}
            ),
            "WAIT",
        )
        self.assertEqual(
            classify_wave_directional_evidence(
                {**robust_sell, "directional_leave_one_out_stable": False}
            ),
            "WAIT",
        )

    def test_leave_one_symbol_out_downgrades_fragile_direction(self):
        outcomes = [
            {
                "symbol": f"S{index}",
                "regime": "Advancing wave",
                "horizon": "21d",
                "forward_return": 0.1,
                "excess_return": 0.05,
                "max_gain": 0.15,
                "max_loss": -0.02,
            }
            for index in range(8)
        ]
        outcomes.extend(
            {
                "symbol": f"S{index}",
                "regime": "Advancing wave",
                "horizon": "21d",
                "forward_return": 0.08,
                "excess_return": 0.04,
                "max_gain": 0.12,
                "max_loss": -0.01,
            }
            for index in range(8)
        )
        row = build_wave_walk_forward_scorecard(outcomes)[0]
        self.assertFalse(row["directional_leave_one_out_stable"])
        self.assertEqual(row["directional_evidence_classification"], "WAIT")

    def test_directional_forecast_uses_robust_conditional_evidence(self):
        signal = calculate_wave("ABC", wave_history())
        age = wave_age_bucket(signal.wave_age_sessions)
        magnitude = wave_magnitude_bucket(
            signal.active_wave_return, signal.reversal_threshold
        )[1]
        broad = [{"regime": signal.regime, "horizon": "21d", "observations": 20}]
        conditional = [
            {
                "regime": signal.regime,
                "horizon": "21d",
                "wave_age_bucket": age,
                "wave_magnitude_bucket": magnitude,
                "observations": 18,
                "directional_symbols": 14,
                "positive_rate": 0.83,
                "positive_rate_ci_low": 0.60,
                "positive_rate_ci_high": 0.95,
                "symbol_positive_return_ci_low": 0.52,
                "symbol_positive_return_ci_high": 0.92,
                "top_symbol_return_observation_share": 0.12,
            }
        ]
        forecast = build_directional_forecasts(
            {"ABC": signal}, {"ABC"}, broad, conditional
        )[0]
        self.assertEqual(forecast["direction"], "BUY")
        self.assertEqual(forecast["evidence_source"], "CONDITIONAL")
        self.assertEqual(forecast["raw_probability"], 0.83)
        self.assertLess(forecast["probability"], forecast["raw_probability"])
        self.assertEqual(forecast["probability_shrinkage_prior_observations"], 20)

    def test_direction_probability_shrinks_small_samples_toward_even_odds(self):
        self.assertEqual(shrink_direction_probability(0.8, 0), 0.5)
        self.assertAlmostEqual(shrink_direction_probability(0.8, 20), 0.65)
        self.assertAlmostEqual(
            shrink_direction_probability(0.8, 200), 0.7727272727272727
        )
        self.assertIsNone(shrink_direction_probability(1.2, 20))
        self.assertIsNone(shrink_direction_probability(0.8, -1))

    def test_direction_rate_comparison_keeps_raw_shrunk_and_wilson_floor(self):
        broad = [
            {
                "regime": "Advancing wave",
                "horizon": "63d",
                "observations": 20,
                "directional_symbols": 12,
                "positive_rate": 0.8,
                "positive_rate_ci_low": 0.6,
                "positive_rate_ci_high": 0.92,
                "symbol_positive_return_ci_low": 0.55,
                "symbol_positive_return_ci_high": 0.9,
                "top_symbol_return_observation_share": 0.15,
            },
            {
                "regime": "Declining wave",
                "horizon": "63d",
                "observations": 20,
                "directional_symbols": 12,
                "positive_rate": 0.2,
                "positive_rate_ci_low": 0.08,
                "positive_rate_ci_high": 0.4,
                "symbol_positive_return_ci_low": 0.1,
                "symbol_positive_return_ci_high": 0.45,
                "top_symbol_return_observation_share": 0.15,
            },
        ]
        rows = build_direction_rate_comparison_scorecard(broad, [])
        by_direction = {row["direction"]: row for row in rows}
        self.assertEqual(set(by_direction), {"BUY", "SELL"})
        self.assertAlmostEqual(by_direction["BUY"]["raw_probability"], 0.8)
        self.assertAlmostEqual(by_direction["BUY"]["shrunk_probability"], 0.65)
        self.assertAlmostEqual(by_direction["BUY"]["wilson_lower_probability"], 0.6)
        self.assertAlmostEqual(by_direction["SELL"]["raw_probability"], 0.8)
        self.assertAlmostEqual(by_direction["SELL"]["shrunk_probability"], 0.65)
        self.assertAlmostEqual(by_direction["SELL"]["wilson_lower_probability"], 0.6)
        self.assertEqual(by_direction["BUY"]["display_policy"], "SHRUNK_RATE")

    def test_blocked_wait_forecast_keeps_probability_schema(self):
        forecast = build_directional_forecasts(
            {},
            {"ABC"},
            [],
            [],
            prices={"ABC": [Price(date(2026, 1, 2), 100)]},
            blocked_reasons={"ABC": "STALE price data"},
        )[0]
        self.assertEqual(forecast["direction"], "WAIT")
        self.assertIsNone(forecast["probability"])
        self.assertIsNone(forecast["raw_probability"])
        self.assertEqual(forecast["probability_shrinkage_prior_observations"], 20)

    def test_directional_forecast_history_is_idempotent(self):
        forecast = {
            "forecast_id": "wave-direction-v1|ABC|2026-01-01",
            "forecast_version": "wave-direction-v1",
            "symbol": "ABC",
            "signal_date": "2026-01-01",
            "entry_close": 100,
            "direction": "WAIT",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forecasts.jsonl"
            self.assertEqual(append_directional_forecast_history([forecast], path), 1)
            self.assertEqual(append_directional_forecast_history([forecast], path), 0)
            records = load_directional_forecast_history(path)
        self.assertEqual(len(records), 1)
        self.assertIn("observed_at", records[0])

    def test_price_zone_replay_scores_pretend_day_zones(self):
        records = build_price_zone_replay({"ABC": wave_history()}, horizon_sessions=5)
        self.assertTrue(records)
        sample = records[0]
        self.assertEqual(sample["replay_version"], "price-zone-replay-v1")
        self.assertIn(sample["zone_label"], {"BUY", "SELL"})
        self.assertIn(
            sample["outcome"],
            {
                "TOUCHED",
                "MISSED",
                "INVALIDATED_BEFORE_TOUCH",
                "RETEST_HELD",
                "NO_RETEST",
                "RETEST_FAILED",
            },
        )
        scorecard = build_price_zone_replay_scorecard(records)
        self.assertTrue(scorecard)
        self.assertIn("touch_rate", scorecard[0])

    def test_directional_forecast_records_wait_when_wave_is_unavailable(self):
        history = wave_history()[:20]
        forecast = build_directional_forecasts(
            {}, {"ABC"}, [], [], {"ABC": history}
        )[0]
        self.assertEqual(forecast["direction"], "WAIT")
        self.assertEqual(forecast["evidence_source"], "NONE")
        self.assertEqual(forecast["signal_date"], history[-1].date.isoformat())

    def test_directional_forecast_waits_when_data_quality_blocks_wave(self):
        history = wave_history()
        forecast = build_directional_forecasts(
            {"ABC": calculate_wave("ABC", history)},
            {"ABC"},
            [],
            [],
            {"ABC": history},
            {"ABC": "Data quality gate blocked direction: STALE / POOR"},
        )[0]
        self.assertEqual(forecast["direction"], "WAIT")
        self.assertEqual(forecast["evidence_source"], "NONE")
        self.assertIn("Data quality gate blocked", forecast["regime"])


if __name__ == "__main__":
    unittest.main()
