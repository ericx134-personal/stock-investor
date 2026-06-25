#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
TEMPLATE_DIR="$PROJECT_ROOT/scripts/macos"
AGENT_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"

mkdir -p "$AGENT_DIR" "$PROJECT_ROOT/data/private/logs"

install_agent() {
  local name="$1"
  local template="$TEMPLATE_DIR/stock-investor-$name.plist.in"
  local target="$AGENT_DIR/com.ericx.stock-investor.$name.plist"

  sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$template" > "$target"
  plutil -lint "$target"
  launchctl bootout "$DOMAIN/com.ericx.stock-investor.$name" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$target"
  launchctl enable "$DOMAIN/com.ericx.stock-investor.$name"
  launchctl kickstart -k "$DOMAIN/com.ericx.stock-investor.$name"
}

install_agent web
install_agent refresh

echo "Installed persistent dashboard: http://127.0.0.1:8765/"
echo "Source repo: $PROJECT_ROOT"
echo "Refresh config: $PROJECT_ROOT/data/private/service.env"
echo "Logs: $PROJECT_ROOT/data/private/logs/"
