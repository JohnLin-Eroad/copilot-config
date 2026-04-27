#!/usr/bin/env bash
# pipeline-dag.sh — Manage a pipeline DAG (Directed Acyclic Graph)
#
# The DAG tracks agent dependencies and execution state. The orchestrator
# uses it to determine which agents can run next. The dashboard reads it
# to render the actual dependency graph.
#
# DAG file lives alongside the STM: ${STM_DIR}/pipeline-dag.json
#
# Usage:
#   pipeline-dag.sh init      <dag-path>
#   pipeline-dag.sh add-node  <dag-path> <node-id> <agent-type> [--label "..."] [--deps "a,b,c"]
#   pipeline-dag.sh ready     <dag-path>              # list nodes ready to run
#   pipeline-dag.sh start     <dag-path> <node-id>    # mark as running
#   pipeline-dag.sh complete  <dag-path> <node-id>    # mark as done
#   pipeline-dag.sh fail      <dag-path> <node-id> [reason]
#   pipeline-dag.sh skip      <dag-path> <node-id>    # mark as skipped (deps met but not needed)
#   pipeline-dag.sh status    <dag-path>              # show full state summary
#   pipeline-dag.sh viz       <dag-path>              # text visualization
#   pipeline-dag.sh template  <dag-path> <template>   # init from a named template
#
# Templates: minimal, standard, full-transformation

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
        cat > "$DAG_PATH" << EOF
{
  "version": 1,
  "created_at": "$TS",
  "updated_at": "$TS",
  "nodes": []
}
EOF
        echo "[pipeline-dag] ✅ Initialized: $DAG_PATH"
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
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --label) LABEL="${2:-$NODE_ID}"; shift 2 ;;
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

        jq --arg id "$NODE_ID" --arg agent "$AGENT" --arg label "$LABEL" --argjson deps "$DEPS" --arg t "$TS" \
            '.nodes += [{
                "id": $id,
                "agent": $agent,
                "label": $label,
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

    template)
        TEMPLATE="${3:-standard}"
        # Init first
        bash "$0" init "$DAG_PATH"

        case "$TEMPLATE" in
            minimal)
                bash "$0" add-node "$DAG_PATH" orchestrator orchestrator --label "Orchestrator"
                bash "$0" add-node "$DAG_PATH" brain-retrieval brain-data-retrieval --label "Brain Fetch" --deps "orchestrator"
                bash "$0" add-node "$DAG_PATH" specialist specialist --label "Specialist" --deps "brain-retrieval"
                bash "$0" add-node "$DAG_PATH" consolidation brain-consolidation --label "Brain Save" --deps "specialist"
                ;;
            standard)
                bash "$0" add-node "$DAG_PATH" orchestrator orchestrator --label "Orchestrator"
                bash "$0" add-node "$DAG_PATH" brain-retrieval brain-data-retrieval --label "Brain Fetch" --deps "orchestrator"
                bash "$0" add-node "$DAG_PATH" architect architect --label "Architecture" --deps "brain-retrieval"
                bash "$0" add-node "$DAG_PATH" security-arch security --label "Security Review" --deps "architect"
                bash "$0" add-node "$DAG_PATH" tech-lead tech-lead --label "Decompose" --deps "architect"
                bash "$0" add-node "$DAG_PATH" dev-a developer --label "Dev Unit A" --deps "tech-lead"
                bash "$0" add-node "$DAG_PATH" dev-b developer --label "Dev Unit B" --deps "tech-lead"
                bash "$0" add-node "$DAG_PATH" testing testing --label "Tests" --deps "dev-a,dev-b"
                bash "$0" add-node "$DAG_PATH" code-review code-reviewer --label "Code Review" --deps "testing,security-arch"
                bash "$0" add-node "$DAG_PATH" consolidation brain-consolidation --label "Brain Save" --deps "code-review"
                ;;
            full-transformation)
                bash "$0" add-node "$DAG_PATH" orchestrator orchestrator --label "Orchestrator"
                bash "$0" add-node "$DAG_PATH" brain-retrieval brain-data-retrieval --label "Brain Fetch" --deps "orchestrator"
                bash "$0" add-node "$DAG_PATH" product-mgr product-manager --label "Product Spec" --deps "brain-retrieval"
                bash "$0" add-node "$DAG_PATH" architect architect --label "Architecture" --deps "product-mgr"
                bash "$0" add-node "$DAG_PATH" security-arch security --label "Arch Security" --deps "architect"
                bash "$0" add-node "$DAG_PATH" tech-lead tech-lead --label "Decompose" --deps "architect"
                bash "$0" add-node "$DAG_PATH" dev-a developer --label "Dev Unit A" --deps "tech-lead"
                bash "$0" add-node "$DAG_PATH" dev-b developer --label "Dev Unit B" --deps "tech-lead"
                bash "$0" add-node "$DAG_PATH" dev-c developer --label "Dev Unit C" --deps "tech-lead"
                bash "$0" add-node "$DAG_PATH" testing qa-engineer --label "QA" --deps "dev-a,dev-b,dev-c"
                bash "$0" add-node "$DAG_PATH" security-code security --label "Code Security" --deps "dev-a,dev-b,dev-c"
                bash "$0" add-node "$DAG_PATH" code-review code-reviewer --label "Code Review" --deps "testing,security-code,security-arch"
                bash "$0" add-node "$DAG_PATH" devops devops --label "CI/CD" --deps "code-review"
                bash "$0" add-node "$DAG_PATH" docs documentation --label "Docs" --deps "code-review"
                bash "$0" add-node "$DAG_PATH" consolidation brain-consolidation --label "Brain Save" --deps "devops,docs"
                ;;
            *)
                echo "[pipeline-dag] ERROR: Unknown template '$TEMPLATE'. Options: minimal, standard, full-transformation" >&2
                exit 1
                ;;
        esac

        echo ""
        echo "[pipeline-dag] 📋 Template '$TEMPLATE' applied"
        bash "$0" status "$DAG_PATH"
        ;;

    *)
        echo "[pipeline-dag] ERROR: Unknown action '$ACTION'" >&2
        echo "Actions: init, add-node, ready, start, complete, fail, skip, status, viz, template" >&2
        exit 1
        ;;
esac
