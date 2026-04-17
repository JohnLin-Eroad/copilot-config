#!/bin/bash
# Obsidian vault → GitHub sync via fswatch
# Watches both vaults and commits+pushes on change (10s debounce via PID files)

VAULTS=(
  "/Users/johnlin/Library/CloudStorage/OneDrive-EROAD/Documents/eroad-brain"
  "/Users/johnlin/Library/CloudStorage/OneDrive-EROAD/Documents/copilot-sessions"
  "/Users/johnlin/john-brain"
)

DEBOUNCE=10
PID_DIR="/tmp/obsidian-sync-pids"
mkdir -p "$PID_DIR"

sync_vault() {
  local vault="$1"
  local name
  name=$(basename "$vault")

  cd "$vault" || return

  if git diff --quiet && git diff --staged --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    return
  fi

  git add -A
  git commit -m "sync: auto-commit $(date '+%Y-%m-%d %H:%M:%S')" --quiet
  git push --quiet
  echo "[$(date '+%H:%M:%S')] Synced $name"
}

schedule_sync() {
  local vault="$1"
  local name
  name=$(basename "$vault")
  local pid_file="$PID_DIR/$name.pid"

  # Cancel any pending sync for this vault
  if [ -f "$pid_file" ]; then
    local old_pid
    old_pid=$(cat "$pid_file")
    /bin/kill "$old_pid" 2>/dev/null; wait "$old_pid" 2>/dev/null
    rm -f "$pid_file"
  fi

  # Schedule a new sync after debounce
  (sleep "$DEBOUNCE" && sync_vault "$vault" && rm -f "$pid_file") &
  echo $! > "$pid_file"
}

echo "Starting Obsidian sync watcher..."
for vault in "${VAULTS[@]}"; do
  echo "  Watching: $vault"
done

# Initial sync on startup
for vault in "${VAULTS[@]}"; do
  sync_vault "$vault"
done

# Watch for changes
/opt/homebrew/bin/fswatch -r \
  --exclude "\.git" \
  --exclude "\.DS_Store" \
  --exclude "workspace\.json" \
  "${VAULTS[@]}" | while IFS= read -r changed_file; do
  for vault in "${VAULTS[@]}"; do
    if [[ "$changed_file" == "$vault"* ]]; then
      schedule_sync "$vault"
      break
    fi
  done
done
