#!/usr/bin/env bash
# brain-manifest.sh — Manage the brain fetch manifest (JSON)
#
# The manifest tracks what brain-data-retrieval has already fetched,
# searched, and marked as absent. Subsequent invocations read this
# to avoid duplicate work — much faster than re-parsing the full STM.
#
# Usage:
#   brain-manifest.sh init   <manifest-path>
#   brain-manifest.sh add    <manifest-path> <relative-path> <score> <lines> [compressed]
#   brain-manifest.sh search <manifest-path> <query-term> <result-count>
#   brain-manifest.sh absent <manifest-path> <topic>
#   brain-manifest.sh check  <manifest-path> <relative-path>     # exit 0 if fetched, 1 if not
#   brain-manifest.sh dump   <manifest-path>                     # pretty-print the manifest
#   brain-manifest.sh stats  <manifest-path>                     # summary stats
#
# The manifest is a JSON file stored alongside the STM:
#   /tmp/task-<slug>/brain-manifest.json

set -euo pipefail

ACTION="${1:-}"
MANIFEST="${2:-}"

if [[ -z "$ACTION" || -z "$MANIFEST" ]]; then
    echo "Usage: brain-manifest.sh <action> <manifest-path> [args...]" >&2
    exit 1
fi

TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

case "$ACTION" in
    init)
        cat > "$MANIFEST" << EOF
{
  "created": "$TS",
  "fetched_files": [],
  "searches": [],
  "absent_topics": [],
  "stats": {
    "total_fetched": 0,
    "total_searches": 0,
    "total_absent": 0,
    "total_lines_fetched": 0,
    "invocations": 0
  }
}
EOF
        echo "[brain-manifest] ✅ Initialized: $MANIFEST"
        ;;

    add)
        REL_PATH="${3:-}"
        SCORE="${4:-0}"
        LINES="${5:-0}"
        COMPRESSED="${6:-false}"

        if [[ -z "$REL_PATH" ]]; then
            echo "[brain-manifest] ERROR: add requires <relative-path>" >&2
            exit 1
        fi

        # Check if already fetched
        if jq -e --arg p "$REL_PATH" '.fetched_files[] | select(.path == $p)' "$MANIFEST" >/dev/null 2>&1; then
            echo "[brain-manifest] ℹ️  Already fetched: $REL_PATH (skipped)"
            exit 0
        fi

        # Add to manifest
        jq --arg p "$REL_PATH" --arg s "$SCORE" --arg l "$LINES" --arg c "$COMPRESSED" --arg t "$TS" \
            '.fetched_files += [{"path": $p, "score": ($s|tonumber), "lines": ($l|tonumber), "compressed": ($c == "true"), "fetched_at": $t}] |
             .stats.total_fetched += 1 |
             .stats.total_lines_fetched += ($l|tonumber)' \
            "$MANIFEST" > "${MANIFEST}.tmp" && mv "${MANIFEST}.tmp" "$MANIFEST"

        echo "[brain-manifest] ✅ Added: $REL_PATH (score=$SCORE, lines=$LINES, compressed=$COMPRESSED)"
        ;;

    search)
        QUERY="${3:-}"
        RESULT_COUNT="${4:-0}"

        if [[ -z "$QUERY" ]]; then
            echo "[brain-manifest] ERROR: search requires <query-term>" >&2
            exit 1
        fi

        jq --arg q "$QUERY" --arg n "$RESULT_COUNT" --arg t "$TS" \
            '.searches += [{"query": $q, "results": ($n|tonumber), "searched_at": $t}] |
             .stats.total_searches += 1' \
            "$MANIFEST" > "${MANIFEST}.tmp" && mv "${MANIFEST}.tmp" "$MANIFEST"

        echo "[brain-manifest] 🔍 Recorded search: '$QUERY' → $RESULT_COUNT results"
        ;;

    absent)
        TOPIC="${3:-}"

        if [[ -z "$TOPIC" ]]; then
            echo "[brain-manifest] ERROR: absent requires <topic>" >&2
            exit 1
        fi

        # Check if already recorded
        if jq -e --arg t "$TOPIC" '.absent_topics[] | select(.topic == $t)' "$MANIFEST" >/dev/null 2>&1; then
            echo "[brain-manifest] ℹ️  Already recorded as absent: $TOPIC"
            exit 0
        fi

        jq --arg topic "$TOPIC" --arg t "$TS" \
            '.absent_topics += [{"topic": $topic, "recorded_at": $t}] |
             .stats.total_absent += 1' \
            "$MANIFEST" > "${MANIFEST}.tmp" && mv "${MANIFEST}.tmp" "$MANIFEST"

        echo "[brain-manifest] ⊘ Recorded absent: $TOPIC"
        ;;

    check)
        REL_PATH="${3:-}"
        if jq -e --arg p "$REL_PATH" '.fetched_files[] | select(.path == $p)' "$MANIFEST" >/dev/null 2>&1; then
            echo "FETCHED"
            exit 0
        else
            echo "NOT_FETCHED"
            exit 1
        fi
        ;;

    bump)
        # Increment invocation counter (call at start of each brain-data-retrieval run)
        jq '.stats.invocations += 1' "$MANIFEST" > "${MANIFEST}.tmp" && mv "${MANIFEST}.tmp" "$MANIFEST"
        echo "[brain-manifest] 📊 Invocation count: $(jq '.stats.invocations' "$MANIFEST")"
        ;;

    dump)
        jq '.' "$MANIFEST"
        ;;

    stats)
        echo "=== Brain Manifest Stats ==="
        jq -r '"Files fetched:  \(.stats.total_fetched)
Lines fetched:  \(.stats.total_lines_fetched)
Searches done:  \(.stats.total_searches)
Absent topics:  \(.stats.total_absent)
Invocations:    \(.stats.invocations)"' "$MANIFEST"
        echo ""
        echo "Fetched paths:"
        jq -r '.fetched_files[].path' "$MANIFEST" 2>/dev/null | sed 's/^/  - /'
        echo ""
        echo "Absent topics:"
        jq -r '.absent_topics[].topic' "$MANIFEST" 2>/dev/null | sed 's/^/  - /'
        ;;

    *)
        echo "[brain-manifest] ERROR: Unknown action '$ACTION'" >&2
        echo "Actions: init, add, search, absent, check, bump, dump, stats" >&2
        exit 1
        ;;
esac
