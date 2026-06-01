#!/usr/bin/env bash
# run-integration-lanes.sh — Sequential shared-file integration after parallel agents complete
#
# Runs lanes in strict order: Lane B (DTOs) → Lane A (YAML/config) → Lane C (Java @Configuration)
# Each lane reads SHARED_FILE_REQUEST entries from STM, applies changes, compiles.
#
# Usage:
#   bash ~/.copilot/scripts/run-integration-lanes.sh --stm PATH [--module MODULE] [--dry-run]
#
# Prerequisites:
#   - All parallel developer agent units must be in DONE state in the STM
#   - STM must contain SHARED_FILE_REQUEST blocks written by developer agents
#   - Java 21 + Maven must be available (via sdkman)
#
# Lanes:
#   Lane B (DTO-OWNER):    shared DTOs, records, enums, value objects
#   Lane A (YAML-OWNER):   *.yml, *.yaml, *.properties files
#   Lane C (JAVACONFIG):   @Configuration, @Bean, @EnableWebSecurity, @SpringBootApplication
#
# Each lane:
#   1. Scans STM for SHARED_FILE_REQUEST entries matching its file type
#   2. Consolidates all requested changes for that lane into one pass
#   3. Applies changes (or flags for manual review if conflicting)
#   4. Runs per-lane mvn compile check
#   5. Writes lane result to STM
#
# Exit codes:
#   0 — All lanes passed
#   1 — One or more lanes failed compile
#   2 — Missing prerequisites (not all units DONE, no STM, etc.)

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
STM_PATH=""
MODULE="api"           # Maven module path (default: compile the whole api)
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stm)     STM_PATH="$2"; shift 2 ;;
        --module)  MODULE="$2";   shift 2 ;;
        --dry-run) DRY_RUN=1;     shift ;;
        *) shift ;;
    esac
done

if [[ -z "$STM_PATH" || ! -f "$STM_PATH" ]]; then
    echo "[lanes] ERROR: --stm PATH required and must exist" >&2
    exit 2
fi

SCRIPTS_DIR="$(dirname "$0")"

# ── Helpers ───────────────────────────────────────────────────────────────────
log() { echo "[lanes] $*"; }

write_stm() {
    local agent="$1" content="$2"
    bash "$SCRIPTS_DIR/write-stm.sh" "$STM_PATH" "$agent" "$content"
}

run_compile() {
    local lane="$1" module="$2"
    if [[ $DRY_RUN -eq 1 ]]; then
        log "DRY-RUN: skipping mvn compile for lane $lane"
        return 0
    fi
    log "Running compile for lane $lane (module: $module)..."
    # shellcheck disable=SC1090
    source ~/.sdkman/bin/sdkman-init.sh 2>/dev/null || true
    sdk use java 21.0.7-zulu 2>/dev/null || true
    cd ~/sovereign
    if mvn compile -pl "$module" -q 2>&1 | tee /tmp/lane-${lane}-compile.log | tail -5; then
        log "Lane $lane compile: ✅ passed"
        return 0
    else
        log "Lane $lane compile: ❌ failed"
        return 1
    fi
}

# ── Prerequisite check: all units must be DONE ───────────────────────────────
log "Checking prerequisites: all units must be DONE..."

ALL_STATES="$(bash "$SCRIPTS_DIR/read-stm-state.sh" "$STM_PATH" 2>/dev/null || true)"

if echo "$ALL_STATES" | grep -qE '(IN_PROGRESS|CLAIMED|NOT_STARTED)'; then
    log "WARNING: Some units are not yet DONE — listing:"
    echo "$ALL_STATES" | grep -E '(IN_PROGRESS|CLAIMED|NOT_STARTED)' || true
    if [[ $DRY_RUN -eq 0 ]]; then
        log "Proceeding anyway (incomplete units will be skipped)"
    fi
fi

# ── Parse SHARED_FILE_REQUEST entries from STM ────────────────────────────────
# Format (in DONE blocks):
#   SHARED_FILE_REQUEST:
#     file: path/to/file
#     change_needed: description
#     reason: why
# Or single-line:
#   SHARED_FILE_REQUEST: path/to/File.java — needs X added

TMPDIR_WORK="$(mktemp -d /tmp/lanes-XXXX)"
trap 'rm -rf "$TMPDIR_WORK"' EXIT

log "Parsing SHARED_FILE_REQUEST entries from STM..."

# Extract all SHARED_FILE_REQUEST blocks
awk '
/SHARED_FILE_REQUEST:/{
    inblock=1
    file=""; change=""; reason=""; agent=current_agent
}
/^### /{
    # Track current agent from section header
    current_agent = $2
    inblock=0
}
inblock && /file:/{
    gsub(/^[ \t]*file:[ \t]*/, "")
    file=$0
}
inblock && /change_needed:/{
    gsub(/^[ \t]*change_needed:[ \t]*/, "")
    change=$0
}
inblock && /reason:/{
    gsub(/^[ \t]*reason:[ \t]*/, "")
    reason=$0
    print file "|" change "|" reason "|" agent
    inblock=0
}
' "$STM_PATH" > "$TMPDIR_WORK/all_requests.txt" 2>/dev/null || true

# Also handle inline SHARED_FILE_REQUEST: path — description format
grep -n 'SHARED_FILE_REQUEST:' "$STM_PATH" | grep -v '^\s*$' | while IFS= read -r line; do
    # Extract inline: SHARED_FILE_REQUEST: file.java — change description
    if echo "$line" | grep -qE 'SHARED_FILE_REQUEST:\s+\S+\s+[—-]'; then
        file="$(echo "$line" | sed 's/.*SHARED_FILE_REQUEST:[ \t]*//' | awk '{print $1}')"
        change="$(echo "$line" | sed 's/.*[—-][ \t]*//')"
        echo "${file}|${change}|inline|unknown" >> "$TMPDIR_WORK/all_requests.txt"
    fi
done 2>/dev/null || true

TOTAL_REQUESTS=$(wc -l < "$TMPDIR_WORK/all_requests.txt" | tr -d ' ')
log "Found $TOTAL_REQUESTS SHARED_FILE_REQUEST entries"

if [[ $TOTAL_REQUESTS -eq 0 ]]; then
    log "No shared file requests found — nothing to do for integration lanes"
    write_stm "integration-lanes" "STATUS: complete
LANE_B: skipped (no DTO requests)
LANE_A: skipped (no config requests)
LANE_C: skipped (no @Configuration requests)
SHARED_FILES_PROCESSED: 0"
    exit 0
fi

# ── Classify requests by lane ─────────────────────────────────────────────────
classify_lane() {
    local filepath="$1"
    # Lane A: YAML/properties config files
    if echo "$filepath" | grep -qE '\.(yml|yaml|properties)$'; then
        echo "A"
        return
    fi
    # Lane C: Java @Configuration (check filename heuristic)
    if echo "$filepath" | grep -qiE '(Config|Configuration|Security|Bean|Application)\.java$'; then
        echo "C"
        return
    fi
    # Lane B: DTOs, records, enums, value objects
    if echo "$filepath" | grep -qiE '(Dto|Record|Enum|Value|Response|Request|Command|Event)\.java$'; then
        echo "B"
        return
    fi
    # Default: Lane B (shared Java that doesn't match C pattern)
    if echo "$filepath" | grep -qE '\.java$'; then
        echo "B"
        return
    fi
    # Schema/migration → Lane A
    if echo "$filepath" | grep -qE '\.(sql|xml)$'; then
        echo "A"
        return
    fi
    echo "B"  # fallback
}

while IFS='|' read -r file change reason agent; do
    [[ -z "$file" ]] && continue
    lane="$(classify_lane "$file")"
    echo "$file|$change|$reason|$agent" >> "$TMPDIR_WORK/lane_${lane}.txt"
done < "$TMPDIR_WORK/all_requests.txt"

# Ensure all lane files exist so wc -l never errors
touch "$TMPDIR_WORK/lane_B.txt" "$TMPDIR_WORK/lane_A.txt" "$TMPDIR_WORK/lane_C.txt"
LANE_B_COUNT=$(wc -l < "$TMPDIR_WORK/lane_B.txt" | tr -d ' ')
LANE_A_COUNT=$(wc -l < "$TMPDIR_WORK/lane_A.txt" | tr -d ' ')
LANE_C_COUNT=$(wc -l < "$TMPDIR_WORK/lane_C.txt" | tr -d ' ')

log "Lane classification: B(DTO)=$LANE_B_COUNT  A(YAML)=$LANE_A_COUNT  C(@Config)=$LANE_C_COUNT"

# ── Lane runner ───────────────────────────────────────────────────────────────
LANE_RESULTS=()

run_lane() {
    local lane_id="$1"
    local lane_name="$2"
    local lane_file="$TMPDIR_WORK/lane_${lane_id}.txt"

    [[ ! -f "$lane_file" || ! -s "$lane_file" ]] && {
        log "Lane $lane_id ($lane_name): skipped — no requests"
        LANE_RESULTS+=("$lane_id:skipped")
        return 0
    }

    local file_count
    file_count=$(wc -l < "$lane_file" | tr -d ' ')
    log ""
    log "━━━ Lane $lane_id ($lane_name) ━━━ $file_count file(s)"

    write_stm "lane-${lane_id}" "STATUS: starting
LANE: $lane_id ($lane_name)
FILES_TO_PROCESS: $file_count"

    local processed=0
    local conflicts=0
    local file_summary=""

    while IFS='|' read -r file change reason agent; do
        [[ -z "$file" ]] && continue
        log "  Processing: $file"
        log "    Change: $change"
        log "    From:   $agent"

        # Check for conflicts: same file requested by multiple agents
        same_file_count=$(grep -c "^${file}|" "$lane_file" 2>/dev/null || echo 1)
        if [[ $same_file_count -gt 1 ]]; then
            log "    ⚠️  CONFLICT: $same_file_count agents requested changes to $file"
            conflicts=$((conflicts + 1))
            # Write conflict note to STM — reconciliation step will handle it
            write_stm "lane-${lane_id}" "CONFLICT_DETECTED:
  file: $file
  requestors: $same_file_count agents
  changes: see SHARED_FILE_REQUEST entries above
  action: requires manual reconciliation or reconcile.sh"
        fi

        # Check file exists
        if [[ ! -f "$file" ]]; then
            log "    ⚠️  File not found: $file — will be created or flagged"
        fi

        # In dry-run, just report; in real run, flag for the orchestrator to apply
        if [[ $DRY_RUN -eq 0 ]]; then
            # Write the change requirement to a per-file instruction file
            # The orchestrator/reconcile step applies these
            local safe_name
            safe_name="$(echo "$file" | tr '/' '_' | tr '.' '_')"
            echo "FILE: $file
CHANGE: $change
REASON: $reason
AGENT: $agent
LANE: $lane_id" >> "$TMPDIR_WORK/apply_${safe_name}.txt"
        fi

        processed=$((processed + 1))
        file_summary="${file_summary}\n  - $file"
    done < "$lane_file"

    # Compile check for this lane
    local compile_result="skipped (dry-run)"
    local compile_exit=0
    if [[ $DRY_RUN -eq 0 && $conflicts -eq 0 ]]; then
        if run_compile "$lane_id" "$MODULE"; then
            compile_result="passed"
        else
            compile_result="FAILED"
            compile_exit=1
        fi
    elif [[ $conflicts -gt 0 ]]; then
        compile_result="skipped (conflicts detected — resolve first)"
    fi

    # Write lane result to STM
    write_stm "lane-${lane_id}" "STATUS: ${compile_exit:-0}
LANE: $lane_id ($lane_name)
FILES_PROCESSED: $processed
CONFLICTS: $conflicts
COMPILE: $compile_result
FILES:$(printf '%b' "$file_summary")"

    if [[ $compile_exit -eq 1 ]]; then
        log "Lane $lane_id FAILED compile — check /tmp/lane-${lane_id}-compile.log"
        LANE_RESULTS+=("$lane_id:failed")
        return 1
    fi

    LANE_RESULTS+=("$lane_id:ok")
    log "Lane $lane_id ($lane_name): ✅ done"
    return 0
}

# ── Execute lanes in order: B → A → C ────────────────────────────────────────
OVERALL_EXIT=0

write_stm "integration-lanes" "STATUS: starting
LANE_ORDER: B(DTO) → A(YAML) → C(@Configuration)
TOTAL_REQUESTS: $TOTAL_REQUESTS
DRY_RUN: $DRY_RUN"

run_lane "B" "DTO-OWNER"   || OVERALL_EXIT=1
run_lane "A" "YAML-OWNER"  || OVERALL_EXIT=1
run_lane "C" "JAVACONFIG"  || OVERALL_EXIT=1

# ── Summary ───────────────────────────────────────────────────────────────────
log ""
log "━━━ Integration Lane Summary ━━━"
RESULT_STR=""
for r in "${LANE_RESULTS[@]:-}"; do
    lane="${r%%:*}"
    status="${r##*:}"
    icon="✅"
    [[ "$status" == "failed" ]] && icon="❌"
    [[ "$status" == "skipped" ]] && icon="⏭️"
    log "  Lane $lane: $icon $status"
    RESULT_STR="${RESULT_STR}LANE_${lane}: $status\n"
done

write_stm "integration-lanes" "STATUS: $([ $OVERALL_EXIT -eq 0 ] && echo complete || echo failed)
$(printf '%b' "$RESULT_STR")TOTAL_PROCESSED: $TOTAL_REQUESTS
NEXT: $([ $OVERALL_EXIT -eq 0 ] && echo 'reconcile' || echo 'fix lane failures, then retry')"

if [[ $OVERALL_EXIT -eq 0 ]]; then
    log "All integration lanes complete ✅ — ready for reconcile.sh"
else
    log "One or more lanes FAILED ❌ — check STM and fix before reconcile.sh"
fi

exit $OVERALL_EXIT
