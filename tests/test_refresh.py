import csv
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stock_investor.refresh import run_refresh, validate_production_refresh


class RefreshTests(unittest.TestCase):
    def test_production_refresh_requires_private_declared_inputs(self):
        with self.assertRaisesRegex(ValueError, "private directory"):
            validate_production_refresh(
                "data/public",
                account_summary_path="summary.json",
                price_source="provider",
                price_adjustment="unknown",
            )
        with self.assertRaisesRegex(ValueError, "declared price source"):
            validate_production_refresh(
                "data/private",
                account_summary_path="summary.json",
                price_source=None,
                price_adjustment="unknown",
            )
        validate_production_refresh(
            "data/private",
            account_summary_path="summary.json",
            price_source="provider",
            price_adjustment="unknown",
        )

    def test_refresh_writes_manifest_last_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            positions = root / "positions.csv"
            positions.write_text(
                "symbol,shares,average_cost,max_portfolio_weight,quality,"
                "valuation,revisions,thesis_broken,cik,sector,theme\n"
                "ABC,10,100,0.1,0.8,0.5,,false,,Test,\n"
            )
            prices = root / "prices.csv"
            with prices.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("date", "symbol", "close"))
                start = date.today() - timedelta(days=299)
                for offset in range(300):
                    current = start + timedelta(days=offset)
                    writer.writerow((current.isoformat(), "ABC", 100 + offset))
                    writer.writerow((current.isoformat(), "SPY", 400 + offset))
            output = root / "private"

            first = run_refresh(
                positions,
                prices,
                output,
                "decision-support-v3",
                benchmark_symbol="SPY",
            )
            alert_lines = (output / "model-v3-alerts.jsonl").read_text().splitlines()
            second = run_refresh(
                positions,
                prices,
                output,
                "decision-support-v3",
                benchmark_symbol="SPY",
            )
            repeated_alert_lines = (
                output / "model-v3-alerts.jsonl"
            ).read_text().splitlines()
            manifest = json.loads((output / "refresh-manifest.json").read_text())

        self.assertTrue(first["read_only"])
        self.assertEqual(manifest["action_counts"], second["action_counts"])
        self.assertEqual(manifest["artifacts"], second["artifacts"])
        self.assertEqual(alert_lines, repeated_alert_lines)
        self.assertEqual(manifest["model_version"], "decision-support-v3")
        self.assertEqual(manifest["kline_coverage_rate"], 0)
        self.assertIn("dashboard", manifest["artifacts"])
        self.assertIn("wave_experiment_outcomes", manifest["artifacts"])
        self.assertIn("wave_experiment_scorecard", manifest["artifacts"])
        self.assertIn("wave_conditional_scorecard", manifest["artifacts"])
        self.assertIn("direction_forecasts", manifest["artifacts"])
        self.assertIn("direction_forecast_outcomes", manifest["artifacts"])
        self.assertIn("direction_forecast_scorecard", manifest["artifacts"])
        self.assertIn("model_health", manifest["artifacts"])
        self.assertIn("price_health", manifest["artifacts"])
        self.assertIn("input_integrity", manifest["artifacts"])
        self.assertEqual(manifest["model_health"]["schema_version"], "model-health-v1")
        self.assertEqual(manifest["input_integrity"]["schema_version"], "input-integrity-v1")
        self.assertEqual(len(manifest["input_integrity"]["prices"]["sha256"]), 64)
        self.assertEqual(
            first["input_integrity"]["prices"]["sha256"],
            second["input_integrity"]["prices"]["sha256"],
        )
        self.assertEqual(manifest["price_source"]["confidence"], "UNKNOWN")
        self.assertEqual(sum(manifest["price_health_status_counts"].values()), 1)
        self.assertEqual(sum(manifest["data_quality_status_counts"].values()), 1)
        self.assertIn(manifest["status"], {"BLOCKED", "DEGRADED", "PENDING", "READY"})
        self.assertIn("decisions", manifest["artifacts"])
        self.assertIn("decision_outcomes", manifest["artifacts"])
        self.assertIn("decision_scorecard", manifest["artifacts"])
        self.assertGreater(manifest["decision_ledger_records"], 0)
        self.assertGreater(manifest["historical_wave_observations"], 0)
        self.assertEqual(manifest["direction_forecast_records"], 1)
        self.assertEqual(manifest["direction_forecast_episode_count"], 1)
        self.assertEqual(sum(manifest["current_direction_forecast_counts"].values()), 1)
        self.assertIn("INCONCLUSIVE", manifest["historical_wave_evidence_counts"])
        self.assertIn("INCONCLUSIVE", manifest["conditional_wave_evidence_counts"])
        self.assertIn("WAIT", manifest["historical_wave_directional_counts"])
        self.assertIn("WAIT", manifest["conditional_wave_directional_counts"])
        self.assertIn("historical_directional_leave_one_out_downgrades", manifest)
        self.assertIn("conditional_directional_leave_one_out_downgrades", manifest)
        self.assertIn("No SEC fundamental snapshots", " ".join(manifest["warnings"]))

    def test_refresh_writes_model_comparison_when_baseline_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            positions = root / "positions.csv"
            positions.write_text(
                "symbol,shares,average_cost,max_portfolio_weight,quality,"
                "valuation,revisions,thesis_broken,cik,sector,theme\n"
                "ABC,10,100,0.1,0.8,0.5,0.2,false,,Test,\n"
            )
            prices = root / "prices.csv"
            with prices.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("date", "symbol", "close"))
                start = date.today() - timedelta(days=299)
                for offset in range(300):
                    current = start + timedelta(days=offset)
                    writer.writerow((current.isoformat(), "ABC", 100 + offset))
                    writer.writerow((current.isoformat(), "SPY", 400 + offset))
            baseline_output = root / "baseline"
            run_refresh(
                positions, prices, baseline_output, "decision-support-v1"
            )
            candidate_output = root / "candidate"
            manifest = run_refresh(
                positions,
                prices,
                candidate_output,
                "decision-support-v3",
                baseline_snapshot_path=baseline_output / "model-v1-snapshot.json",
            )

        self.assertIn("comparison", manifest["artifacts"])


if __name__ == "__main__":
    unittest.main()
