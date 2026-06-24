#!/bin/bash
set -euo pipefail

SCRIPT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_ROOT="${STOCK_INVESTOR_RUNTIME_ROOT:-$HOME/Library/Application Support/stock-investor}"
SOURCE_ROOT="${STOCK_INVESTOR_SOURCE_ROOT:-}"
PRIVATE_MODE="none"

for arg in "$@"; do
  case "$arg" in
    --private-data)
      PRIVATE_MODE="always"
      ;;
    --private-data-if-empty)
      PRIVATE_MODE="if-empty"
      ;;
    *)
      echo "usage: scripts/sync_runtime.sh [--private-data|--private-data-if-empty]" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$SOURCE_ROOT" ]]; then
  if [[ -f "$SCRIPT_ROOT/.source-root" ]]; then
    SOURCE_ROOT="$(cat "$SCRIPT_ROOT/.source-root")"
  else
    SOURCE_ROOT="$SCRIPT_ROOT"
  fi
fi

[[ -d "$SOURCE_ROOT/src" && -d "$SOURCE_ROOT/scripts" ]] || exit 0
mkdir -p "$RUNTIME_ROOT/data/private/logs"
printf "%s\n" "$SOURCE_ROOT" > "$RUNTIME_ROOT/.source-root"

if [[ "$SOURCE_ROOT" == "$RUNTIME_ROOT" ]]; then
  exit 0
fi

rsync -a --delete "$SOURCE_ROOT/src/" "$RUNTIME_ROOT/src/"
rsync -a --delete "$SOURCE_ROOT/scripts/" "$RUNTIME_ROOT/scripts/"
rsync -a --delete "$SOURCE_ROOT/models/" "$RUNTIME_ROOT/models/"
rsync -a "$SOURCE_ROOT/web/" "$RUNTIME_ROOT/"
cp "$SOURCE_ROOT/pyproject.toml" "$RUNTIME_ROOT/pyproject.toml"

mkdir -p "$RUNTIME_ROOT/portfolio"
rsync -a --delete "$SOURCE_ROOT/portfolio/" "$RUNTIME_ROOT/portfolio/"

if [[ "$PRIVATE_MODE" == "always" ]] || {
  [[ "$PRIVATE_MODE" == "if-empty" ]] && [[ ! -f "$RUNTIME_ROOT/data/private/refresh-manifest.json" ]]
}; then
  rsync -a --exclude logs/ "$SOURCE_ROOT/data/private/" "$RUNTIME_ROOT/data/private/"
fi
