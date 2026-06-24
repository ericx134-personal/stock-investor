#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_ROOT_FILE="$PROJECT_ROOT/.source-root"

if [[ "${1:-}" != "--synced" && -f "$SOURCE_ROOT_FILE" ]]; then
  if ! "$PROJECT_ROOT/scripts/sync_runtime.sh"; then
    echo "warning: runtime sync failed; refreshing with existing runtime copy" >&2
  fi
  exec "$PROJECT_ROOT/scripts/run_market_refresh.sh" --synced
fi

cd "$PROJECT_ROOT"

CONFIG="$PROJECT_ROOT/data/private/service.env"
PRICES="$PROJECT_ROOT/data/private/robinhood-prices.csv"
TEMP_PRICES="$PROJECT_ROOT/data/private/.market-prices.$$.csv"
LATEST_QUOTES="$PROJECT_ROOT/data/private/latest-quotes.json"
TEMP_QUOTES="$PROJECT_ROOT/data/private/.latest-quotes.$$.json"

cleanup() {
  rm -f "$TEMP_PRICES"
  rm -f "$TEMP_QUOTES"
}
trap cleanup EXIT

if [[ -f "$CONFIG" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG"
  set +a
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting scheduled market refresh"

echo "Using Yahoo Finance chart data (no credentials)" >&2
START_DATE="${ACCOUNT_HISTORY_START_DATE:-${YAHOO_START_DATE:-}}"
if [[ -z "$START_DATE" ]]; then
  START_DATE="2017-01-01"
fi
END_DATE="$(date -v+1d +%Y-%m-%d)"
PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli fetch-yahoo \
  portfolio/positions.csv "$TEMP_PRICES" \
  --start "$START_DATE" --end "$END_DATE" \
  --extra-symbol SPY \
  --merge-existing "$PRICES"
mv "$TEMP_PRICES" "$PRICES"
PRICE_SOURCE="Yahoo Finance chart fallback"
PRICE_ADJUSTMENT="unknown"

PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli fetch-yahoo-quotes \
  portfolio/positions.csv "$TEMP_QUOTES" \
  --extra-symbol SPY
mv "$TEMP_QUOTES" "$LATEST_QUOTES"

PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli refresh \
  portfolio/positions.csv "$PRICES" data/private \
  --model-version decision-support-v3 \
  --account-summary portfolio/robinhood-summary.json \
  --baseline-snapshot data/private/model-v1-snapshot.json \
  --benchmark SPY \
  --price-source "$PRICE_SOURCE" \
  --latest-quotes "$LATEST_QUOTES" \
  --price-adjustment "$PRICE_ADJUSTMENT" \
  --production-safe

PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli archive-private \
  data/private --keep-days "${ARCHIVE_KEEP_DAYS:-30}"
PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli verify-private-archive \
  "data/private/archives/stock-investor-private-$(date +%F).tar.gz"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scheduled market refresh complete"
