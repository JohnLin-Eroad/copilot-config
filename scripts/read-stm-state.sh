#!/usr/bin/env bash
# read-stm-state.sh — Query the latest state for a unit from the STM file
#
# Usage:
#   bash ~/.copilot/scripts/read-stm-state.sh "$STM_PATH" "A"
#   bash ~/.copilot/scripts/read-stm-state.sh "$STM_PATH"        # prints all unit states
#
# Returns (stdout):
#   Single unit:  NOT_STARTED | CLAIMED | IN_PROGRESS | COMPILE_CHECKED | DONE | FAILED | DEFERRED
#   All units:    table of UNIT / STATE / AGENT / TIMESTAMP_MS
#
# State headers written by write-stm.sh:
#   <!-- UNIT:A STATE:IN_PROGRESS TS:1745284800000 AGENT:developer-A -->
# Compatible with bash 3.2+ (macOS default — no associative arrays used)

set -euo pipefail

STM_PATH="${1:-}"
UNIT_FILTER="${2:-}"

if [[ -z "$STM_PATH" || ! -f "$STM_PATH" ]]; then
    if [[ -n "$UNIT_FILTER" ]]; then echo "NOT_STARTED"; else echo "(no STM found)"; fi
    exit 0
fi

# ── Extract all state header lines, keep only the LAST per unit ───────────────
# Format: <!-- UNIT:X STATE:Y TS:Z AGENT:W -->
# Strategy: grep all matches, then use awk to keep last-seen per unit ID

ALL_HEADERS="$(grep -o '<!-- UNIT:[A-Za-z0-9_-]* STATE:[A-Z_]* TS:[0-9]* AGENT:[^ ]* -->' "$STM_PATH" 2>/dev/null || true)"

if [[ -z "$ALL_HEADERS" ]]; then
    if [[ -n "$UNIT_FILTER" ]]; then echo "NOT_STARTED"; else echo "(no unit states found in STM)"; fi
    exit 0
fi

# Use awk to keep the last occurrence per UNIT (latest state wins — append-only)
LATEST="$(echo "$ALL_HEADERS" | awk '{
    # Extract UNIT, STATE, TS, AGENT from: <!-- UNIT:X STATE:Y TS:Z AGENT:W -->
    for (i=1; i<=NF; i++) {
        if ($i ~ /^UNIT:/)  { split($i, a, ":"); uid=a[2] }
        if ($i ~ /^STATE:/) { split($i, a, ":"); state=a[2] }
        if ($i ~ /^TS:/)    { split($i, a, ":"); ts=a[2] }
        if ($i ~ /^AGENT:/) { split($i, a, ":"); agent=a[2] }
    }
    # Overwrite — last line for this unit wins
    unit_state[uid]=state
    unit_agent[uid]=agent
    unit_ts[uid]=ts
}
END {
    for (u in unit_state) print u "\t" unit_state[u] "\t" unit_agent[u] "\t" unit_ts[u]
}' | sort)"

if [[ -n "$UNIT_FILTER" ]]; then
    # Single unit — return state only
    MATCH="$(echo "$LATEST" | awk -F'\t' -v u="$UNIT_FILTER" '$1==u {print $2}')"
    echo "${MATCH:-NOT_STARTED}"
else
    # All units table
    printf "%-12s %-20s %-24s %s\n" "UNIT" "STATE" "AGENT" "TIMESTAMP_MS"
    printf "%-12s %-20s %-24s %s\n" "----" "-----" "-----" "------------"
    echo "$LATEST" | awk -F'\t' '{ printf "%-12s %-20s %-24s %s\n", $1, $2, $3, $4 }'
fi
