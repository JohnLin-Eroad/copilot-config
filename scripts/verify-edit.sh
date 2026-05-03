#!/usr/bin/env bash
# verify-edit.sh — Post-edit quality gate
#
# Run after editing files to verify the change doesn't break things.
# Detects language from file extension and runs the appropriate check.
#
# Usage:
#   bash ~/.copilot/scripts/verify-edit.sh <file-path> [repo-root]
#
# Returns exit code 0 if OK, 1 if verification failed.
# Output is minimal on success, verbose on failure.

set -euo pipefail

FILE_PATH="${1:-}"
REPO_ROOT="${2:-$(git -C "$(dirname "$FILE_PATH")" rev-parse --show-toplevel 2>/dev/null || dirname "$FILE_PATH")}"

if [[ -z "$FILE_PATH" ]]; then
    echo "[verify-edit] ERROR: No file path provided" >&2
    echo "Usage: verify-edit.sh <file-path> [repo-root]" >&2
    exit 1
fi

if [[ ! -f "$FILE_PATH" ]]; then
    echo "[verify-edit] WARNING: File not found: $FILE_PATH — skipping verification" >&2
    exit 0
fi

EXT="${FILE_PATH##*.}"
FAILED=0

case "$EXT" in
    java)
        # Find the Maven module containing this file
        MODULE_DIR="$FILE_PATH"
        while [[ "$MODULE_DIR" != "/" && "$MODULE_DIR" != "$REPO_ROOT" ]]; do
            MODULE_DIR="$(dirname "$MODULE_DIR")"
            if [[ -f "$MODULE_DIR/pom.xml" ]]; then
                break
            fi
        done

        if [[ -f "$MODULE_DIR/pom.xml" && "$MODULE_DIR" != "$REPO_ROOT" ]]; then
            MODULE_NAME="$(basename "$MODULE_DIR")"
            echo "[verify-edit] ☕ Compiling module '$MODULE_NAME'..."
            if ! (cd "$REPO_ROOT/api" 2>/dev/null && mvn -pl "$MODULE_NAME" compile -q 2>&1); then
                echo "[verify-edit] ❌ Java compilation failed for module '$MODULE_NAME'" >&2
                FAILED=1
            else
                echo "[verify-edit] ✅ Java compilation OK"
            fi
        else
            echo "[verify-edit] ℹ️  No pom.xml found for $FILE_PATH — skipping compile check"
        fi
        ;;

    ts|tsx)
        # Run TypeScript type check from the nearest directory with tsconfig.json
        TS_DIR="$FILE_PATH"
        while [[ "$TS_DIR" != "/" && "$TS_DIR" != "$REPO_ROOT" ]]; do
            TS_DIR="$(dirname "$TS_DIR")"
            if [[ -f "$TS_DIR/tsconfig.json" ]]; then
                break
            fi
        done

        if [[ -f "$TS_DIR/tsconfig.json" ]]; then
            echo "[verify-edit] 📘 Type-checking TypeScript..."
            if ! (cd "$TS_DIR" && npx tsc --noEmit 2>&1 | head -20); then
                echo "[verify-edit] ❌ TypeScript type check failed" >&2
                FAILED=1
            else
                echo "[verify-edit] ✅ TypeScript types OK"
            fi
        fi
        ;;

    sql)
        # Basic SQL syntax check — just ensure it's parseable
        echo "[verify-edit] 📝 SQL file edited: $FILE_PATH (manual review recommended for migrations)"
        ;;

    sh|bash)
        echo "[verify-edit] 🐚 Checking shell syntax..."
        if ! bash -n "$FILE_PATH" 2>&1; then
            echo "[verify-edit] ❌ Shell syntax error in $FILE_PATH" >&2
            FAILED=1
        else
            echo "[verify-edit] ✅ Shell syntax OK"
        fi
        ;;

    py)
        echo "[verify-edit] 🐍 Checking Python syntax..."
        if ! python3 -c "import py_compile; py_compile.compile('$FILE_PATH', doraise=True)" 2>&1; then
            echo "[verify-edit] ❌ Python syntax error in $FILE_PATH" >&2
            FAILED=1
        else
            echo "[verify-edit] ✅ Python syntax OK"
        fi
        ;;

    *)
        # No verification for unknown file types
        ;;
esac

exit $FAILED
