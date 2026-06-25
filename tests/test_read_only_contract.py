import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = sorted((ROOT / "src").rglob("*.py")) + sorted(
    (ROOT / "scripts").rglob("*.sh")
)
ALLOWED_READ_ONLY_HTTP_POSTS = {
    "snaptrade.py": {
        "/snapTrade/registerUser",
        "/snapTrade/login",
    }
}
FORBIDDEN_BROKERAGE_WRITES = re.compile(
    r"\b("
    r"place_(equity|option|crypto|futures)_order|"
    r"review_(equity|option|crypto|futures)_order|"
    r"cancel_(equity|option|crypto|futures)_order|"
    r"replace_(equity|option|crypto|futures)_order|"
    r"add_(option_)?to_watchlist|remove_(option_)?from_watchlist|"
    r"create_watchlist|update_watchlist|follow_watchlist|unfollow_watchlist"
    r")\b",
    re.IGNORECASE,
)


class ReadOnlyContractTests(unittest.TestCase):
    def test_runtime_contains_no_brokerage_write_action(self):
        violations = []
        for path in RUNTIME_FILES:
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if FORBIDDEN_BROKERAGE_WRITES.search(line):
                    violations.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(violations, [], f"brokerage write actions found: {violations}")

    def test_python_runtime_contains_no_http_write_request(self):
        violations = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "method":
                        continue
                    if (
                        isinstance(keyword.value, ast.Constant)
                        and str(keyword.value.value).upper()
                        in {"POST", "PUT", "PATCH", "DELETE"}
                    ):
                        if _is_allowed_read_only_auth_post(path, node):
                            continue
                        violations.append(
                            f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}"
                        )
                if _is_forbidden_snaptrade_post(path, node):
                    violations.append(
                        f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}"
                    )
        self.assertEqual(violations, [], f"HTTP write requests found: {violations}")

    def test_market_refresh_uses_moomoo_first_with_no_credential_fallback(self):
        script = (ROOT / "scripts" / "run_market_refresh.sh").read_text()
        cli = (ROOT / "src" / "stock_investor" / "cli.py").read_text()
        self.assertIn('MARKET_DATA_PROVIDER_ORDER="${MARKET_DATA_PROVIDER_ORDER:-moomoo,yahoo}"', script)
        self.assertIn("fetch-moomoo", script)
        self.assertIn("fetch-yahoo", script)
        self.assertIn("write_progress 35", script)
        self.assertIn("write_progress 100", script)
        self.assertIn(
            'START_DATE="${ACCOUNT_HISTORY_START_DATE:-${YAHOO_START_DATE:-}}"',
            script,
        )
        self.assertIn('START_DATE="2017-01-01"', script)
        self.assertIn('DEFAULT_ACCOUNT_HISTORY_START_DATE = "2017-01-01"', cli)
        self.assertIn('os.environ.get("ACCOUNT_HISTORY_START_DATE")', cli)
        self.assertIn('yahoo_parser.add_argument("--start", default=_default_yahoo_start())', cli)
        self.assertIn('"fetch-moomoo"', cli)
        self.assertIn('"fetch-moomoo-quotes"', cli)
        launchd = (ROOT / "scripts" / "macos" / "stock-investor-refresh.plist.in").read_text()
        self.assertIn("<key>StartCalendarInterval</key>", launchd)
        self.assertIn("<integer>6</integer>", launchd)
        self.assertIn("<integer>35</integer>", launchd)
        self.assertIn("<integer>13</integer>", launchd)
        self.assertIn("<integer>10</integer>", launchd)
        self.assertNotIn("<key>StartInterval</key>", launchd)
        self.assertNotIn("1970-01-01", script)
        self.assertNotIn("1970-01-01", cli)
        self.assertNotIn("ENABLE_ALPACA_MARKET_DATA", script)
        self.assertNotIn("APCA_API_KEY_ID", script)
        self.assertNotIn("APCA_API_SECRET_KEY", script)
        self.assertNotIn("APCA_API_KEY_ID", cli)
        self.assertNotIn("APCA_API_SECRET_KEY", cli)
        self.assertNotIn("fetch-alpaca", script)
        self.assertNotIn("fetch-alpaca", cli)

    def test_local_services_use_repo_as_single_source_of_truth(self):
        service_files = {
            "run_web_server": ROOT / "scripts" / "run_web_server.sh",
            "run_market_refresh": ROOT / "scripts" / "run_market_refresh.sh",
            "install_macos_services": ROOT / "scripts" / "install_macos_services.sh",
            "web_server": ROOT / "src" / "stock_investor" / "web_server.py",
            "dashboard": ROOT / "src" / "stock_investor" / "dashboard.py",
        }
        combined = "\n".join(path.read_text() for path in service_files.values())
        self.assertNotIn("sync_runtime", combined)
        self.assertNotIn("--synced", combined)
        self.assertNotIn("STOCK_INVESTOR_RUNTIME_ROOT", combined)
        self.assertNotIn("STOCK_INVESTOR_SKIP_RUNTIME_SYNC", combined)
        self.assertNotIn("Application Support/stock-investor", combined)
        self.assertFalse((ROOT / "scripts" / "sync_runtime.sh").exists())


def _is_allowed_read_only_auth_post(path: Path, node: ast.Call) -> bool:
    if path.name != "snaptrade.py":
        return False
    allowed = ALLOWED_READ_ONLY_HTTP_POSTS.get(path.name, set())
    return any(
        isinstance(argument, ast.Constant) and argument.value in allowed
        for argument in node.args
    )


def _is_forbidden_snaptrade_post(path: Path, node: ast.Call) -> bool:
    if path.name != "snaptrade.py":
        return False
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "_request":
        return False
    if not node.args:
        return False
    method = node.args[0]
    if not (isinstance(method, ast.Constant) and method.value == "POST"):
        return False
    for argument in node.args[1:]:
        if isinstance(argument, ast.Constant):
            return argument.value not in ALLOWED_READ_ONLY_HTTP_POSTS[path.name]
    return True


if __name__ == "__main__":
    unittest.main()
