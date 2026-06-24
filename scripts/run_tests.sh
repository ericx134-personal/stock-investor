#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-/usr/bin/python3}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

LEVEL="${1:-L1}"
shift || true
LEVEL="$(printf '%s' "$LEVEL" | tr '[:lower:]' '[:upper:]')"

L1_TESTS=(
  tests.test_read_only_contract
  tests.test_snaptrade_provider
  tests.test_moomoo_provider
  tests.test_robinhood
  tests.test_robinhood_provider
  tests.test_data
  tests.test_yahoo
  tests.test_refresh
  tests.test_web_server
  tests.test_dashboard.DashboardTests.test_dashboard_write_mirrors_installed_runtime_copy
  tests.test_dashboard.DashboardTests.test_dashboard_adds_fidelity_tab_from_snaptrade_snapshot
  tests.test_dashboard.DashboardTests.test_dashboard_uses_latest_quote_overlay_for_front_page_price
  tests.test_dashboard.DashboardTests.test_dashboard_account_overview_uses_margin_summary_and_account_chart
  tests.test_dashboard.DashboardTests.test_dashboard_warns_but_keeps_stale_robinhood_account_view_visible
  tests.test_dashboard.DashboardTests.test_dashboard_prioritizes_and_escapes_alerts
)

L2_TESTS=(
  "${L1_TESTS[@]}"
  tests.test_monitor
  tests.test_diagnostics
  tests.test_evaluation
  tests.test_kline
  tests.test_model
  tests.test_risk
  tests.test_scoring
  tests.test_wave
)

case "$LEVEL" in
  L1)
    echo "Running L1 fast regression tests"
    exec "$PYTHON" -m unittest "${L1_TESTS[@]}" "$@"
    ;;
  L2)
    echo "Running L2 core regression tests"
    exec "$PYTHON" -m unittest "${L2_TESTS[@]}" "$@"
    ;;
  L3)
    echo "Running L3 full suite and public-safety check"
    "$PYTHON" -m unittest discover tests "$@"
    scripts/check_public_safety.sh
    ;;
  *)
    echo "usage: scripts/run_tests.sh [L1|L2|L3] [unittest args...]" >&2
    exit 2
    ;;
esac
