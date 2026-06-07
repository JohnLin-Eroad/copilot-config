#!/usr/bin/env bash
# brain-git-push.sh — Commit and push all changes in the eroad-brain vault to GitHub
#
# Usage:
#   bash ~/.copilot/scripts/brain-git-push.sh                  # auto message
#   bash ~/.copilot/scripts/brain-git-push.sh "custom message"  # custom commit message

set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

BRAIN_DIR="$HOME/eroad-brain"
DATE=$(date '+%Y-%m-%d %H:%M')
MSG="${1:-"chore: auto-sync brain vault — $DATE"}"

cd "$BRAIN_DIR"

# Nothing to do if clean
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  echo "ℹ️  Brain vault is clean — nothing to push."
  exit 0
fi

git add -A
git commit -m "$MSG

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push

echo "✅ Brain vault synced to GitHub."
