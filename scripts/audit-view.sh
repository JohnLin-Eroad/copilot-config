#!/bin/bash
# audit-view.sh — view governance audit log entries
# Usage: audit-view.sh [options]
#   -n <N>          last N entries (default: 20)
#   -b <level>      filter by blast radius (CRITICAL|HIGH|MEDIUM|LOW)
#   -d <decision>   filter by decision (BLOCK|ALLOW)
#   -c <category>   filter by category (e.g. file-write, vcs, database)
#   --blocks        show only blocked operations
#   --today         show only today's entries
#   --json          raw JSON output (no pretty-print)

AUDIT_LOG="$HOME/.copilot/logs/audit.jsonl"

if [[ ! -f "$AUDIT_LOG" ]]; then
  echo "No audit log found at $AUDIT_LOG"
  exit 0
fi

N=20
FILTER=""
JSON_MODE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n) N="$2"; shift 2 ;;
    -b) BLAST="$2"; shift 2 ;;
    -d) DECISION="$2"; shift 2 ;;
    -c) CATEGORY="$2"; shift 2 ;;
    --blocks) DECISION="BLOCK"; shift ;;
    --today) TODAY=$(date +%Y-%m-%d); shift ;;
    --json) JSON_MODE=true; shift ;;
    -h|--help)
      head -10 "$0" | grep "^#" | sed 's/^# //'
      exit 0 ;;
    *) shift ;;
  esac
done

# Build jq filter
JQ_FILTER="."
[[ -n "$BLAST" ]]    && JQ_FILTER+=" | select(.blastRadius == \"$BLAST\")"
[[ -n "$DECISION" ]] && JQ_FILTER+=" | select(.decision == \"$DECISION\")"
[[ -n "$CATEGORY" ]] && JQ_FILTER+=" | select(.category == \"$CATEGORY\")"
[[ -n "$TODAY" ]]    && JQ_FILTER+=" | select(.timestamp | startswith(\"$TODAY\"))"

if $JSON_MODE; then
  tail -"$N" "$AUDIT_LOG" | jq "$JQ_FILTER" 2>/dev/null
else
  echo "=== Sovereign Copilot Audit Log (last $N entries) ==="
  [[ -n "$BLAST" ]]    && echo "  Filter: blast=$BLAST"
  [[ -n "$DECISION" ]] && echo "  Filter: decision=$DECISION"
  [[ -n "$CATEGORY" ]] && echo "  Filter: category=$CATEGORY"
  [[ -n "$TODAY" ]]    && echo "  Filter: today=$TODAY"
  echo ""

  tail -"$N" "$AUDIT_LOG" | jq -r "$JQ_FILTER | \
    \"\(.timestamp // \"-\") | \(.decision // \"?\") | blast=\(.blastRadius // \"-\") | \(.tool // \"-\") | \(.category // \"-\") | \(.note // \"-\")\"" 2>/dev/null | \
    awk -F' | ' '{
      d = $2; color=""
      if (d == "BLOCK") color = "\033[31m"
      else color = "\033[32m"
      printf "%s %s%-5s\033[0m %s %s %s\n", $1, color, $2, $4, $5, $6
    }'

  echo ""
  TOTAL=$(wc -l < "$AUDIT_LOG")
  BLOCKS=$(grep -c '"BLOCK"' "$AUDIT_LOG" 2>/dev/null || echo 0)
  echo "  Total entries: $TOTAL | Blocked: $BLOCKS"
fi
