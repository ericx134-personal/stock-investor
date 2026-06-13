import json
import tempfile
import unittest
from pathlib import Path

from stock_investor.filings import extract_recent_filings, update_filing_state


def submissions(accessions, forms=None, items=None):
    return {
        "filings": {
            "recent": {
                "accessionNumber": accessions,
                "form": (forms or ["8-K", "4"])[: len(accessions)],
                "filingDate": ["2026-06-01", "2026-05-20"][: len(accessions)],
                "primaryDocument": ["event.htm", "ownership.xml"][: len(accessions)],
                "items": (items or ["2.02,9.01", ""])[: len(accessions)],
            }
        }
    }


class FilingTests(unittest.TestCase):
    def test_extract_filters_forms_and_builds_sec_url(self):
        events = extract_recent_filings(
            "ABC", "1234", submissions(["0000001234-26-000001", "0000001234-26-000002"])
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].form, "8-K")
        self.assertEqual(events[0].items, ("2.02", "9.01"))
        self.assertIn("EARNINGS_RELEASE", events[0].event_categories)
        self.assertEqual(events[0].importance, "MEDIUM")
        self.assertIn("/1234/000000123426000001/event.htm", events[0].url)

    def test_high_importance_8k_item_is_classified(self):
        event = extract_recent_filings(
            "ABC",
            "1234",
            submissions(
                ["0000001234-26-000001"],
                forms=["8-K"],
                items=["1.05,8.01"],
            ),
        )[0]
        self.assertEqual(event.importance, "HIGH")
        self.assertIn("MATERIAL_CYBERSECURITY_INCIDENT", event.event_categories)

    def test_periodic_report_is_classified_without_items(self):
        event = extract_recent_filings(
            "ABC",
            "1234",
            submissions(
                ["0000001234-26-000001"],
                forms=["10-Q"],
                items=[""],
            ),
        )[0]
        self.assertEqual(event.event_categories, ("PERIODIC_FINANCIAL_REPORT",))
        self.assertEqual(event.importance, "MEDIUM")

    def test_first_state_run_baselines_then_returns_only_new_filings(self):
        initial = extract_recent_filings(
            "ABC", "1234", submissions(["0000001234-26-000001"])
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filings-state.json"
            self.assertEqual(update_filing_state(initial, path), [])
            newer = initial + [
                initial[0].__class__(
                    "ABC",
                    "0000001234",
                    "0000001234-26-000003",
                    "10-Q",
                    "2026-06-10",
                    "quarter.htm",
                    "https://example.test/quarter.htm",
                )
            ]
            unseen = update_filing_state(newer, path)
            state = json.loads(path.read_text())
        self.assertEqual([event.form for event in unseen], ["10-Q"])
        self.assertEqual(len(state["seen_accessions"]), 2)


if __name__ == "__main__":
    unittest.main()
