#!/usr/bin/env bash
# weekly-branch.sh — Weekly experiment branch creator
# Invoked by: ~/Library/LaunchAgents/com.johnlin.weekly-experimenter.plist
# Schedule: Every Sunday at 10:00 (1 hour after ai-learner)

set -euo pipefail

LOG="/tmp/weekly-experimenter.log"
exec >> "$LOG" 2>&1

echo ""
echo "========================================="
echo "Weekly Experimenter — $(date '+%Y-%m-%d %H:%M:%S')"
echo "WEEK: $(date +%Y-W%V)"
echo "========================================="

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

WEEK=$(date +%Y-W%V)
VAULT=~/AI-understandings
WEEKLY_NOTE="$VAULT/10 - Weekly Learnings/$WEEK.md"

# Check the weekly note exists (ai-learner must have run first)
if [ ! -f "$WEEKLY_NOTE" ]; then
  echo "WARNING: Weekly note not found at $WEEKLY_NOTE"
  echo "ai-learner may not have run yet or produced no output. Skipping experimenter."
  exit 0
fi

if ! gh auth status > /dev/null 2>&1; then
  echo "ERROR: gh is not authenticated."
  exit 1
fi

exec /opt/homebrew/bin/copilot agent run weekly-experimenter \
  --message "Run the weekly experiment workflow for week $WEEK. The weekly learnings note is at $WEEKLY_NOTE. Read it, classify actionable items, create branch weekly/$WEEK in copilot-config, implement LOW blast-radius experiments, and write experiments/$WEEK.md."
