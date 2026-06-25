import tempfile
import time
import unittest
from pathlib import Path

from stock_investor.web_server import RefreshState


class WebServerTests(unittest.TestCase):
    def test_refresh_state_runs_one_refresh_at_a_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "refresh.sh"
            script.write_text(
                "#!/bin/sh\n"
                "printf '{\"progress\":55,\"message\":\"quotes updated\"}\\n' > \"$STOCK_INVESTOR_REFRESH_PROGRESS\"\n"
                "sleep 0.3\n"
                "exit 0\n"
            )
            script.chmod(0o755)

            state = RefreshState()
            self.assertTrue(state.start([str(script)], root))
            self.assertFalse(state.start([str(script)], root))
            seen_progress = False
            for _ in range(50):
                snapshot = state.snapshot()
                seen_progress = seen_progress or snapshot.get("progress") == 55
                if snapshot["status"] == "succeeded":
                    break
                time.sleep(0.02)

        self.assertTrue(seen_progress)
        self.assertEqual(state.snapshot()["status"], "succeeded")
        self.assertEqual(state.snapshot()["progress"], 100)


if __name__ == "__main__":
    unittest.main()
