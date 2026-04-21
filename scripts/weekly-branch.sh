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
STATE_FILE="$HOME/.copilot/state/weekly-branch.json"

log() { echo "[$(date)] 📅 weekly-branch: $*" | tee -a "$LOG"; }

mkdir -p "$(dirname "$STATE_FILE")"
cd "$REPO_DIR"

# macOS vs GNU date for "7 days from now"
next_week() { date -v+7d +%G-W%V 2>/dev/null || date --date="7 days" +%G-W%V; }

CURRENT_BRANCH="weekly/$(date +%G-W%V)"
NEXT_BRANCH="weekly/$(next_week)"

# Persist last-run timestamps so --check can detect missed windows
state_get() { python3 -c "import json,os; f='$STATE_FILE'; d=json.load(open(f)) if os.path.exists(f) else {}; print(d.get('$1',''))" 2>/dev/null; }
state_set() { python3 -c "
import json, os
f='$STATE_FILE'
d=json.load(open(f)) if os.path.exists(f) else {}
d['$1']='$2'
json.dump(d, open(f,'w'))
" 2>/dev/null; }

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

    state_set "last_open" "$(date +%s)"
    state_set "last_open_branch" "$CURRENT_BRANCH"
    log "Now on: $(git branch --show-current)"
    ;;

  --close)
    ACTIVE=$(git branch --show-current)
    log "Closing week — creating PR for $ACTIVE → master"

    if [[ "$ACTIVE" != weekly/* ]]; then
      log "⚠️  Not on a weekly branch ($ACTIVE) — aborting close"
      exit 1
    fi

    # Push any remaining changes before opening the PR
    git push origin "$ACTIVE" --quiet

    # Create PR for review (idempotent — gh will error if PR already exists, which is fine)
    WEEK=$(echo "$ACTIVE" | sed 's|weekly/||')
    PR_URL=$(gh pr create \
      --base master \
      --head "$ACTIVE" \
      --title "Weekly config: $WEEK" \
      --body "Weekly Copilot config changes for $WEEK.

Review and cherry-pick what to merge into master." \
      --repo "JohnLin-Eroad/copilot-config" 2>&1) && \
      log "✅ PR created: $PR_URL" || \
      log "⚠️  PR creation skipped (may already exist): $PR_URL"

    # Create next week's branch from master and switch to it so fswatch targets it
    log "Opening next week: $NEXT_BRANCH"
    git fetch origin --quiet
    if git show-ref --quiet "refs/heads/$NEXT_BRANCH"; then
      log "Next week's branch already exists — checking out"
      git checkout "$NEXT_BRANCH"
    elif git show-ref --quiet "refs/remotes/origin/$NEXT_BRANCH"; then
      git checkout --track "origin/$NEXT_BRANCH"
    else
      git checkout master
      git pull origin master --quiet
      git checkout -b "$NEXT_BRANCH"
      git push --set-upstream origin "$NEXT_BRANCH"
      log "✅ Created and pushed $NEXT_BRANCH"
    fi

    state_set "last_close" "$(date +%s)"
    state_set "last_close_branch" "$ACTIVE"
    log "Now on: $(git branch --show-current) — ready for next week"
    ;;

  --check)
    # Run missed --open or --close actions since the last time they were executed.
    # Called at Copilot session start to catch up after sleep/shutdown.
    NOW=$(date +%s)
    DOW=$(date +%u)   # 1=Mon … 7=Sun
    HOUR=$(date +%H)  # 00-23

    LAST_OPEN=$(state_get "last_open")
    LAST_OPEN_BRANCH=$(state_get "last_open_branch")
    LAST_CLOSE=$(state_get "last_close")

    # --- Check if --open is overdue ---
    # Due: Monday (DOW=1) at or after 09:00
    # Overdue if: it's Mon+ AND last_open_branch != current week's branch
    if [[ "$LAST_OPEN_BRANCH" != "$CURRENT_BRANCH" ]]; then
      # We haven't opened this week's branch yet
      ACTIVE=$(git branch --show-current 2>/dev/null || echo "")
      if [[ "$ACTIVE" != "$CURRENT_BRANCH" ]]; then
        log "🔔 --open overdue for $CURRENT_BRANCH — running now (catch-up)"
        bash "$0" --open
      fi
    fi

    # --- Check if --close is overdue ---
    # Due: Sunday (DOW=7) at or after 18:00
    # Overdue if: it's Mon+ AND last_close didn't happen this week (branch still weekly/last-week)
    ACTIVE=$(git branch --show-current 2>/dev/null || echo "")
    if [[ "$ACTIVE" == weekly/* && "$ACTIVE" != "$CURRENT_BRANCH" ]]; then
      # Still on last week's branch — close was missed
      log "🔔 --close overdue (still on $ACTIVE, current week is $CURRENT_BRANCH) — running now (catch-up)"
      bash "$0" --close
    fi

    log "✅ Check complete"
    ;;

  *)
    echo "Usage: $0 --open | --close"
    exit 1
    ;;
esac
