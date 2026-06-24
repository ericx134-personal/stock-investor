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
            script.write_text("#!/bin/sh\nexit 0\n")
            script.chmod(0o755)

            state = RefreshState()
            self.assertTrue(state.start([str(script)], root))
            self.assertFalse(state.start([str(script)], root))
            for _ in range(20):
                if state.snapshot()["status"] == "succeeded":
                    break
                time.sleep(0.02)

        self.assertEqual(state.snapshot()["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
