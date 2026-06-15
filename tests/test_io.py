import tempfile
import unittest
from pathlib import Path

from stock_investor.io import atomic_text_writer, atomic_write_text


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_replaces_content_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "state.json"
            output.write_text("old")
            atomic_write_text("new", output)
            self.assertEqual(output.read_text(), "new")
            self.assertEqual(list(output.parent.glob(f".{output.name}.*.tmp")), [])

    def test_failed_atomic_write_preserves_previous_content(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "state.json"
            output.write_text("old")
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                with atomic_text_writer(output) as handle:
                    handle.write("partial")
                    raise RuntimeError("interrupted")
            self.assertEqual(output.read_text(), "old")
            self.assertEqual(list(output.parent.glob(f".{output.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
