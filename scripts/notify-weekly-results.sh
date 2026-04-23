#!/usr/bin/env bash
# notify-weekly-results.sh — Run weekly benchmark then post results to PR + notify user.
# Called by weekly-branch.sh --close in background after PR creation.
#
# Usage: notify-weekly-results.sh <pr_url> <week>   e.g. notify-weekly-results.sh https://github.com/.../pull/12 2026-W17

set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PR_URL="${1:-}"
WEEK="${2:-$(date +%G-W%V)}"
RESULTS_FILE="$HOME/copilot-config/benchmarks/results/$WEEK.json"
LOG="$HOME/.copilot/logs/watch-config.log"
REPO="JohnLin-Eroad/copilot-config"

log()    { echo "[$(date)] 📊 notify-weekly: $*" | tee -a "$LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"$2\"" 2>/dev/null || true; }

# ------------------------------------------------------------------
# 1. Run the benchmark agent
# ------------------------------------------------------------------
log "Running benchmark suite for $WEEK..."

/opt/homebrew/bin/copilot agent run benchmark-runner \
  --message "Run the full benchmark suite for week $WEEK. Execute all 5 benchmark categories, score each using the defined rubrics, save results to benchmarks/results/$WEEK.json, and generate the markdown report at benchmarks/reports/$WEEK.md. Compare against the most recent previous week's results." \
  2>&1 | tee -a "$LOG"

# ------------------------------------------------------------------
# 2. Wait for results file (up to 5 min)
# ------------------------------------------------------------------
for i in $(seq 1 30); do
  [[ -f "$RESULTS_FILE" ]] && break
  sleep 10
done

if [[ ! -f "$RESULTS_FILE" ]]; then
  log "⚠️  Benchmark results not found after 5 min — skipping notification"
  notify "Benchmarking failed or timed out for $WEEK. Check logs." "⚠️ Copilot Weekly"
  exit 1
fi

# ------------------------------------------------------------------
# 3. Parse results into a markdown comment
# ------------------------------------------------------------------
SUMMARY=$(python3 - <<PYEOF
import json

with open("$RESULTS_FILE") as f:
    d = json.load(f)

overall  = d.get("overall", "?")
vs_prev  = d.get("vs_previous", 0)
delta    = f"+{vs_prev}" if isinstance(vs_prev, (int, float)) and vs_prev >= 0 else str(vs_prev)
scores   = d.get("scores", {})

lines = [
    f"## 📊 Benchmark Results — $WEEK",
    f"",
    f"**Overall: {overall}/100** ({delta} vs last week)",
    f"",
    f"| Category | Score | Max |",
    f"|---|---|---|",
]
for key, val in scores.items():
    name  = key.replace("_", " ").title()
    score = val.get("score", "?")
    max_s = val.get("max", 5)
    lines.append(f"| {name} | {score} | {max_s} |")

lines += [
    f"",
    f"> Full report: \`benchmarks/reports/$WEEK.md\`",
]
print("\\n".join(lines))
PYEOF
)

log "Benchmark complete — posting results to PR"

# ------------------------------------------------------------------
# 4. Post as PR comment
# ------------------------------------------------------------------
if [[ -n "$PR_URL" ]]; then
  gh pr comment "$PR_URL" --body "$SUMMARY" 2>&1 | tee -a "$LOG" \
    && log "✅ Posted benchmark results to PR" \
    || log "⚠️  Failed to post PR comment"
else
  log "⚠️  No PR URL provided — skipping PR comment"
fi

# ------------------------------------------------------------------
# 5. macOS notification with headline score
# ------------------------------------------------------------------
SCORE=$(python3 -c "import json; d=json.load(open('$RESULTS_FILE')); print(d.get('overall','?'))" 2>/dev/null || echo "?")
DELTA=$(python3 -c "
import json
d = json.load(open('$RESULTS_FILE'))
v = d.get('vs_previous', 0)
print(f'+{v}' if isinstance(v, (int,float)) and v >= 0 else str(v))
" 2>/dev/null || echo "")

notify "Score: $SCORE/100 ($DELTA vs last week). PR ready for review." "✅ $WEEK Benchmarks Done"

log "All done for $WEEK."
