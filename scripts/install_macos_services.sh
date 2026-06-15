#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE_DIR="$PROJECT_ROOT/scripts/macos"
AGENT_DIR="$HOME/Library/LaunchAgents"
RUNTIME_ROOT="$HOME/Library/Application Support/stock-investor"
DOMAIN="gui/$(id -u)"

mkdir -p "$AGENT_DIR" "$RUNTIME_ROOT/data/private/logs"

# LaunchAgents cannot reliably read ~/Documents under macOS privacy controls.
# Keep a private operational copy in Application Support instead.
rsync -a "$PROJECT_ROOT/src/" "$RUNTIME_ROOT/src/"
rsync -a "$PROJECT_ROOT/scripts/" "$RUNTIME_ROOT/scripts/"
rsync -a "$PROJECT_ROOT/models/" "$RUNTIME_ROOT/models/"
cp "$PROJECT_ROOT/pyproject.toml" "$RUNTIME_ROOT/pyproject.toml"
mkdir -p "$RUNTIME_ROOT/portfolio"
rsync -a "$PROJECT_ROOT/portfolio/" "$RUNTIME_ROOT/portfolio/"
if [[ ! -f "$RUNTIME_ROOT/data/private/refresh-manifest.json" ]]; then
  rsync -a --exclude logs/ "$PROJECT_ROOT/data/private/" "$RUNTIME_ROOT/data/private/"
fi

install_agent() {
  local name="$1"
  local template="$TEMPLATE_DIR/stock-investor-$name.plist.in"
  local target="$AGENT_DIR/com.ericx.stock-investor.$name.plist"

  sed "s|__PROJECT_ROOT__|$RUNTIME_ROOT|g" "$template" > "$target"
  plutil -lint "$target"
  launchctl bootout "$DOMAIN/com.ericx.stock-investor.$name" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$target"
  launchctl enable "$DOMAIN/com.ericx.stock-investor.$name"
  launchctl kickstart -k "$DOMAIN/com.ericx.stock-investor.$name"
}

install_agent web
install_agent refresh

echo "Installed persistent dashboard: http://127.0.0.1:8765/data/private/dashboard-v3.html"
echo "Runtime copy: $RUNTIME_ROOT"
echo "Refresh credentials: $RUNTIME_ROOT/data/private/service.env"
echo "Logs: $RUNTIME_ROOT/data/private/logs/"
