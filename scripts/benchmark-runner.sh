#!/usr/bin/env bash
# benchmark-runner.sh — Weekly benchmark runner
# Invoked by: ~/Library/LaunchAgents/com.johnlin.benchmark-runner.plist
# Schedule: Every Monday at 09:00

set -euo pipefail

LOG="/tmp/benchmark-runner.log"
exec >> "$LOG" 2>&1

echo ""
echo "========================================="
echo "Benchmark Runner — $(date '+%Y-%m-%d %H:%M:%S')"
echo "WEEK: $(date +%Y-W%V)"
echo "========================================="

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

if ! gh auth status > /dev/null 2>&1; then
  echo "ERROR: gh is not authenticated."
  exit 1
fi

exec /opt/homebrew/bin/copilot agent run benchmark-runner \
  --message "Run the full benchmark suite for week $(date +%Y-W%V). Execute all 5 benchmark categories, score each using the defined rubrics, save results to benchmarks/results/$(date +%Y-W%V).json, and generate the markdown report at benchmarks/reports/$(date +%Y-W%V).md. Compare against the most recent previous week's results."
