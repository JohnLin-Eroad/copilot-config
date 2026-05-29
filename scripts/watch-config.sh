#!/bin/bash
# watch-config.sh — File watcher for Copilot config auto-sync
# Monitors ~/.copilot config files and pushes changes to GitHub whenever they change.
# Runs as a macOS LaunchAgent (com.johnlin.copilot-config-sync).

COPILOT_DIR="$HOME/.copilot"
SESSIONS_DIR="$HOME/copilot-sessions"
SYNC_SCRIPT="$COPILOT_DIR/scripts/sync-config.py"
FSWATCH="/opt/homebrew/bin/fswatch"

echo "[$(date)] 👀 Watching Copilot config and sessions for changes..."

# --latency 2: batch all events within a 2-second window (natural debounce)
# -o: output one line per batch (event count), not per-file paths
"$FSWATCH" --latency 2 -o \
    "$COPILOT_DIR/agents" \
    "$COPILOT_DIR/skills" \
    "$COPILOT_DIR/scripts" \
    "$COPILOT_DIR/mcp-config.json" \
    "$SESSIONS_DIR" | while read -r; do
    echo "[$(date)] 🔄 Change detected — syncing..."
    python3 "$SYNC_SCRIPT" && echo "[$(date)] ✅ Config sync complete" || echo "[$(date)] ⚠️  Config sync failed"
    # Push any committed sessions to GitHub
    git -C "$SESSIONS_DIR" push --quiet 2>/dev/null && echo "[$(date)] ✅ Sessions pushed" || true
done
