#!/usr/bin/env bash
# add-learning.sh — Write a learning to the global or local learnings file
#
# Usage:
#   bash add-learning.sh --global "What was learned"
#   bash add-learning.sh --local  "What was learned"
#   bash add-learning.sh          "What was learned"  # auto-detects: local if in git repo, else global
#
# Files written to:
#   Global: ~/.copilot/learnings.md
#   Local:  <git-root>/.github/learnings.md

set -e

GLOBAL_FILE="$HOME/.copilot/learnings.md"
MODE="auto"
LEARNING=""

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --global) MODE="global"; shift ;;
    --local)  MODE="local";  shift ;;
    *)        LEARNING="$1"; shift ;;
  esac
done

if [[ -z "$LEARNING" ]]; then
  echo "Usage: add-learning.sh [--global|--local] \"Learning text\"" >&2
  exit 1
fi

# Auto-detect mode: local if inside a git repo, global otherwise
if [[ "$MODE" == "auto" ]]; then
  if git rev-parse --show-toplevel &>/dev/null 2>&1; then
    MODE="local"
  else
    MODE="global"
  fi
fi

# Determine target file
if [[ "$MODE" == "global" ]]; then
  TARGET="$GLOBAL_FILE"
  SCOPE="global"
else
  GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
  if [[ -z "$GIT_ROOT" ]]; then
    echo "Warning: not in a git repo, falling back to global learnings" >&2
    TARGET="$GLOBAL_FILE"
    SCOPE="global"
  else
    TARGET="$GIT_ROOT/.github/learnings.md"
    SCOPE="local ($GIT_ROOT)"
    mkdir -p "$GIT_ROOT/.github"
  fi
fi

DATE=$(date +%Y-%m-%d)
REPO_NAME=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "")")

# Create file with header if it doesn't exist
if [[ ! -f "$TARGET" ]]; then
  if [[ "$MODE" == "global" ]]; then
    cat > "$TARGET" << 'EOF'
# Copilot Global Learnings

Cross-repo patterns, preferences, and lessons learned — applied to all sessions.

---

EOF
  else
    cat > "$TARGET" << EOF
# Copilot Learnings — ${REPO_NAME}

Repo-specific patterns, gotchas, and lessons learned for this project.

---

EOF
  fi
fi

# Append the learning with date
echo "- **[$DATE]** $LEARNING" >> "$TARGET"

echo "✅ Learning written to $SCOPE learnings file"
echo "   → $TARGET"
