import json
import tempfile
import unittest
from pathlib import Path

from stock_investor.providers.moomoo import (
    MoomooProviderError,
    fetch_moomoo_watchlists,
    write_moomoo_watchlists,
)


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orientation):
        if orientation != "records":
            raise ValueError(f"unexpected orientation: {orientation}")
        return self.rows


class FakeContext:
    def __init__(self):
        self.closed = False
        self.group_calls = 0
        self.security_calls = []

    def get_user_security_group(self):
        self.group_calls += 1
        return 0, FakeTable(
            [
                {"group_name": "Robinhood"},
                {"group_name": "401k"},
                {"group_name": "Robinhood"},
            ]
        )

    def get_user_security(self, group_name):
        self.security_calls.append(group_name)
        rows = {
            "Robinhood": [
                {"code": "US.HOOD", "name": "Robinhood Markets"},
                {"code": "US.AFRM", "name": "Affirm"},
            ],
            "401k": [
                {"code": "US.FXAIX", "name": "Fidelity 500 Index"},
                {"code": "HK.00700", "name": "Tencent"},
            ],
        }
        return 0, FakeTable(rows[group_name])

    def close(self):
        self.closed = True


class FakeSdk:
    RET_OK = 0

    def __init__(self, context):
        self.context = context

    def OpenQuoteContext(self, host, port):
        self.host = host
        self.port = port
        return self.context


class MoomooProviderTests(unittest.TestCase):
    def test_fetch_discovers_groups_and_normalizes_symbols(self):
        context = FakeContext()
        sdk = FakeSdk(context)

        payload = fetch_moomoo_watchlists(sdk=sdk)

        self.assertTrue(context.closed)
        self.assertEqual(context.group_calls, 1)
        self.assertEqual(context.security_calls, ["Robinhood", "401k"])
        self.assertEqual(payload["source"], "moomoo-opend")
        self.assertEqual(payload["group_count"], 2)
        self.assertEqual(payload["unique_symbols"], ["00700", "AFRM", "FXAIX", "HOOD"])
        hood = next(item for item in payload["items"] if item["symbol"] == "HOOD")
        self.assertEqual(hood["market"], "US")
        self.assertEqual(hood["name"], "Robinhood Markets")

    def test_explicit_groups_skip_group_discovery(self):
        context = FakeContext()
        sdk = FakeSdk(context)

        payload = fetch_moomoo_watchlists(group_names=("Robinhood",), sdk=sdk)

        self.assertEqual(context.group_calls, 0)
        self.assertEqual(context.security_calls, ["Robinhood"])
        self.assertEqual(payload["unique_symbols"], ["AFRM", "HOOD"])

    def test_non_ok_response_is_reported(self):
        class BadContext(FakeContext):
            def get_user_security(self, group_name):
                return -1, "not logged in"

        with self.assertRaisesRegex(MoomooProviderError, "not logged in"):
            fetch_moomoo_watchlists(
                group_names=("Robinhood",),
                sdk=FakeSdk(BadContext()),
            )

    def test_write_payload(self):
        payload = {"schema_version": 1, "items": [{"symbol": "HOOD"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brokers" / "moomoo-watchlists.json"
            write_moomoo_watchlists(payload, path)
            loaded = json.loads(path.read_text())
        self.assertEqual(loaded, payload)


if __name__ == "__main__":
    unittest.main()
