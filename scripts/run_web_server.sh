#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
DEFAULT_CODEX_PYTHON="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
PYTHON_BIN="${PYTHON_BIN:-}"
WEB_BIND="${STOCK_INVESTOR_WEB_BIND:-127.0.0.1}"
WEB_PORT="${STOCK_INVESTOR_WEB_PORT:-8765}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$DEFAULT_CODEX_PYTHON" ]]; then
    PYTHON_BIN="$DEFAULT_CODEX_PYTHON"
  else
    PYTHON_BIN="/usr/bin/python3"
  fi
fi

PYTHONPATH="$PROJECT_ROOT/src" exec "$PYTHON_BIN" -m stock_investor.web_server \
  --port "$WEB_PORT" --bind "$WEB_BIND" --directory "$PROJECT_ROOT"
