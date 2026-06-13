import unittest

from stock_investor.providers.sec import (
    fetch_company_facts,
    fetch_submissions,
    fetch_ticker_ciks,
)


class SecTests(unittest.TestCase):
    def test_fetch_uses_padded_cik_and_identifying_user_agent(self):
        calls = []

        def transport(url, headers):
            calls.append((url, headers))
            return {"ok": True}

        result = fetch_company_facts("1234", "stock-investor owner@example.com", transport)
        self.assertEqual(result, {"ok": True})
        self.assertTrue(calls[0][0].endswith("CIK0000001234.json"))
        self.assertEqual(
            calls[0][1]["User-Agent"], "stock-investor owner@example.com"
        )
        self.assertNotIn("Host", calls[0][1])

    def test_fetch_requires_identifying_user_agent(self):
        with self.assertRaisesRegex(ValueError, "include an email"):
            fetch_company_facts("1234", "stock-investor")

    def test_fetch_ticker_ciks_normalizes_mapping(self):
        def transport(url, headers):
            return {"0": {"ticker": "aapl", "cik_str": 320193}}

        mapping = fetch_ticker_ciks("stock-investor owner@example.com", transport)
        self.assertEqual(mapping, {"AAPL": "0000320193"})

    def test_fetch_submissions_uses_official_endpoint(self):
        calls = []

        def transport(url, headers):
            calls.append(url)
            return {}

        fetch_submissions("1234", "stock-investor owner@example.com", transport)
        self.assertTrue(calls[0].endswith("/submissions/CIK0000001234.json"))


if __name__ == "__main__":
    unittest.main()
