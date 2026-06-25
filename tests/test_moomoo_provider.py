import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_investor.providers.moomoo import (
    MoomooProviderError,
    fetch_moomoo_daily_bars,
    fetch_moomoo_latest_quotes,
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

    def request_history_kline(self, code, **kwargs):
        self.history_call = (code, kwargs)
        return 0, FakeTable(
            [
                {
                    "code": code,
                    "time_key": "2026-06-23 00:00:00",
                    "open": 90,
                    "close": 92,
                    "high": 93,
                    "low": 89,
                    "volume": 1000,
                },
                {
                    "code": code,
                    "time_key": "2026-06-24 00:00:00",
                    "open": 92,
                    "close": 94,
                    "high": 95,
                    "low": 91,
                    "volume": 1200,
                },
            ]
        ), None

    def get_market_snapshot(self, codes):
        self.snapshot_codes = codes
        return 0, FakeTable(
            [
                {
                    "code": code,
                    "last_price": 94,
                    "prev_close_price": 92,
                    "after_price": 95,
                    "update_time": "2026-06-24 20:00:00",
                }
                for code in codes
            ]
        )

    def close(self):
        self.closed = True


class FakeSdk:
    RET_OK = 0

    class KLType:
        K_DAY = "K_DAY"

    class AuType:
        QFQ = "QFQ"

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

        payload = fetch_moomoo_watchlists(sdk=sdk, check_connection=False)

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

        payload = fetch_moomoo_watchlists(
            group_names=("Robinhood",),
            sdk=sdk,
            check_connection=False,
        )

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
                check_connection=False,
            )

    def test_closed_opend_port_fails_before_context_creation(self):
        class ExplodingSdk:
            RET_OK = 0

            def OpenQuoteContext(self, host, port):
                raise AssertionError("OpenQuoteContext should not be created")

        with patch(
            "stock_investor.providers.moomoo.socket.create_connection",
            side_effect=OSError("connection refused"),
        ):
            with self.assertRaisesRegex(MoomooProviderError, "OpenD is not reachable"):
                fetch_moomoo_watchlists(
                    group_names=("Robinhood",),
                    sdk=ExplodingSdk(),
                )

    def test_high_frequency_response_retries_once(self):
        class RateLimitedContext(FakeContext):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            def get_user_security(self, group_name):
                self.attempts += 1
                if self.attempts == 1:
                    return -1, "Get Watchlist Groups request failed due to high frequency."
                return super().get_user_security(group_name)

        context = RateLimitedContext()
        with patch("stock_investor.providers.moomoo.time.sleep") as sleep:
            payload = fetch_moomoo_watchlists(
                group_names=("Robinhood",),
                sdk=FakeSdk(context),
                check_connection=False,
                high_frequency_retry_seconds=31,
            )

        sleep.assert_called_once_with(31)
        self.assertEqual(context.attempts, 2)
        self.assertEqual(payload["unique_symbols"], ["AFRM", "HOOD"])

    def test_write_payload(self):
        payload = {"schema_version": 1, "items": [{"symbol": "HOOD"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brokers" / "moomoo-watchlists.json"
            write_moomoo_watchlists(payload, path)
            loaded = json.loads(path.read_text())
        self.assertEqual(loaded, payload)

    def test_fetch_daily_bars_uses_opend_kline(self):
        context = FakeContext()

        payload = fetch_moomoo_daily_bars(
            ["hood"],
            "2026-06-01",
            "2026-06-24",
            sdk=FakeSdk(context),
            check_connection=False,
        )

        self.assertEqual(context.history_call[0], "US.HOOD")
        self.assertEqual(context.history_call[1]["ktype"], "K_DAY")
        self.assertEqual(context.history_call[1]["autype"], "QFQ")
        self.assertEqual([item.close for item in payload["HOOD"]], [92.0, 94.0])
        self.assertTrue(context.closed)

    def test_fetch_latest_quotes_uses_opend_snapshot(self):
        context = FakeContext()

        quotes = fetch_moomoo_latest_quotes(
            ["HOOD"],
            sdk=FakeSdk(context),
            check_connection=False,
        )

        self.assertEqual(context.snapshot_codes, ["US.HOOD"])
        self.assertEqual(quotes["HOOD"]["price"], 95.0)
        self.assertAlmostEqual(quotes["HOOD"]["today_return"], 95 / 92 - 1)
        self.assertEqual(quotes["HOOD"]["source"], "Moomoo OpenD market snapshot")

    def test_snapshot_batch_failure_falls_back_to_single_symbols(self):
        class PartialSnapshotContext(FakeContext):
            def get_market_snapshot(self, codes):
                if len(codes) > 1:
                    return -1, "Unknown stock. BAD"
                if codes == ["US.BAD"]:
                    return -1, "Unknown stock. BAD"
                return super().get_market_snapshot(codes)

        failures = []
        quotes = fetch_moomoo_latest_quotes(
            ["HOOD", "BAD"],
            sdk=FakeSdk(PartialSnapshotContext()),
            check_connection=False,
            on_failure=failures.append,
        )

        self.assertIn("HOOD", quotes)
        self.assertNotIn("BAD", quotes)
        self.assertEqual(failures[0].symbol, "BAD")


if __name__ == "__main__":
    unittest.main()
