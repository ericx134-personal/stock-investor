import tarfile
import tempfile
import unittest
from datetime import date
from pathlib import Path

from stock_investor.archive import archive_private_artifacts


class ArchiveTests(unittest.TestCase):
    def test_archive_preserves_ledgers_and_excludes_credentials_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "data" / "private"
            private.mkdir(parents=True)
            (private / "forecasts.jsonl").write_text("failed forecast\n")
            (private / "snapshot.json").write_text("{}\n")
            (private / "service.env").write_text("SECRET=x\n")
            (private / ".refresh.lock").write_text("pid=1\n")
            (private / "logs").mkdir()
            (private / "logs" / "refresh.log").write_text("log\n")

            report = archive_private_artifacts(private, keep_days=2, as_of=date(2026, 6, 15))

            with tarfile.open(report["archive"]) as bundle:
                names = bundle.getnames()
            self.assertEqual(names, ["forecasts.jsonl", "snapshot.json"])
            self.assertEqual((private / "forecasts.jsonl").read_text(), "failed forecast\n")

    def test_archive_prunes_only_expired_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            archives = private / "archives"
            archives.mkdir(parents=True)
            (private / "snapshot.json").write_text("{}")
            old = archives / "stock-investor-private-2026-06-10.tar.gz"
            recent = archives / "stock-investor-private-2026-06-14.tar.gz"
            unrelated = archives / "keep-me.tar.gz"
            old.write_text("old")
            recent.write_text("recent")
            unrelated.write_text("unrelated")

            report = archive_private_artifacts(private, keep_days=2, as_of=date(2026, 6, 15))

            self.assertEqual(report["removed_archives"], [old.name])
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(unrelated.exists())

    def test_archive_refuses_non_private_source(self):
        with self.assertRaisesRegex(ValueError, "private directory"):
            archive_private_artifacts("/tmp/public")


if __name__ == "__main__":
    unittest.main()
