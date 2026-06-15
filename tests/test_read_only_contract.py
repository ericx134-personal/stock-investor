import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = sorted((ROOT / "src").rglob("*.py")) + sorted(
    (ROOT / "scripts").rglob("*.sh")
)
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
                        violations.append(
                            f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}"
                        )
        self.assertEqual(violations, [], f"HTTP write requests found: {violations}")


if __name__ == "__main__":
    unittest.main()
