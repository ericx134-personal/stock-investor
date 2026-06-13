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


if __name__ == "__main__":
    unittest.main()
