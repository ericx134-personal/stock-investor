#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

CONFIG="$PROJECT_ROOT/data/private/service.env"
PRICES="$PROJECT_ROOT/data/private/robinhood-prices.csv"
TEMP_PRICES="$PROJECT_ROOT/data/private/.market-prices.$$.csv"

cleanup() {
  rm -f "$TEMP_PRICES"
}
trap cleanup EXIT

if [[ -f "$CONFIG" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG"
  set +a
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting scheduled market refresh"

if [[ -n "${APCA_API_KEY_ID:-}" && -n "${APCA_API_SECRET_KEY:-}" ]]; then
  START_DATE="$(date -v-730d +%Y-%m-%d)"
  END_DATE="$(date -v+1d +%Y-%m-%d)"
  PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli fetch-alpaca \
    portfolio/positions.csv "$TEMP_PRICES" \
    --start "$START_DATE" --end "$END_DATE" --feed "${ALPACA_FEED:-iex}" \
    --extra-symbol SPY
  mv "$TEMP_PRICES" "$PRICES"
  PRICE_SOURCE="Alpaca Market Data API (${ALPACA_FEED:-iex}, adjusted)"
  PRICE_ADJUSTMENT="all"
else
  echo "market fetch skipped: configure APCA_API_KEY_ID and APCA_API_SECRET_KEY in $CONFIG" >&2
  PRICE_SOURCE="Robinhood MCP read-only export"
  PRICE_ADJUSTMENT="unknown"
fi

PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli refresh \
  portfolio/positions.csv "$PRICES" data/private \
  --model-version decision-support-v3 \
  --account-summary portfolio/robinhood-summary.json \
  --baseline-snapshot data/private/model-v1-snapshot.json \
  --benchmark SPY \
  --price-source "$PRICE_SOURCE" \
  --price-adjustment "$PRICE_ADJUSTMENT" \
  --production-safe

PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli archive-private \
  data/private --keep-days "${ARCHIVE_KEEP_DAYS:-30}"
PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli verify-private-archive \
  "data/private/archives/stock-investor-private-$(date +%F).tar.gz"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scheduled market refresh complete"
