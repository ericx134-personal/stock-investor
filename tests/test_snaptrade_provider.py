import base64
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_investor.providers.snaptrade import (
    SnapTradeClient,
    SnapTradeCredentials,
    build_snaptrade_account_summary,
    compute_request_signature,
    fetch_snaptrade_snapshot,
    load_snaptrade_credentials,
    write_snaptrade_snapshot,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class FakeOpener:
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        url = request.full_url
        if "/snapTrade/registerUser?" in url:
            return FakeResponse({"userId": "eric-local", "userSecret": "secret"})
        if "/snapTrade/login?" in url:
            return FakeResponse({"redirectURI": "https://app.snaptrade.test/connect"})
        if "/accounts?" in url:
            return FakeResponse(
                [
                    {
                        "id": "acct-1",
                        "brokerage_authorization": "auth-1",
                        "name": "Fidelity 401k",
                        "number": "123456789",
                        "institution_name": "Fidelity",
                        "sync_status": "SYNCED",
                        "balance": {"total": 1000},
                    }
                ]
            )
        if "/accounts/acct-1/balances?" in url:
            return FakeResponse(
                [{"currency": {"code": "USD"}, "cash": 50, "buying_power": 75}]
            )
        if "/accounts/acct-1/positions/all?" in url:
            return FakeResponse(
                {
                    "results": [
                        {
                            "instrument": {
                                "kind": "stock",
                                "symbol": "aapl",
                                "description": "Apple Inc.",
                                "currency": "USD",
                                "exchange": "XNAS",
                            },
                            "units": 3,
                            "price": 200,
                            "market_value": 600,
                            "average_purchase_price": 150,
                        },
                        {
                            "instrument": {
                                "kind": "mutualfund",
                                "raw_symbol": "FXAIX",
                                "description": "Fidelity 500 Index",
                            },
                            "quantity": "2.5",
                            "marketValue": "500.50",
                        },
                    ]
                }
            )
        if "/accounts/acct-1/balanceHistory?" in url:
            return FakeResponse(
                {
                    "currency": "USD",
                    "history": [
                        {"date": "2026-06-23", "total_value": "900.00"},
                        {"date": "2026-06-24", "total_value": "1000.00"},
                    ],
                }
            )
        raise AssertionError(f"unexpected URL: {url}")


def credentials():
    return SnapTradeCredentials(
        client_id="CID",
        consumer_key="KEY",
        user_id="eric-local",
        user_secret="user-secret",
        base_url="https://unit.test/api/v1",
    )


class SnapTradeProviderTests(unittest.TestCase):
    def test_compute_request_signature_uses_snaptrade_canonical_payload(self):
        path = "/snapTrade/registerUser?clientId=CID&timestamp=123"
        body = {"userId": "eric-local"}

        signature = compute_request_signature(path, "KEY", body)

        canonical = (
            '{"content":{"userId":"eric-local"},'
            '"path":"/api/v1/snapTrade/registerUser",'
            '"query":"clientId=CID&timestamp=123"}'
        )
        expected = base64.b64encode(
            hmac.new(b"KEY", canonical.encode(), hashlib.sha256).digest()
        ).decode()
        self.assertEqual(signature, expected)

    def test_register_and_login_generate_signed_read_only_requests(self):
        opener = FakeOpener()
        client = SnapTradeClient(credentials(), opener=opener, clock=lambda: 123)

        registered = client.register_user("eric-local")
        login = client.login_url(
            user_id="eric-local",
            user_secret="user-secret",
            broker="FIDELITY",
        )

        self.assertEqual(registered["userSecret"], "secret")
        self.assertEqual(login["redirectURI"], "https://app.snaptrade.test/connect")
        self.assertIn("Signature", dict(opener.requests[0].headers))
        self.assertIn("clientId=CID&timestamp=123", opener.requests[0].full_url)
        login_body = json.loads(opener.requests[1].data.decode())
        self.assertEqual(login_body["connectionType"], "read")
        self.assertEqual(login_body["broker"], "FIDELITY")

    def test_personal_login_omits_user_identity_query(self):
        opener = FakeOpener()
        client = SnapTradeClient(credentials(), opener=opener, clock=lambda: 123)

        login = client.login_url(broker="FIDELITY")

        self.assertEqual(login["redirectURI"], "https://app.snaptrade.test/connect")
        self.assertIn("/snapTrade/login?clientId=CID&timestamp=123", opener.requests[0].full_url)
        self.assertNotIn("userId=", opener.requests[0].full_url)
        self.assertNotIn("userSecret=", opener.requests[0].full_url)

    def test_fetch_snapshot_masks_account_number_and_normalizes_positions(self):
        opener = FakeOpener()
        client = SnapTradeClient(credentials(), opener=opener, clock=lambda: 123)

        payload = fetch_snaptrade_snapshot(
            client,
            user_id="eric-local",
            user_secret="user-secret",
        )

        self.assertEqual(payload["source"], "snaptrade")
        self.assertEqual(payload["account_count"], 1)
        self.assertEqual(payload["position_count"], 2)
        self.assertEqual(payload["unique_symbols"], ["AAPL", "FXAIX"])
        account = payload["accounts"][0]
        self.assertEqual(account["account"]["number"], "***6789")
        self.assertEqual(account["balances"][0]["buying_power"], 75)
        self.assertEqual(account["positions"][0]["symbol"], "AAPL")
        self.assertEqual(account["positions"][0]["units"], 3.0)
        self.assertEqual(account["positions"][1]["market_value"], 500.5)

    def test_fetch_snapshot_can_include_account_balance_history(self):
        opener = FakeOpener()
        client = SnapTradeClient(credentials(), opener=opener, clock=lambda: 123)

        payload = fetch_snaptrade_snapshot(client, include_balance_history=True)

        account = payload["accounts"][0]
        self.assertEqual(account["balance_history"]["currency"], "USD")
        self.assertEqual(
            account["balance_history"]["history"][1]["total_value"],
            "1000.00",
        )
        self.assertTrue(
            any("/accounts/acct-1/balanceHistory?" in item.full_url for item in opener.requests)
        )

    def test_build_account_summary_filters_empty_accounts_and_institution(self):
        snapshot = {
            "captured_at": "2026-06-25T00:00:00+00:00",
            "accounts": [
                {
                    "account": {
                        "institution_name": "Robinhood",
                        "balance": {"total": {"amount": 0, "currency": "USD"}},
                    },
                    "balances": [{"cash": 0, "buying_power": 0}],
                    "positions": [],
                },
                {
                    "account": {
                        "institution_name": "Robinhood",
                        "balance": {"total": {"amount": 800, "currency": "USD"}},
                    },
                    "balances": [{"cash": -200, "buying_power": 100}],
                    "positions": [{"symbol": "ABC", "units": 10, "price": 100}],
                },
                {
                    "account": {
                        "institution_name": "Fidelity",
                        "balance": {"total": {"amount": 300, "currency": "USD"}},
                    },
                    "balances": [{"cash": 25, "buying_power": 25}],
                    "positions": [{"symbol": "XYZ", "units": 3, "price": 100}],
                },
            ],
        }

        summary = build_snaptrade_account_summary(
            snapshot,
            institution_name="Robinhood",
        )

        self.assertEqual(summary["account_count"], 1)
        self.assertEqual(summary["account_value"], 800)
        self.assertEqual(summary["cash"], -200)
        self.assertEqual(summary["margin_used"], 200)
        self.assertEqual(summary["buying_power"], 100)
        self.assertEqual(summary["holdings_value"], 1000)

    def test_fetch_personal_snapshot_omits_user_identity_query(self):
        opener = FakeOpener()
        client = SnapTradeClient(credentials(), opener=opener, clock=lambda: 123)

        payload = fetch_snaptrade_snapshot(client)

        self.assertEqual(payload["account_count"], 1)
        self.assertTrue(all("userSecret=" not in item.full_url for item in opener.requests))

    def test_write_snapshot(self):
        payload = {"schema_version": 1, "source": "snaptrade"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brokers" / "snaptrade.json"
            write_snaptrade_snapshot(payload, path)
            loaded = json.loads(path.read_text())
        self.assertEqual(loaded, payload)

    def test_load_credentials_reads_private_service_env(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / "service.env"
            env_path.write_text(
                "\n".join(
                    [
                        "SNAPTRADE_CLIENT_ID=file-client",
                        "SNAPTRADE_CONSUMER_KEY='file-key'",
                        "SNAPTRADE_USER_ID=test-user-id",
                        'SNAPTRADE_USER_SECRET="file-secret"',
                    ]
                )
            )
            with patch.dict("os.environ", {}, clear=True):
                loaded = load_snaptrade_credentials(require_user=True, env_path=env_path)

        self.assertEqual(loaded.client_id, "file-client")
        self.assertEqual(loaded.consumer_key, "file-key")
        self.assertEqual(loaded.user_id, "test-user-id")
        self.assertEqual(loaded.user_secret, "file-secret")

    def test_environment_overrides_private_service_env(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / "service.env"
            env_path.write_text(
                "SNAPTRADE_CLIENT_ID=file-client\n"
                "SNAPTRADE_CONSUMER_KEY=file-key\n"
            )
            with patch.dict(
                "os.environ",
                {
                    "SNAPTRADE_CLIENT_ID": "env-client",
                    "SNAPTRADE_CONSUMER_KEY": "env-key",
                },
                clear=True,
            ):
                loaded = load_snaptrade_credentials(env_path=env_path)

        self.assertEqual(loaded.client_id, "env-client")
        self.assertEqual(loaded.consumer_key, "env-key")


if __name__ == "__main__":
    unittest.main()
