#!/usr/bin/env bash
# pipeline-dag.sh — Fully dynamic pipeline DAG manager
#
# The DAG is built incrementally by the orchestrator. There are NO fixed
# pipelines. The orchestrator decides what agents are needed based on the
# task, adds them to the DAG, and agents themselves can signal that they
# need sub-agents (orchestrator adds those too).
#
# Flow:
#   1. init       → empty DAG with orchestrator root node (auto-completed)
#   2. add-node   → orchestrator adds agents as it decides they're needed
#   3. start/complete/fail/skip → lifecycle management
#   4. ready      → query which nodes can run next (all deps satisfied)
#   5. remove-node → prune a pending node no longer needed
#
# DAG file: ${STM_DIR}/pipeline-dag.json
#
# Usage:
#   pipeline-dag.sh init        <dag-path>
#   pipeline-dag.sh add-node    <dag-path> <node-id> <agent-type> [--label "..."] [--deps "a,b,c"]
#   pipeline-dag.sh remove-node <dag-path> <node-id>              # remove a pending node
#   pipeline-dag.sh ready       <dag-path>                        # list nodes ready to run
#   pipeline-dag.sh start       <dag-path> <node-id>
#   pipeline-dag.sh complete    <dag-path> <node-id>
#   pipeline-dag.sh fail        <dag-path> <node-id> [reason]
#   pipeline-dag.sh skip        <dag-path> <node-id>
#   pipeline-dag.sh status      <dag-path>
#   pipeline-dag.sh viz         <dag-path>

set -euo pipefail

ACTION="${1:-}"
DAG_PATH="${2:-}"

if [[ -z "$ACTION" || -z "$DAG_PATH" ]]; then
    echo "Usage: pipeline-dag.sh <action> <dag-path> [args...]" >&2
    exit 1
fi

TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# ── Helper: update node field ─────────────────────────────────────────────────
_update_node() {
    local node_id="$1" field="$2" value="$3"
    jq --arg id "$node_id" --arg f "$field" --arg v "$value" \
        '(.nodes[] | select(.id == $id))[$f] = $v | .updated_at = $v' \
        "$DAG_PATH" > "${DAG_PATH}.tmp" && mv "${DAG_PATH}.tmp" "$DAG_PATH"
}

_update_node_ts() {
    local node_id="$1" status="$2" ts_field="$3"
    jq --arg id "$node_id" --arg s "$status" --arg tf "$ts_field" --arg t "$TS" --arg now "$TS" \
        '(.nodes[] | select(.id == $id)).status = $s |
         (.nodes[] | select(.id == $id))[$tf] = $t |
         .updated_at = $now' \
        "$DAG_PATH" > "${DAG_PATH}.tmp" && mv "${DAG_PATH}.tmp" "$DAG_PATH"
}

case "$ACTION" in
    init)
        TS_NOW="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        cat > "$DAG_PATH" << EOF
{
  "version": 2,
  "created_at": "$TS_NOW",
  "updated_at": "$TS_NOW",
  "nodes": [
    {
      "id": "orchestrator",
      "agent": "orchestrator",
      "label": "Orchestrator",
      "deps": [],
      "status": "done",
      "added_at": "$TS_NOW",
      "started_at": "$TS_NOW",
      "completed_at": "$TS_NOW",
      "failed_reason": null
    }
  ]
}
EOF
        echo "[pipeline-dag] ✅ Initialized (orchestrator auto-completed): $DAG_PATH"
        ;;

    add-node)
        NODE_ID="${3:-}"
        AGENT="${4:-}"
        if [[ -z "$NODE_ID" || -z "$AGENT" ]]; then
            echo "[pipeline-dag] ERROR: add-node requires <node-id> <agent-type>" >&2
            exit 1
        fi
        shift 4

        LABEL="$NODE_ID"
        DEPS="[]"
        DESC=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --label) LABEL="${2:-$NODE_ID}"; shift 2 ;;
                --desc) DESC="${2:-}"; shift 2 ;;
                --deps)
                    # Convert comma-separated to JSON array
                    IFS=',' read -ra DEP_ARR <<< "${2:-}"
                    DEPS=$(printf '%s\n' "${DEP_ARR[@]}" | jq -R . | jq -s .)
                    shift 2
                    ;;
                *) shift ;;
            esac
        done

        # Check for duplicate
        if jq -e --arg id "$NODE_ID" '.nodes[] | select(.id == $id)' "$DAG_PATH" >/dev/null 2>&1; then
            echo "[pipeline-dag] ℹ️  Node '$NODE_ID' already exists (skipped)"
            exit 0
        fi

        jq --arg id "$NODE_ID" --arg agent "$AGENT" --arg label "$LABEL" --argjson deps "$DEPS" --arg t "$TS" --arg desc "$DESC" \
            '.nodes += [{
                "id": $id,
                "agent": $agent,
                "label": $label,
                "description": $desc,
                "deps": $deps,
                "status": "pending",
                "added_at": $t,
                "started_at": null,
                "completed_at": null,
                "failed_reason": null
            }] | .updated_at = $t' \
            "$DAG_PATH" > "${DAG_PATH}.tmp" && mv "${DAG_PATH}.tmp" "$DAG_PATH"

        echo "[pipeline-dag] ✅ Added node: $NODE_ID ($AGENT) deps=[$(echo "$DEPS" | jq -r 'join(",")')]"
        ;;

    remove-node)
        NODE_ID="${3:-}"
        if [[ -z "$NODE_ID" ]]; then
            echo "[pipeline-dag] ERROR: remove-node requires <node-id>" >&2; exit 1
        fi
        # Only allow removing pending nodes
        STATUS=$(jq -r --arg id "$NODE_ID" '.nodes[] | select(.id == $id) | .status' "$DAG_PATH" 2>/dev/null)
        if [[ -z "$STATUS" ]]; then
            echo "[pipeline-dag] ERROR: Node '$NODE_ID' not found" >&2; exit 1
        fi
        if [[ "$STATUS" != "pending" ]]; then
            echo "[pipeline-dag] ERROR: Can only remove pending nodes (node '$NODE_ID' is '$STATUS')" >&2; exit 1
        fi
        # Check no other node depends on it
        DEPENDENTS=$(jq -r --arg id "$NODE_ID" '[.nodes[] | select(.deps[] == $id) | .id] | join(", ")' "$DAG_PATH" 2>/dev/null)
        if [[ -n "$DEPENDENTS" ]]; then
            echo "[pipeline-dag] ERROR: Cannot remove '$NODE_ID' — depended on by: $DEPENDENTS" >&2; exit 1
        fi
        jq --arg id "$NODE_ID" --arg t "$TS" \
            '.nodes = [.nodes[] | select(.id != $id)] | .updated_at = $t' \
            "$DAG_PATH" > "${DAG_PATH}.tmp" && mv "${DAG_PATH}.tmp" "$DAG_PATH"
        echo "[pipeline-dag] 🗑  Removed: $NODE_ID"
        ;;

    ready)
        # List nodes whose dependencies are ALL done/skipped AND node itself is pending
        jq -r '
            .nodes as $all |
            .nodes[] |
            select(.status == "pending") |
            select(
                .deps as $deps |
                ($deps | length) == 0 or
                ([$deps[] | . as $d | $all[] | select(.id == $d) | .status] | all(. == "done" or . == "skipped"))
            ) |
            .id
        ' "$DAG_PATH"
        ;;

    start)
        NODE_ID="${3:-}"
        if [[ -z "$NODE_ID" ]]; then
            echo "[pipeline-dag] ERROR: start requires <node-id>" >&2; exit 1
        fi
        _update_node_ts "$NODE_ID" "running" "started_at"
        echo "[pipeline-dag] 🔄 Started: $NODE_ID"
        ;;

    complete)
        NODE_ID="${3:-}"
        if [[ -z "$NODE_ID" ]]; then
            echo "[pipeline-dag] ERROR: complete requires <node-id>" >&2; exit 1
        fi
        _update_node_ts "$NODE_ID" "done" "completed_at"
        echo "[pipeline-dag] ✅ Completed: $NODE_ID"

        # Show newly ready nodes
        READY=$(bash "$0" ready "$DAG_PATH" 2>/dev/null)
        if [[ -n "$READY" ]]; then
            echo "[pipeline-dag] 🟢 Now ready: $READY"
        fi
        ;;

    fail)
        NODE_ID="${3:-}"
        REASON="${4:-unknown}"
        if [[ -z "$NODE_ID" ]]; then
            echo "[pipeline-dag] ERROR: fail requires <node-id>" >&2; exit 1
        fi
        jq --arg id "$NODE_ID" --arg r "$REASON" --arg t "$TS" \
            '(.nodes[] | select(.id == $id)).status = "failed" |
             (.nodes[] | select(.id == $id)).completed_at = $t |
             (.nodes[] | select(.id == $id)).failed_reason = $r |
             .updated_at = $t' \
            "$DAG_PATH" > "${DAG_PATH}.tmp" && mv "${DAG_PATH}.tmp" "$DAG_PATH"
        echo "[pipeline-dag] ❌ Failed: $NODE_ID — $REASON"
        ;;

    skip)
        NODE_ID="${3:-}"
        if [[ -z "$NODE_ID" ]]; then
            echo "[pipeline-dag] ERROR: skip requires <node-id>" >&2; exit 1
        fi
        _update_node_ts "$NODE_ID" "skipped" "completed_at"
        echo "[pipeline-dag] ⏭  Skipped: $NODE_ID"

        READY=$(bash "$0" ready "$DAG_PATH" 2>/dev/null)
        if [[ -n "$READY" ]]; then
            echo "[pipeline-dag] 🟢 Now ready: $READY"
        fi
        ;;

    status)
        echo "=== Pipeline DAG Status ==="
        jq -r '.nodes[] | "\(.status | if . == "done" then "✅" elif . == "running" then "🔄" elif . == "failed" then "❌" elif . == "skipped" then "⏭ " else "⏳" end) \(.id) (\(.agent)) deps=[\(.deps | join(","))]"' "$DAG_PATH"
        echo ""
        DONE=$(jq '[.nodes[] | select(.status == "done" or .status == "skipped")] | length' "$DAG_PATH")
        TOTAL=$(jq '.nodes | length' "$DAG_PATH")
        RUNNING=$(jq '[.nodes[] | select(.status == "running")] | length' "$DAG_PATH")
        FAILED=$(jq '[.nodes[] | select(.status == "failed")] | length' "$DAG_PATH")
        echo "Progress: $DONE/$TOTAL done, $RUNNING running, $FAILED failed"
        ;;

    viz)
        # Text-based DAG visualization
        echo "=== Pipeline DAG ==="
        echo ""
        # Show nodes grouped by depth (BFS layers)
        jq -r '
            def depth:
                . as $nodes |
                reduce .[] as $n (
                    {};
                    . as $depths |
                    if ($n.deps | length) == 0 then
                        . + {($n.id): 0}
                    else
                        ($n.deps | map($depths[.] // 0) | max) + 1 |
                        $depths + {($n.id): .}
                    end
                );
            .nodes | depth as $d |
            ($d | to_entries | map(.value) | max // 0) as $max_depth |
            range(0; $max_depth + 1) | . as $layer |
            "Layer \($layer):",
            ([$d | to_entries[] | select(.value == $layer) | .key] | join("  "))
        ' "$DAG_PATH" 2>/dev/null || echo "(visualization requires jq with advanced features)"

        echo ""
        echo "--- Edges ---"
        jq -r '.nodes[] | select(.deps | length > 0) | "\(.deps | join(", ")) → \(.id)"' "$DAG_PATH"
        ;;

    *)
        echo "[pipeline-dag] ERROR: Unknown action '$ACTION'" >&2
        echo "Actions: init, add-node, remove-node, ready, start, complete, fail, skip, status, viz" >&2
        exit 1
        ;;
esac
