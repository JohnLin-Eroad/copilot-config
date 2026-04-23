#!/usr/bin/env bash
# decompose-task.sh — Score, partition, and assign files to parallel developer agents
#
# Usage:
#   bash ~/.copilot/scripts/decompose-task.sh [OPTIONS] [files...]
#
# Options:
#   --dir DIR           Score all Java/config files under DIR (e.g. src/)
#   --git-diff BRANCH   Score files changed vs BRANCH (default: HEAD~1)
#   --stm PATH          Write BUDGET_LEDGER_INIT block to STM after decomposition
#   --json              Output machine-readable JSON (default: pretty table)
#   --dry-run           Score and plan only — do not write to STM
#
# Examples:
#   # Score files in a git diff
#   bash decompose-task.sh --git-diff main --stm "$STM_PATH"
#
#   # Score explicit files
#   bash decompose-task.sh --stm "$STM_PATH" src/VehicleService.java src/VehicleRepository.java
#
#   # Score all changed Java files in a directory
#   bash decompose-task.sh --dir sovereign/api/src --stm "$STM_PATH"
#
# Complexity scoring formula (from design spec):
#   score = lines + (imports×2) + (public_methods×3) + (cyclomatic×5)
#         + config_file(+40) + schema_or_api_change(+50) + shared_file(+15 each)
#
# Agent allocation:
#   ≤300   → 1 agent   (budget: 12 calls)
#   301-600 → 2 agents  (budget: 12 each)
#   601-900 → 3 agents  (budget: 14 each)
#   901-1200→ 4 agents  (budget: 15 each)
#   >1200  → WARN: sequential phases recommended
#   Any single file scoring >200 → gets its own agent unit
#
# Use-case unit detection (heuristic, no Java parser required):
#   1. Java package path → use-case name (e.g. com.eroad.telematics.vehicle → "vehicle")
#   2. Config files grouped by directory proximity to use-case Java files
#   3. Files without a clear use-case → "shared" unit (queued for integration lanes)
#
# Output (default table):
#   UNIT | AGENT      | FILES | SCORE | BUDGET | TYPE
#   A    | developer-A | 3    | 187   | 12     | normal
#   B    | developer-B | 5    | 312   | 14     | normal
#   shared | (lane)   | 2    | -     | -      | shared-file
#
# Output (--json):
#   { "total_score": N, "regime": "NORMAL|DEGRADE", "units": [...], "shared_files": [...] }

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
DIR=""
GIT_DIFF=""
STM_PATH=""
OUTPUT_JSON=0
DRY_RUN=0
EXTRA_FILES=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)       DIR="$2";       shift 2 ;;
        --git-diff)  GIT_DIFF="$2";  shift 2 ;;
        --stm)       STM_PATH="$2";  shift 2 ;;
        --json)      OUTPUT_JSON=1;  shift ;;
        --dry-run)   DRY_RUN=1;      shift ;;
        -*)          echo "Unknown option: $1" >&2; exit 1 ;;
        *)           EXTRA_FILES+=("$1"); shift ;;
    esac
done

# ── File collection ───────────────────────────────────────────────────────────
FILES=()

if [[ -n "$GIT_DIFF" ]]; then
    while IFS= read -r f; do
        [[ -f "$f" ]] && FILES+=("$f")
    done < <(git diff --name-only "$GIT_DIFF" 2>/dev/null | grep -E '\.(java|kt|groovy|yml|yaml|properties|xml|json|sql)$' || true)
fi

if [[ -n "$DIR" && -d "$DIR" ]]; then
    while IFS= read -r f; do
        FILES+=("$f")
    done < <(find "$DIR" -type f \( -name "*.java" -o -name "*.kt" -o -name "*.yml" \
               -o -name "*.yaml" -o -name "*.properties" -o -name "*.xml" \
               -o -name "*.sql" \) 2>/dev/null | sort)
fi

for f in "${EXTRA_FILES[@]+"${EXTRA_FILES[@]}"}"; do
    [[ -f "$f" ]] && FILES+=("$f")
done

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "[decompose] ERROR: No files found to score. Use --dir, --git-diff, or pass file paths." >&2
    exit 1
fi

# ── Helpers ───────────────────────────────────────────────────────────────────

# Detect if a file is a "shared" file (used across multiple use-cases)
# Heuristic: common/ shared/ util/ dto/ model/ base/ at any path depth
is_shared_file() {
    local f="$1"
    echo "$f" | grep -qiE '/(common|shared|util(s)?|dto(s)?|model(s)?|base|core|exception|error|config)/' && return 0
    # Also: files that match @Configuration or @Bean patterns (Java config — goes to Lane C)
    if [[ "$f" =~ \.java$ ]]; then
        grep -qE '@(Configuration|Bean|EnableWebSecurity|SpringBootApplication)' "$f" 2>/dev/null && return 0
    fi
    return 1
}

# Detect if file is a config file (yml/yaml/properties → Lane A, sql → schema)
is_config_file() {
    [[ "$1" =~ \.(yml|yaml|properties)$ ]] && return 0
    return 1
}

# Detect schema/API change markers
is_schema_or_api() {
    local f="$1"
    [[ "$f" =~ \.(sql)$ ]] && return 0
    [[ "$f" =~ (migration|schema|flyway|liquibase|V[0-9]) ]] && return 0
    if [[ "$f" =~ \.java$ ]]; then
        grep -qE '@(RestController|RequestMapping|PostMapping|GetMapping|PutMapping|DeleteMapping|Entity|Table|Column|ManyToOne|OneToMany)' "$f" 2>/dev/null && return 0
    fi
    return 1
}

# Extract use-case name from file path
# com/eroad/telematics/vehicle/VehicleService.java → "vehicle"
# com/eroad/sovereign/compliance/... → "compliance"
infer_use_case() {
    local f="$1"
    # Try Java package depth: take the component after the org prefix (eroad/sovereign/X)
    local uc
    uc="$(echo "$f" | grep -oE '(com|org|io)/[a-z]+/[a-z]+/([a-z_]+)/' | tail -1 | awk -F'/' '{print $4}' || true)"
    if [[ -z "$uc" ]]; then
        # Fallback: parent directory name
        uc="$(dirname "$f" | xargs basename 2>/dev/null || echo "misc")"
    fi
    echo "${uc:-misc}"
}

# Score a single file
score_file() {
    local f="$1"
    local score=0

    if [[ ! -f "$f" ]]; then
        echo "0"
        return
    fi

    # lines_changed
    local lines
    lines="$(wc -l < "$f" 2>/dev/null || echo 0)"
    score=$((score + lines))

    # imports × 2  (Java/Kotlin)
    if [[ "$f" =~ \.(java|kt)$ ]]; then
        local imports=0 methods=0 cyclo=0
        # grep -c prints "0" on no-match then exits 1; use || true to avoid double-printing
        { imports=$(grep -c '^import ' "$f" 2>/dev/null); } || true
        imports=${imports:-0}
        score=$((score + imports * 2))

        # public methods × 3
        { methods=$(grep -cE '^\s*(public|protected)\s+\S.*\(.*\)\s*(\{|throws)' "$f" 2>/dev/null); } || true
        methods=${methods:-0}
        score=$((score + methods * 3))

        # cyclomatic complexity proxy × 5 (if/else/for/while/switch/case/catch/ternary)
        { cyclo=$(grep -cE '\b(if|else if|for|while|switch|case|catch)' "$f" 2>/dev/null); } || true
        cyclo=${cyclo:-0}
        score=$((score + cyclo * 5))
    fi

    # config file bonus
    if is_config_file "$f"; then
        score=$((score + 40))
    fi

    # schema/API change bonus
    if is_schema_or_api "$f"; then
        score=$((score + 50))
    fi

    echo "$score"
}

# Agent budget from total score
budget_for_score() {
    local s="$1"
    if   [[ $s -le 300  ]]; then echo 12
    elif [[ $s -le 600  ]]; then echo 12
    elif [[ $s -le 900  ]]; then echo 14
    elif [[ $s -le 1200 ]]; then echo 15
    else echo 15
    fi
}

# Number of agents from total score
agents_for_score() {
    local s="$1"
    if   [[ $s -le 300  ]]; then echo 1
    elif [[ $s -le 600  ]]; then echo 2
    elif [[ $s -le 900  ]]; then echo 3
    elif [[ $s -le 1200 ]]; then echo 4
    else echo 4   # >1200: warn about sequential phases
    fi
}

# Letter label for unit index
unit_label() {
    local idx="$1"
    echo "ABCDEFGHIJKLMNOP" | cut -c$((idx+1)) 2>/dev/null || echo "U$idx"
}

# ── Score all files ───────────────────────────────────────────────────────────
# Output: FILE SCORE USE_CASE IS_SHARED IS_CONFIG
declare -a FILE_LIST SCORE_LIST UC_LIST SHARED_LIST TYPE_LIST

for f in "${FILES[@]}"; do
    s="$(score_file "$f")"
    uc="$(infer_use_case "$f")"
    shared="0"
    ftype="normal"
    if is_shared_file "$f"; then
        shared="1"
        ftype="shared"
    elif is_config_file "$f"; then
        ftype="config"
    fi

    FILE_LIST+=("$f")
    SCORE_LIST+=("$s")
    UC_LIST+=("$uc")
    SHARED_LIST+=("$shared")
    TYPE_LIST+=("$ftype")
done

TOTAL_FILES=${#FILE_LIST[@]}

# ── Group non-shared files by use-case ───────────────────────────────────────
# Build use-case → file list mapping (using temp files to avoid bash 3.2 assoc arrays)
TMPDIR_WORK="$(mktemp -d /tmp/decompose-XXXX)"
trap 'rm -rf "$TMPDIR_WORK"' EXIT

for i in $(seq 0 $((TOTAL_FILES - 1))); do
    f="${FILE_LIST[$i]}"
    s="${SCORE_LIST[$i]}"
    shared="${SHARED_LIST[$i]}"
    uc="${UC_LIST[$i]}"

    if [[ "$shared" == "1" ]]; then
        echo "$f $s" >> "$TMPDIR_WORK/shared_files.txt"
    else
        echo "$f $s" >> "$TMPDIR_WORK/uc_${uc}.txt"
    fi
done

# Collect use-case names (unique, sorted)
UC_NAMES=()
if ls "$TMPDIR_WORK"/uc_*.txt 2>/dev/null | head -1 >/dev/null; then
    while IFS= read -r ucfile; do
        ucname="$(basename "$ucfile" .txt | sed 's/^uc_//')"
        UC_NAMES+=("$ucname")
    done < <(ls "$TMPDIR_WORK"/uc_*.txt 2>/dev/null | sort)
fi

# ── Score per use-case, detect files that should be isolated ─────────────────
declare -a UNIT_UC UNIT_FILES UNIT_SCORES UNIT_FILE_COUNT
UNIT_IDX=0

for uc in "${UC_NAMES[@]}"; do
    ucfile="$TMPDIR_WORK/uc_${uc}.txt"
    [[ -f "$ucfile" ]] || continue

    # Score for this use-case
    uc_score=0
    uc_files=()
    big_files=()  # files scoring >200 alone — get own unit

    while IFS=' ' read -r ff fs; do
        if [[ -n "$ff" ]]; then
            if [[ $fs -gt 200 ]]; then
                big_files+=("$ff $fs")
            else
                uc_files+=("$ff")
                uc_score=$((uc_score + fs))
            fi
        fi
    done < "$ucfile"

    # Files scoring >200 alone get their own unit
    for bigentry in "${big_files[@]:-}"; do
        [[ -z "$bigentry" ]] && continue
        bf="$(echo "$bigentry" | awk '{print $1}')"
        bs="$(echo "$bigentry" | awk '{print $2}')"
        label="$(unit_label $UNIT_IDX)"
        UNIT_UC+=("${uc}-isolated")
        UNIT_FILES+=("$bf")
        UNIT_SCORES+=("$bs")
        UNIT_FILE_COUNT+=(1)
        UNIT_IDX=$((UNIT_IDX + 1))
        # Write individual file list
        echo "$bf" > "$TMPDIR_WORK/unit_${label}.files"
    done

    # Remaining use-case files as one unit
    if [[ ${#uc_files[@]} -gt 0 ]]; then
        label="$(unit_label $UNIT_IDX)"
        UNIT_UC+=("$uc")
        UNIT_FILES+=("$(IFS=','; echo "${uc_files[*]}")")
        UNIT_SCORES+=("$uc_score")
        UNIT_FILE_COUNT+=(${#uc_files[@]})
        UNIT_IDX=$((UNIT_IDX + 1))
        printf '%s\n' "${uc_files[@]}" > "$TMPDIR_WORK/unit_${label}.files"
    fi
done

TOTAL_UNITS=${#UNIT_SCORES[@]}

# Total score (sum of unit scores only, not shared)
TOTAL_SCORE=0
for s in "${UNIT_SCORES[@]:-0}"; do TOTAL_SCORE=$((TOTAL_SCORE + s)); done

NUM_AGENTS="$(agents_for_score $TOTAL_SCORE)"
PER_AGENT_BUDGET="$(budget_for_score $TOTAL_SCORE)"
REGIME="NORMAL"
[[ $TOTAL_SCORE -gt 1200 ]] && REGIME="WARN_SEQUENTIAL"

# ── Shared file count ─────────────────────────────────────────────────────────
SHARED_COUNT=0
SHARED_FILES_LIST=""
if [[ -f "$TMPDIR_WORK/shared_files.txt" ]]; then
    SHARED_COUNT="$(wc -l < "$TMPDIR_WORK/shared_files.txt" | tr -d ' ')"
    SHARED_FILES_LIST="$(awk '{print $1}' "$TMPDIR_WORK/shared_files.txt" | tr '\n' ',')"
fi

# ── Output ────────────────────────────────────────────────────────────────────
if [[ $OUTPUT_JSON -eq 1 ]]; then
    # JSON output
    echo "{"
    echo "  \"total_score\": $TOTAL_SCORE,"
    echo "  \"total_files\": $TOTAL_FILES,"
    echo "  \"num_agents\": $NUM_AGENTS,"
    echo "  \"per_agent_budget\": $PER_AGENT_BUDGET,"
    echo "  \"regime\": \"$REGIME\","
    echo "  \"units\": ["
    for i in $(seq 0 $((TOTAL_UNITS - 1))); do
        label="$(unit_label $i)"
        sep=","
        [[ $i -eq $((TOTAL_UNITS - 1)) ]] && sep=""
        echo "    {\"unit\": \"$label\", \"use_case\": \"${UNIT_UC[$i]}\", \"score\": ${UNIT_SCORES[$i]}, \"file_count\": ${UNIT_FILE_COUNT[$i]}, \"budget\": $PER_AGENT_BUDGET, \"agent\": \"developer-$(echo $label | tr 'A-Z' 'a-z')\"}$sep"
    done
    echo "  ],"
    echo "  \"shared_files\": \"$SHARED_FILES_LIST\","
    echo "  \"shared_file_count\": $SHARED_COUNT"
    echo "}"
else
    # Pretty table
    echo ""
    echo "┌─────────────────────────────────────────────────────────────┐"
    echo "│            TASK DECOMPOSITION RESULT                       │"
    echo "└─────────────────────────────────────────────────────────────┘"
    echo ""
    printf "  Total score   : %d\n" "$TOTAL_SCORE"
    printf "  Files scored  : %d  (shared: %d)\n" "$TOTAL_FILES" "$SHARED_COUNT"
    printf "  Agents needed : %d\n" "$NUM_AGENTS"
    printf "  Budget/agent  : %d tool calls\n" "$PER_AGENT_BUDGET"
    printf "  Regime        : %s\n" "$REGIME"
    echo ""

    if [[ $TOTAL_UNITS -gt 0 ]]; then
        printf "  %-6s %-24s %-8s %-8s %-24s\n" "UNIT" "USE-CASE" "FILES" "SCORE" "AGENT"
        printf "  %-6s %-24s %-8s %-8s %-24s\n" "------" "------------------------" "--------" "--------" "------------------------"
        for i in $(seq 0 $((TOTAL_UNITS - 1))); do
            label="$(unit_label $i)"
            printf "  %-6s %-24s %-8s %-8s %-24s\n" \
                "$label" \
                "${UNIT_UC[$i]:0:24}" \
                "${UNIT_FILE_COUNT[$i]}" \
                "${UNIT_SCORES[$i]}" \
                "developer-$(echo "$label" | tr 'A-Z' 'a-z')"
        done
    else
        echo "  (no non-shared units found)"
    fi

    if [[ $SHARED_COUNT -gt 0 ]]; then
        echo ""
        printf "  %-6s %-24s %-8s %-8s %-24s\n" "shared" "integration-lanes" "$SHARED_COUNT" "-" "(Lane B/A/C)"
        echo ""
        echo "  Shared files (→ integration lanes):"
        if [[ -f "$TMPDIR_WORK/shared_files.txt" ]]; then
            awk '{printf "    %s  (score: %s)\n", $1, $2}' "$TMPDIR_WORK/shared_files.txt"
        fi
    fi

    if [[ "$REGIME" == "WARN_SEQUENTIAL" ]]; then
        echo ""
        echo "  ⚠️  Score >1200: consider breaking into sequential phases"
        echo "     Phase 1: units A-B, Phase 2: units C-D (after A-B DONE)"
    fi
    echo ""
fi

# ── Write BUDGET_LEDGER_INIT to STM ──────────────────────────────────────────
if [[ -n "$STM_PATH" && $DRY_RUN -eq 0 ]]; then
    LEDGER_BLOCK="## [BUDGET_LEDGER]
total_budget: 180
total_score: $TOTAL_SCORE
regime: $REGIME
global_calls_used: 0
global_calls_remaining: 180
units:"

    for i in $(seq 0 $((TOTAL_UNITS - 1))); do
        label="$(unit_label $i)"
        LEDGER_BLOCK="${LEDGER_BLOCK}
  - unit: $label
    use_case: ${UNIT_UC[$i]}
    agent: developer-$(echo "$label" | tr 'A-Z' 'a-z')
    allocated: $PER_AGENT_BUDGET
    used: 0
    state: NOT_STARTED
    file_count: ${UNIT_FILE_COUNT[$i]}"
    done

    LEDGER_BLOCK="${LEDGER_BLOCK}
shared_files: $SHARED_COUNT"

    bash "$(dirname "$0")/write-stm.sh" "$STM_PATH" "decompose-task" "$LEDGER_BLOCK"
    echo "[decompose] ✅ BUDGET_LEDGER_INIT written to STM"
fi
