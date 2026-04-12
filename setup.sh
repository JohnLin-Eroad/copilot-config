#!/usr/bin/env bash
# setup.sh — Bootstrap Copilot CLI configuration from this repo
set -e

COPILOT_DIR="$HOME/.copilot"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🤖 Setting up Copilot CLI config from $REPO_DIR"

# Create directories
mkdir -p "$COPILOT_DIR/agents" "$COPILOT_DIR/skills" "$COPILOT_DIR/scripts" "$COPILOT_DIR/logs"

# Copy agents
echo "📋 Installing agents..."
cp "$REPO_DIR/agents/"*.agent.md "$COPILOT_DIR/agents/"

# Copy skills
echo "🧠 Installing skills..."
cp -r "$REPO_DIR/skills/." "$COPILOT_DIR/skills/"

# Copy hooks
echo "🔒 Installing security hooks..."
mkdir -p "$COPILOT_DIR/hooks"
cp "$REPO_DIR/hooks/security-check.sh" "$COPILOT_DIR/hooks/"
chmod +x "$COPILOT_DIR/hooks/security-check.sh"

# Copy scripts
echo "📜 Installing scripts..."
cp "$REPO_DIR/scripts/summarize-session.py" "$COPILOT_DIR/scripts/"
cp "$REPO_DIR/scripts/sync-config.py" "$COPILOT_DIR/scripts/"
cp "$REPO_DIR/scripts/watch-config.sh" "$COPILOT_DIR/scripts/"
cp "$REPO_DIR/scripts/add-learning.sh" "$COPILOT_DIR/scripts/"
chmod +x "$COPILOT_DIR/scripts/watch-config.sh"
chmod +x "$COPILOT_DIR/scripts/add-learning.sh"

# Copy global agent instructions
echo "📝 Installing global agent instructions..."
cp "$REPO_DIR/copilot-instructions.md" "$COPILOT_DIR/copilot-instructions.md"

# Seed global learnings (only if not already present)
if [ ! -f "$COPILOT_DIR/learnings.md" ]; then
  echo "📚 Installing global learnings seed..."
  cp "$REPO_DIR/learnings.md" "$COPILOT_DIR/learnings.md"
else
  echo "📚 learnings.md already exists — skipping (preserving live entries)"
fi

# MCP config
if [ -f "$COPILOT_DIR/mcp-config.json" ]; then
  echo "⚠️  mcp-config.json already exists — skipping (edit manually or back up first)"
else
  cp "$REPO_DIR/mcp-config.json" "$COPILOT_DIR/mcp-config.json"
  echo "⚠️  mcp-config.json copied — replace all YOUR_* placeholders with real values:"
  echo "    - YOUR_NOTION_TOKEN"
  echo "    - YOUR_FIGMA_ACCESS_TOKEN"
  echo "    - YOUR_TENANT_ID (Microsoft 365)"
fi

# Install and start the config-sync LaunchAgent (macOS only)
PLIST_SRC="$REPO_DIR/com.johnlin.copilot-config-sync.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.johnlin.copilot-config-sync.plist"
if [[ "$(uname)" == "Darwin" ]] && [ -f "$PLIST_SRC" ]; then
  echo "🔍 Installing config-sync file watcher..."
  cp "$PLIST_SRC" "$PLIST_DST"
  # Unload first in case it's already loaded, then reload
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  launchctl load "$PLIST_DST"
  echo "✅ File watcher LaunchAgent installed and started."
  echo "   Logs: ~/.copilot/logs/watch-config.log"
fi

echo ""
echo "✅ Done! Next steps:"
echo "  1. Fill in secrets in ~/.copilot/mcp-config.json"
echo "  2. Also set NOTION_TOKEN in ~/.copilot/scripts/summarize-session.py"
echo "  3. Add the copilot() zsh wrapper to ~/.zshrc (see README.md)"
echo "  4. Ensure fswatch is installed: brew install fswatch"
