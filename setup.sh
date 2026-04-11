#!/usr/bin/env bash
# setup.sh — Bootstrap Copilot CLI configuration from this repo
set -e

COPILOT_DIR="$HOME/.copilot"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🤖 Setting up Copilot CLI config from $REPO_DIR"

# Create directories
mkdir -p "$COPILOT_DIR/agents" "$COPILOT_DIR/skills" "$COPILOT_DIR/scripts"

# Copy agents
echo "📋 Installing agents..."
cp "$REPO_DIR/agents/"*.agent.md "$COPILOT_DIR/agents/"

# Copy skills
echo "🧠 Installing skills..."
cp -r "$REPO_DIR/skills/." "$COPILOT_DIR/skills/"

# Copy scripts
echo "📜 Installing scripts..."
cp "$REPO_DIR/scripts/summarize-session.py" "$COPILOT_DIR/scripts/"

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

echo ""
echo "✅ Done! Next steps:"
echo "  1. Fill in secrets in ~/.copilot/mcp-config.json"
echo "  2. Also set NOTION_TOKEN in ~/.copilot/scripts/summarize-session.py"
echo "  3. Add the copilot() zsh wrapper to ~/.zshrc (see README.md)"
