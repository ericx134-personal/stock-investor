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
PRICES="$PROJECT_ROOT/data/private/market-prices.csv"
TEMP_PRICES="$PROJECT_ROOT/data/private/.market-prices.$$.csv"
LATEST_QUOTES="$PROJECT_ROOT/data/private/latest-quotes.json"
TEMP_QUOTES="$PROJECT_ROOT/data/private/.latest-quotes.$$.json"

cleanup() {
  rm -f "$TEMP_PRICES"
  rm -f "$TEMP_QUOTES"
}
trap cleanup EXIT

write_progress() {
  local progress="$1"
  local message="$2"
  if [[ -n "${STOCK_INVESTOR_REFRESH_PROGRESS:-}" ]]; then
    mkdir -p "$(dirname "$STOCK_INVESTOR_REFRESH_PROGRESS")"
    printf '{"progress":%s,"message":"%s"}\n' "$progress" "$message" > "$STOCK_INVESTOR_REFRESH_PROGRESS"
  fi
}

if [[ -f "$CONFIG" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG"
  set +a
fi
ACCOUNT_SUMMARY="${ACCOUNT_SUMMARY_PATH:-portfolio/account-summary.json}"
PRIMARY_ACCOUNT_INSTITUTION="${PRIMARY_ACCOUNT_INSTITUTION:-Robinhood}"
MARKET_DATA_PROVIDER_ORDER="${MARKET_DATA_PROVIDER_ORDER:-moomoo,yahoo}"
MOOMOO_WATCHLISTS="${MOOMOO_WATCHLISTS_PATH:-data/private/brokers/moomoo-watchlists.json}"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting scheduled market refresh"
write_progress 5 "starting"
if [[ -n "${SNAPTRADE_CLIENT_ID:-}" && -n "${SNAPTRADE_CONSUMER_KEY:-}" ]]; then
  if PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli import-snaptrade-accounts \
    data/private/brokers/snaptrade-accounts.json \
    --account-summary-output "$ACCOUNT_SUMMARY" \
    --account-summary-institution "$PRIMARY_ACCOUNT_INSTITUTION" \
    --include-balance-history; then
    write_progress 15 "broker accounts updated"
  else
    echo "warning: SnapTrade account refresh failed; using previous account summary" >&2
  fi
fi
ACCOUNT_ARGS=()
if [[ -f "$ACCOUNT_SUMMARY" ]]; then
  ACCOUNT_ARGS=(--account-summary "$ACCOUNT_SUMMARY")
fi
MOOMOO_ARGS=()
if printf ',%s,' "$MARKET_DATA_PROVIDER_ORDER" | tr '[:upper:]' '[:lower:]' | grep -q ',moomoo,'; then
  if PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli import-moomoo-watchlist "$MOOMOO_WATCHLISTS"; then
    write_progress 22 "moomoo watchlists updated"
    MOOMOO_ARGS=(--moomoo-watchlists "$MOOMOO_WATCHLISTS")
  else
    echo "warning: Moomoo watchlist import failed; using previous watchlist snapshot if available" >&2
    if [[ -f "$MOOMOO_WATCHLISTS" ]]; then
      MOOMOO_ARGS=(--moomoo-watchlists "$MOOMOO_WATCHLISTS")
    fi
  fi
elif [[ -f "$MOOMOO_WATCHLISTS" ]]; then
  MOOMOO_ARGS=(--moomoo-watchlists "$MOOMOO_WATCHLISTS")
fi

START_DATE="${ACCOUNT_HISTORY_START_DATE:-${YAHOO_START_DATE:-}}"
if [[ -z "$START_DATE" ]]; then
  START_DATE="2017-01-01"
fi
END_DATE="$(date -v+1d +%Y-%m-%d)"

PRICE_SOURCE=""
PRICE_ADJUSTMENT="unknown"
IFS=',' read -r -a PROVIDERS <<< "$MARKET_DATA_PROVIDER_ORDER"
for PROVIDER in "${PROVIDERS[@]}"; do
  PROVIDER="$(printf '%s' "$PROVIDER" | tr '[:upper:]' '[:lower:]' | xargs)"
  if [[ "$PROVIDER" == "moomoo" ]]; then
    echo "Using Moomoo OpenD chart data" >&2
    if PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli fetch-moomoo \
      portfolio/positions.csv "$TEMP_PRICES" \
      --start "$START_DATE" --end "$END_DATE" \
      --extra-symbol SPY \
      --merge-existing "$PRICES"; then
      PRICE_SOURCE="Moomoo OpenD K-line"
      PRICE_ADJUSTMENT="all"
      break
    fi
    echo "Moomoo chart refresh failed; trying next provider" >&2
  elif [[ "$PROVIDER" == "yahoo" ]]; then
    echo "Using Yahoo Finance chart fallback (no credentials)" >&2
    if PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli fetch-yahoo \
      portfolio/positions.csv "$TEMP_PRICES" \
      --start "$START_DATE" --end "$END_DATE" \
      --extra-symbol SPY \
      --merge-existing "$PRICES"; then
      PRICE_SOURCE="Yahoo Finance chart fallback"
      PRICE_ADJUSTMENT="unknown"
      break
    fi
    echo "Yahoo chart refresh failed; trying next provider" >&2
  elif [[ -n "$PROVIDER" ]]; then
    echo "Unknown market data provider '$PROVIDER'; skipping" >&2
  fi
done
if [[ -z "$PRICE_SOURCE" ]]; then
  echo "No configured market data provider succeeded" >&2
  exit 1
fi
mv "$TEMP_PRICES" "$PRICES"
write_progress 35 "price history updated"

QUOTE_SOURCE=""
for PROVIDER in "${PROVIDERS[@]}"; do
  PROVIDER="$(printf '%s' "$PROVIDER" | tr '[:upper:]' '[:lower:]' | xargs)"
  if [[ "$PROVIDER" == "moomoo" ]]; then
    if PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli fetch-moomoo-quotes \
      portfolio/positions.csv "$TEMP_QUOTES" \
      --extra-symbol SPY; then
      QUOTE_SOURCE="Moomoo OpenD market snapshot"
      break
    fi
    echo "Moomoo quote refresh failed; trying next provider" >&2
  elif [[ "$PROVIDER" == "yahoo" ]]; then
    if PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli fetch-yahoo-quotes \
      portfolio/positions.csv "$TEMP_QUOTES" \
      --extra-symbol SPY; then
      QUOTE_SOURCE="Yahoo Finance quote fallback"
      break
    fi
    echo "Yahoo quote refresh failed; trying next provider" >&2
  fi
done
if [[ -z "$QUOTE_SOURCE" ]]; then
  echo "No configured quote provider succeeded" >&2
  exit 1
fi
mv "$TEMP_QUOTES" "$LATEST_QUOTES"
write_progress 55 "latest quotes updated"

PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli refresh \
  portfolio/positions.csv "$PRICES" data/private \
  --model-version decision-support-v3 \
  "${ACCOUNT_ARGS[@]}" \
  --baseline-snapshot data/private/model-v1-snapshot.json \
  --benchmark SPY \
  --price-source "$PRICE_SOURCE" \
  --latest-quotes "$LATEST_QUOTES" \
  --price-adjustment "$PRICE_ADJUSTMENT" \
  "${MOOMOO_ARGS[@]}" \
  --production-safe
write_progress 82 "dashboard rebuilt"

PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli archive-private \
  data/private --keep-days "${ARCHIVE_KEEP_DAYS:-30}"
write_progress 92 "archive written"
PYTHONPATH=src /usr/bin/python3 -m stock_investor.cli verify-private-archive \
  "data/private/archives/stock-investor-private-$(date +%F).tar.gz"
write_progress 100 "refresh complete"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scheduled market refresh complete"
