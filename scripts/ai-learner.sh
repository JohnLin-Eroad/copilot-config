#!/usr/bin/env bash
# ai-learner.sh — Weekly AI learning agent runner
# Invoked by: ~/Library/LaunchAgents/com.johnlin.ai-learner.plist
# Schedule: Every Sunday at 09:00

set -euo pipefail

LOG="/tmp/ai-learner.log"
exec >> "$LOG" 2>&1

echo ""
echo "========================================="
echo "AI Learner — $(date '+%Y-%m-%d %H:%M:%S')"
echo "WEEK: $(date +%Y-W%V)"
echo "========================================="

# Ensure Homebrew tools are on PATH (not available in launchd by default)
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Verify gh is authenticated
if ! gh auth status > /dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run 'gh auth login' first."
  exit 1
fi

# Verify vault exists
VAULT=~/Documents/AI-understandings
if [ ! -d "$VAULT" ]; then
  echo "ERROR: AI Understandings vault not found at $VAULT"
  exit 1
fi

# Trigger the ai-learner agent via Copilot CLI
exec /opt/homebrew/bin/copilot agent run ai-learner \
  --message "Run the weekly AI learning scan. Today is $(date +%Y-%m-%d), week $(date +%Y-W%V). Search HN, arXiv, GitHub Trending, and high-signal blogs for AI/LLM/agent developments from the past 7 days. Deduplicate against the existing vault, keep only genuinely new discoveries, and write the weekly note."
