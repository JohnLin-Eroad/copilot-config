#!/usr/bin/env bash
# benchmark-runner.sh — Weekly benchmark runner
# Invoked by: ~/Library/LaunchAgents/com.johnlin.benchmark-runner.plist
# Schedule: Every Monday at 09:00
#
# Architecture: This script delegates ALL work to benchmark-orchestrator.py.
# The Python orchestrator handles prompt selection, copilot execution, grading,
# trace writing, results aggregation, and git commit. This shell script just
# handles logging, PATH, and error reporting.

LOG="/tmp/benchmark-runner.log"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ORCHESTRATOR="$SCRIPT_DIR/benchmark-orchestrator.py"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

WEEK=$(date +%G-W%V)

echo "" >> "$LOG"
echo "=========================================" >> "$LOG"
echo "Benchmark Runner — $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"
echo "WEEK: $WEEK" >> "$LOG"
echo "=========================================" >> "$LOG"

# Pre-flight: check gh auth (needed for copilot CLI)
if ! gh auth status > /dev/null 2>&1; then
  echo "ERROR: gh is not authenticated." >> "$LOG"
  exit 1
fi

# Pre-flight: check orchestrator exists
if [ ! -f "$ORCHESTRATOR" ]; then
  echo "ERROR: Orchestrator not found at $ORCHESTRATOR" >> "$LOG"
  exit 1
fi

# Run the Python orchestrator
echo "Starting benchmark-orchestrator.py..." >> "$LOG"
python3 "$ORCHESTRATOR" "$WEEK" --verbose >> "$LOG" 2>&1
EXIT_CODE=$?

echo "" >> "$LOG"
echo "=========================================" >> "$LOG"
echo "Benchmark Runner finished at $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"
echo "Exit code: $EXIT_CODE" >> "$LOG"
echo "=========================================" >> "$LOG"

exit $EXIT_CODE
