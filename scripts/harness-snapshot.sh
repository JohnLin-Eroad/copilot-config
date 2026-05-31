#!/bin/bash
# harness-snapshot.sh
# Snapshot current harness state into copilot-config/harness-candidates/WEEK/
# Run after benchmark-runner completes to capture the exact config that produced the scores.

set -euo pipefail

WEEK="${1:-$(date +"%Y-W%V")}"
CONFIG=~/copilot-config
DEST="$CONFIG/harness-candidates/$WEEK"

mkdir -p "$DEST/agents" "$DEST/skills"

# Core harness files
cp ~/.copilot/copilot-instructions.md "$DEST/"
cp ~/.copilot/agents/*.agent.md "$DEST/agents/" 2>/dev/null || true
cp ~/.copilot/skills/*.skill.md "$DEST/skills/" 2>/dev/null || true

# Write score metadata from the week's benchmark result (if available)
RESULT="$CONFIG/benchmarks/results/$WEEK.json"
if [ -f "$RESULT" ]; then
    python3 - "$RESULT" "$DEST/score.txt" << 'EOF'
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
overall = d.get("overall", "?")
tasks = d.get("tasks", {})
with open(sys.argv[2], "w") as out:
    out.write(f"overall: {overall}\n")
    for task, score in tasks.items():
        out.write(f"{task}: {score}\n")
EOF
else
    echo "overall: pending" > "$DEST/score.txt"
fi

cd "$CONFIG"

# Ensure we're on master before committing the snapshot
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "master")
git checkout "$DEFAULT_BRANCH" 2>/dev/null || git checkout master

git add "harness-candidates/$WEEK/"

if git diff --cached --quiet; then
    echo "No harness changes to snapshot for $WEEK"
    exit 0
fi

git commit -m "Harness snapshot: $WEEK

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"

git push origin "$DEFAULT_BRANCH"
echo "$(date '+%Y-%m-%d %H:%M:%S') harness-snapshot: $WEEK saved to harness-candidates/$WEEK/"
