#!/bin/bash
# weekly-branch.sh — Weekly branch rotation for ~/copilot-config
#
# Usage:
#   weekly-branch.sh --open    Create this week's branch from master (idempotent). Run Monday morning.
#   weekly-branch.sh --close   Merge current week to master, create next week's branch. Run Sunday evening.
#
# Branch naming: weekly/YYYY-WXX  (ISO 8601 week, e.g. weekly/2026-W17)
# fswatch auto-pushes commits to whatever branch is checked out, so switching
# branches here is all that's needed to redirect the auto-sync.

set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

REPO_DIR="$HOME/copilot-config"
LOG="$HOME/.copilot/logs/watch-config.log"

log() { echo "[$(date)] 📅 weekly-branch: $*" | tee -a "$LOG"; }

cd "$REPO_DIR"

# macOS vs GNU date for "7 days from now"
next_week() { date -v+7d +%G-W%V 2>/dev/null || date --date="7 days" +%G-W%V; }

CURRENT_BRANCH="weekly/$(date +%G-W%V)"
NEXT_BRANCH="weekly/$(next_week)"

case "${1:-}" in

  --open)
    log "Opening week: $CURRENT_BRANCH"
    git fetch origin --quiet

    if git show-ref --quiet "refs/heads/$CURRENT_BRANCH"; then
      log "Branch already exists locally — checking out"
      git checkout "$CURRENT_BRANCH"
    elif git show-ref --quiet "refs/remotes/origin/$CURRENT_BRANCH"; then
      log "Branch exists on remote — tracking and checking out"
      git checkout --track "origin/$CURRENT_BRANCH"
    else
      log "Creating $CURRENT_BRANCH from master"
      git checkout master
      git pull origin master --quiet
      git checkout -b "$CURRENT_BRANCH"
      git push --set-upstream origin "$CURRENT_BRANCH"
      log "✅ Created and pushed $CURRENT_BRANCH"
    fi

    log "Now on: $(git branch --show-current)"
    ;;

  --close)
    ACTIVE=$(git branch --show-current)
    log "Closing week — merging $ACTIVE → master"

    if [[ "$ACTIVE" != weekly/* ]]; then
      log "⚠️  Not on a weekly branch ($ACTIVE) — aborting close"
      exit 1
    fi

    # Merge current week into master
    git checkout master
    git pull origin master --quiet
    git merge --no-ff "$ACTIVE" -m "chore: merge $ACTIVE into master

Weekly experiment branch merged at end of week.
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
    git push origin master
    log "✅ Merged $ACTIVE → master and pushed"

    # Create next week's branch and switch to it so fswatch targets it
    log "Opening next week: $NEXT_BRANCH"
    if git show-ref --quiet "refs/heads/$NEXT_BRANCH"; then
      log "Next week's branch already exists — checking out"
      git checkout "$NEXT_BRANCH"
    else
      git checkout -b "$NEXT_BRANCH"
      git push --set-upstream origin "$NEXT_BRANCH"
      log "✅ Created and pushed $NEXT_BRANCH"
    fi

    log "Now on: $(git branch --show-current) — ready for next week"
    ;;

  *)
    echo "Usage: $0 --open | --close"
    exit 1
    ;;
esac
