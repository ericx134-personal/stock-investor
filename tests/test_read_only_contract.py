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

    def test_market_refresh_uses_no_credential_provider_by_default(self):
        script = (ROOT / "scripts" / "run_market_refresh.sh").read_text()
        cli = (ROOT / "src" / "stock_investor" / "cli.py").read_text()
        self.assertIn("Using Yahoo Finance chart data (no credentials)", script)
        self.assertIn(
            'START_DATE="${ACCOUNT_HISTORY_START_DATE:-${YAHOO_START_DATE:-}}"',
            script,
        )
        self.assertIn('START_DATE="$(date -v-730d +%Y-%m-%d)"', script)
        self.assertIn('DEFAULT_YAHOO_LOOKBACK_DAYS = 730', cli)
        self.assertIn('os.environ.get("ACCOUNT_HISTORY_START_DATE")', cli)
        self.assertIn('yahoo_parser.add_argument("--start", default=_default_yahoo_start())', cli)
        self.assertNotIn("1970-01-01", script)
        self.assertNotIn("1970-01-01", cli)
        self.assertNotIn("ENABLE_ALPACA_MARKET_DATA", script)
        self.assertNotIn("APCA_API_KEY_ID", script)
        self.assertNotIn("APCA_API_SECRET_KEY", script)
        self.assertNotIn("APCA_API_KEY_ID", cli)
        self.assertNotIn("APCA_API_SECRET_KEY", cli)
        self.assertNotIn("fetch-alpaca", script)
        self.assertNotIn("fetch-alpaca", cli)


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
