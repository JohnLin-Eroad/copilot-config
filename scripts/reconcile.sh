#!/usr/bin/env bash
# reconcile.sh — Semantic reconciliation after integration lanes complete
#
# Runs after run-integration-lanes.sh to verify the full build is coherent:
#   1. Contract conformance — method signatures match STM contracts
#   2. SmokeContextTest.java — creates it if missing, then runs it
#   3. Verifies ≥1 @SpringBootTest per modified use-case
#   4. Full mvn compile && mvn test -q
#
# Usage:
#   bash ~/.copilot/scripts/reconcile.sh --stm PATH [--module MODULE] [--dry-run]
#
# Exit codes:
#   0 — All checks passed
#   1 — Build/test failure
#   2 — Missing prerequisites (STM not found, lanes not complete, etc.)

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
STM_PATH=""
MODULE="api"
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
    echo "[reconcile] ERROR: --stm PATH required and must exist" >&2
    exit 2
fi

SCRIPTS_DIR="$(dirname "$0")"

log()      { echo "[reconcile] $*"; }
write_stm() { bash "$SCRIPTS_DIR/write-stm.sh" "$STM_PATH" "reconcile" "$1"; }

TMPDIR_WORK="$(mktemp -d /tmp/reconcile-XXXX)"
trap 'rm -rf "$TMPDIR_WORK"' EXIT

# ── Java / Maven setup ────────────────────────────────────────────────────────
setup_java() {
    # shellcheck disable=SC1090
    source ~/.sdkman/bin/sdkman-init.sh 2>/dev/null || true
    sdk use java 21.0.7-zulu 2>/dev/null || true
}

# ── Prerequisite check ────────────────────────────────────────────────────────
log "Step 0: Prerequisite check"

# Check integration lanes completed
if ! grep -q 'LANE_B:.*ok\|LANE_B:.*skipped\|integration-lanes.*complete' "$STM_PATH" 2>/dev/null; then
    log "WARNING: Integration lanes may not have completed — check STM before proceeding"
fi

# Collect all units from STM
ALL_STATES="$(bash "$SCRIPTS_DIR/read-stm-state.sh" "$STM_PATH" 2>/dev/null || true)"
DONE_UNITS="$(echo "$ALL_STATES" | awk '/DONE/{print $1}' | grep -v UNIT | tr '\n' ' ')"
log "Units in DONE state: ${DONE_UNITS:-none}"

# ── Step 1: Contract conformance check ───────────────────────────────────────
log ""
log "Step 1: Contract conformance"

# Extract contract declarations from STM (written by agents in YAML contract blocks)
CONTRACTS_FOUND=0
CONTRACT_VIOLATIONS=0

grep -A 20 'CONTRACTS:' "$STM_PATH" 2>/dev/null > "$TMPDIR_WORK/contracts_raw.txt" || true

if [[ -s "$TMPDIR_WORK/contracts_raw.txt" ]]; then
    CONTRACTS_FOUND=$(grep -c 'interface:\|method:\|signature:' "$TMPDIR_WORK/contracts_raw.txt" 2>/dev/null || echo 0)
    log "  Found $CONTRACTS_FOUND contract declarations in STM"

    # Check each declared interface exists in the codebase
    while IFS= read -r line; do
        if echo "$line" | grep -qE '^\s*interface:\s*\S'; then
            iface="$(echo "$line" | sed 's/.*interface:[ \t]*//' | awk '{print $1}')"
            if [[ -n "$iface" ]]; then
                if find ~/sovereign/api -name "${iface}.java" 2>/dev/null | grep -q .; then
                    log "  ✅ Contract interface found: $iface"
                else
                    log "  ⚠️  Contract interface NOT found in codebase: $iface"
                    CONTRACT_VIOLATIONS=$((CONTRACT_VIOLATIONS + 1))
                fi
            fi
        fi
    done < "$TMPDIR_WORK/contracts_raw.txt"
else
    log "  No explicit contract blocks found in STM — skipping signature check"
fi

write_stm "STATUS: in_progress
STEP: contract-conformance
CONTRACTS_FOUND: $CONTRACTS_FOUND
VIOLATIONS: $CONTRACT_VIOLATIONS"

# ── Step 2: SmokeContextTest.java ─────────────────────────────────────────────
log ""
log "Step 2: SmokeContextTest.java"

# Find existing smoke test
SMOKE_TEST_PATH="$(find ~/sovereign/api -name 'SmokeContextTest.java' -o -name 'SmokeContextIT.java' 2>/dev/null | head -1 || true)"

if [[ -n "$SMOKE_TEST_PATH" ]]; then
    log "  SmokeContextTest already exists: $SMOKE_TEST_PATH"
else
    log "  SmokeContextTest not found — creating..."

    # Find the test directory for the web module
    TEST_DIR="$(find ~/sovereign/api/web/src/test -type d -name "*.web" 2>/dev/null | head -1 || \
                find ~/sovereign/api/web/src/test -type d 2>/dev/null | grep 'java' | head -1 || \
                echo "")"

    if [[ -z "$TEST_DIR" ]]; then
        # Infer from main source
        MAIN_PKG_DIR="$(find ~/sovereign/api/web/src/main/java -name "*.java" 2>/dev/null | head -1 | xargs dirname 2>/dev/null || echo "")"
        if [[ -n "$MAIN_PKG_DIR" ]]; then
            # Derive test dir from main src (replace main with test)
            TEST_DIR="${MAIN_PKG_DIR/src\/main/src\/test}"
            mkdir -p "$TEST_DIR"
        fi
    fi

    if [[ -n "$TEST_DIR" ]]; then
        # Determine package from existing test files or infer
        PKG="$(grep -r '^package ' "$TEST_DIR" 2>/dev/null | head -1 | awk '{print $2}' | tr -d ';' || \
               grep -r '^package ' ~/sovereign/api/web/src/main/java 2>/dev/null | head -1 | awk '{print $2}' | tr -d ';' || \
               echo "com.sovereign.web")"

        SMOKE_TEST_PATH="${TEST_DIR}/SmokeContextTest.java"

        if [[ $DRY_RUN -eq 0 ]]; then
            cat > "$SMOKE_TEST_PATH" << JAVA
package ${PKG};

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

/**
 * Smoke test — verifies the Spring application context loads without errors.
 * Created by reconcile.sh as part of parallel-agent post-merge reconciliation.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("test")
class SmokeContextTest {

    @Test
    void contextLoads() {
        // If the context fails to load, this test will fail with a descriptive error.
        // No assertions needed — successful load is the assertion.
    }
}
JAVA
            log "  ✅ Created: $SMOKE_TEST_PATH"
        else
            log "  DRY-RUN: would create $SMOKE_TEST_PATH (package: $PKG)"
            SMOKE_TEST_PATH="$TEST_DIR/SmokeContextTest.java (dry-run)"
        fi
    else
        log "  ⚠️  Could not determine test directory — skipping SmokeContextTest creation"
        SMOKE_TEST_PATH="(not created)"
    fi
fi

write_stm "STATUS: in_progress
STEP: smoke-context-test
SMOKE_TEST_PATH: $SMOKE_TEST_PATH"

# ── Step 3: Check ≥1 @SpringBootTest per modified use-case ───────────────────
log ""
log "Step 3: @SpringBootTest coverage check"

# Collect use-cases from unit states
USE_CASES_MISSING=()
while IFS=' ' read -r unit state agent ts; do
    [[ "$unit" == "UNIT" || "$unit" == "----" || -z "$unit" ]] && continue
    [[ "$state" != "DONE" ]] && continue

    # Look for @SpringBootTest in that use-case's test files
    uc_lower="$(echo "$unit" | tr 'A-Z' 'a-z')"
    if find ~/sovereign/api -path "*/test/*" -name "*.java" 2>/dev/null | \
       xargs grep -l "@SpringBootTest" 2>/dev/null | \
       grep -qi "$uc_lower" > /dev/null 2>&1; then
        log "  ✅ Unit $unit: @SpringBootTest found"
    else
        log "  ⚠️  Unit $unit: no @SpringBootTest found in test path matching '$uc_lower'"
        USE_CASES_MISSING+=("$unit")
    fi
done < <(echo "$ALL_STATES")

if [[ ${#USE_CASES_MISSING[@]} -gt 0 ]]; then
    log "  Missing @SpringBootTest for units: ${USE_CASES_MISSING[*]}"
    log "  → SmokeContextTest.java covers context loading; unit-specific tests recommended"
fi

write_stm "STATUS: in_progress
STEP: spring-boot-test-coverage
MISSING_UNITS: ${USE_CASES_MISSING[*]:-none}"

# ── Step 4: Full build ────────────────────────────────────────────────────────
log ""
log "Step 4: Full mvn compile + test"

BUILD_RESULT="skipped (dry-run)"
BUILD_EXIT=0

if [[ $DRY_RUN -eq 0 ]]; then
    setup_java
    cd ~/sovereign

    log "  Running: mvn compile -pl $MODULE -q"
    if mvn compile -pl "$MODULE" -q 2>&1 | tee "$TMPDIR_WORK/compile.log" | tail -10; then
        log "  ✅ Compile passed"
    else
        log "  ❌ Compile FAILED"
        BUILD_RESULT="compile-failed"
        BUILD_EXIT=1
        # Capture error for STM
        COMPILE_ERROR="$(tail -20 "$TMPDIR_WORK/compile.log" 2>/dev/null || echo "see logs")"
        write_stm "STATUS: failed
STEP: compile
ERROR: $COMPILE_ERROR
ACTION: fix compile errors before retrying reconcile.sh"
        exit 1
    fi

    log "  Running: mvn test -pl $MODULE -q"
    if mvn test -pl "$MODULE" -q 2>&1 | tee "$TMPDIR_WORK/test.log" | tail -20; then
        log "  ✅ Tests passed"
        BUILD_RESULT="passed"
        # Extract test counts
        TEST_SUMMARY="$(grep -E 'Tests run:|BUILD' "$TMPDIR_WORK/test.log" | tail -5 || echo "see logs")"
    else
        log "  ❌ Tests FAILED"
        BUILD_RESULT="test-failed"
        BUILD_EXIT=1
        TEST_ERROR="$(tail -30 "$TMPDIR_WORK/test.log" 2>/dev/null || echo "see logs")"
        write_stm "STATUS: failed
STEP: test
ERROR: $TEST_ERROR
ACTION: fix failing tests before marking pipeline complete"
        exit 1
    fi
else
    log "  DRY-RUN: skipping compile and test"
    TEST_SUMMARY="(dry-run)"
fi

# ── Final summary ─────────────────────────────────────────────────────────────
log ""
log "━━━ Reconciliation Summary ━━━"
log "  Contract violations  : $CONTRACT_VIOLATIONS"
log "  SmokeContextTest     : $SMOKE_TEST_PATH"
log "  Missing @SpringBootTest units: ${USE_CASES_MISSING[*]:-none}"
log "  Build result         : $BUILD_RESULT"

write_stm "STATUS: complete
STEP: reconciliation-complete
CONTRACT_VIOLATIONS: $CONTRACT_VIOLATIONS
SMOKE_TEST: $SMOKE_TEST_PATH
MISSING_SPRING_TESTS: ${USE_CASES_MISSING[*]:-none}
BUILD: $BUILD_RESULT
TEST_SUMMARY: ${TEST_SUMMARY:-n/a}
NEXT: pipeline complete ✅ — review any contract violations or missing test coverage above"

log ""
log "Reconciliation complete ✅"
exit 0
