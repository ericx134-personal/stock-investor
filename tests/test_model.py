import json
import unittest
from pathlib import Path

from stock_investor.model import MODEL_POLICIES, MODEL_VERSION
from stock_investor.scoring import BUY_CANDIDATE_THRESHOLD, SIGNAL_WEIGHTS


class ModelRegistryTests(unittest.TestCase):
    def test_registry_matches_runtime_model(self):
        path = Path(__file__).parents[1] / "models" / f"{MODEL_VERSION}.json"
        payload = json.loads(path.read_text())
        self.assertEqual(payload["model_version"], MODEL_VERSION)
        self.assertEqual(payload["signal_weights"], SIGNAL_WEIGHTS)
        self.assertEqual(
            payload["buy_candidate_threshold"], BUY_CANDIDATE_THRESHOLD
        )

    def test_every_runtime_policy_has_registry_entry(self):
        for version, policy in MODEL_POLICIES.items():
            path = Path(__file__).parents[1] / "models" / f"{version}.json"
            payload = json.loads(path.read_text())
            self.assertEqual(payload["model_version"], version)
            self.assertEqual(
                payload["buy_candidate_threshold"], policy.buy_candidate_threshold
            )
            self.assertEqual(
                payload["require_revisions_for_buy"],
                policy.require_revisions_for_buy,
            )

    def test_frozen_direction_candidate_is_read_only_and_unpromoted(self):
        path = Path(__file__).parents[1] / "models" / "wave-direction-v4-candidate.json"
        payload = json.loads(path.read_text())
        self.assertEqual(payload["promotion_status"], "frozen_candidate")
        self.assertEqual(payload["trade_permissions"], "none")
        self.assertEqual(payload["base_forecast_version"], "wave-direction-v4")
        self.assertTrue(payload["confidence_policy"]["wilson_lower_bound_is_audit_floor"])
        self.assertTrue(
            all(gate["status"] == "pending" for gate in payload["promotion_gates"])
        )

    def test_model_governance_defines_lifecycle_and_rollback_gates(self):
        path = Path(__file__).parents[1] / "models" / "model-governance-v1.json"
        payload = json.loads(path.read_text())
        self.assertEqual(payload["schema_version"], "model-governance-v1")
        self.assertEqual(
            set(payload["lifecycle_states"]),
            {
                "experimental",
                "frozen_candidate",
                "promoted",
                "probation",
                "retired",
                "rolled_back",
            },
        )
        promotion_gate_ids = {gate["id"] for gate in payload["promotion_gates"]}
        self.assertIn("sealed_forward_samples", promotion_gate_ids)
        self.assertIn("time_period_stability", promotion_gate_ids)
        self.assertIn("market_regime_stability", promotion_gate_ids)
        self.assertIn("false_discovery_control", promotion_gate_ids)
        rollback_gate_ids = {gate["id"] for gate in payload["rollback_gates"]}
        self.assertIn("write_action_violation", rollback_gate_ids)
        self.assertIn("private_data_exposure", rollback_gate_ids)
        self.assertIn("required_data_block_ignored", rollback_gate_ids)
        invariant_ids = {
            gate["id"]
            for gate in payload["global_invariants"]
            if gate["severity"] == "rollback"
        }
        self.assertIn("read_only_contract", invariant_ids)


if __name__ == "__main__":
    unittest.main()
