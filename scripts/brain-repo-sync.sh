#!/usr/bin/env bash
# brain-repo-sync.sh — Nightly sync of eroad GitHub repos → local brain vault
# Invoked by: ~/Library/LaunchAgents/com.eroad.brain-repo-sync.plist

set -euo pipefail

LOG="/tmp/brain-repo-sync.log"
exec >> "$LOG" 2>&1

echo ""
echo "========================================="
echo "Brain Repo Sync — $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================="

# Ensure Homebrew tools are on PATH (not available in launchd by default)
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Verify gh is authenticated
if ! gh auth status > /dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run 'gh auth login' first."
  exit 1
fi

# Trigger the brain-repo-sync agent via Copilot CLI
/opt/homebrew/bin/copilot agent run brain-repo-sync \
  --message "Run the full nightly brain repo sync for all EROAD services. Today's date is $(date +%Y-%m-%d)."

# Push any changes the agent wrote back to GitHub
bash "$HOME/.copilot/scripts/brain-git-push.sh" "chore: nightly brain repo sync — $(date +%Y-%m-%d)"
