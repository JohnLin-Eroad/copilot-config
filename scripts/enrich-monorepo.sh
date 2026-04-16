#!/usr/bin/env bash
# enrich-monorepo.sh — For a monorepo, detect submodules and create vault sub-nodes
#
# Usage:
#   bash enrich-monorepo.sh <repo-name>
#   bash enrich-monorepo.sh vehicle-service
#
# Steps:
#   1. Fetches file tree and detects submodules (dirs with their own pom.xml or package.json)
#   2. Filters out non-deployable modules (-migration, -client, -model, -test, etc.)
#   3. Creates/updates ~/eroad-brain/01 - Services/{repo}/{module}.md for each
#   4. Updates parent vault node with ## Submodules section

set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

REPO="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "$REPO" ]]; then
  echo "Usage: $0 <repo-name>" >&2
  exit 1
fi

BRAIN_DIR="$HOME/eroad-brain"
PARENT_NODE="$BRAIN_DIR/01 - Services/${REPO}.md"
SUBDIR="$BRAIN_DIR/01 - Services/$REPO"
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

log() { echo "[enrich-mono] $*" >&2; }

# ─────────────────────────────────────────────────────────────
# 1. Fetch file tree
# ─────────────────────────────────────────────────────────────
log "Fetching file tree for eroad/$REPO..."
gh api "repos/eroad/$REPO/git/trees/HEAD?recursive=1" --jq '.tree[].path' > "$TMP/tree.txt" 2>/dev/null \
  || { log "ERROR: Cannot access repo eroad/$REPO"; exit 1; }

# ─────────────────────────────────────────────────────────────
# 2. Detect submodules (dirs with pom.xml at depth=1 OR JS workspace packages)
# ─────────────────────────────────────────────────────────────
# Maven: {module}/pom.xml at depth 1
MAVEN_MODULES=$(grep -E '^[^/]+/pom\.xml$' "$TMP/tree.txt" | sed 's|/pom.xml||' | sort -u || true)
# JS workspaces: packages/{module}/package.json or apps/{module}/package.json
JS_MODULES=$(grep -E '^(packages|apps|services)/[^/]+/package\.json$' "$TMP/tree.txt" | sed 's|/package.json||' | sed 's|^[^/]*/||' | sort -u || true)

# Combine
ALL_MODULES=$(echo -e "$MAVEN_MODULES\n$JS_MODULES" | grep -v '^$' | sort -u)

if [[ -z "$ALL_MODULES" ]]; then
  log "No submodules detected for $REPO"
  exit 0
fi

MODULE_COUNT=$(echo "$ALL_MODULES" | wc -l | tr -d ' ')
log "Found $MODULE_COUNT submodules"

# ─────────────────────────────────────────────────────────────
# 3. Filter to deployable/meaningful modules
# ─────────────────────────────────────────────────────────────
SKIP_PATTERNS="-migration|-client|-model|-test|-load-test|integration-test|-jacoco|-test-helper|-test-support|codecov|coverage|load-test-tool|-thin-client|-wsclient|-client-swagger|-test$|-tests$|-performance-test|-component-test"

DEPLOYABLE_MODULES=$(echo "$ALL_MODULES" | grep -vE "($SKIP_PATTERNS)" || true)

if [[ -z "$DEPLOYABLE_MODULES" ]]; then
  log "No deployable submodules after filtering (all are clients/migrations/tests)"
  exit 0
fi

DEP_COUNT=$(echo "$DEPLOYABLE_MODULES" | wc -l | tr -d ' ')
log "Deployable submodules: $DEP_COUNT"
echo "$DEPLOYABLE_MODULES" | while read m; do log "  → $m"; done

# ─────────────────────────────────────────────────────────────
# 4. Create submodule nodes in parallel
# ─────────────────────────────────────────────────────────────
mkdir -p "$SUBDIR"
PIDS=()
RESULTS=()

while IFS= read -r module; do
  [[ -z "$module" ]] && continue
  (
    result=$(bash "$SCRIPT_DIR/create-submodule-node.sh" "$REPO" "$module" 2>/tmp/sub-${REPO}-${module}.log)
    echo "OK:$module:$result"
  ) &
  PIDS+=($!)
done <<< "$DEPLOYABLE_MODULES"

# Wait for all
FAILED=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || ((FAILED++)) || true
done

log "All submodule nodes created ($FAILED failures)"

# ─────────────────────────────────────────────────────────────
# 5. Update parent vault node with ## Submodules section
# ─────────────────────────────────────────────────────────────
if [[ -f "$PARENT_NODE" ]]; then
  log "Updating parent node with submodule links..."
  python3 - "$PARENT_NODE" "$REPO" "$SUBDIR" << 'PYEOF'
import sys, os, re

parent_path = sys.argv[1]
repo        = sys.argv[2]
subdir      = sys.argv[3]

with open(parent_path) as f:
    content = f.read()

# List all created submodule nodes
nodes = sorted(
    f[:-3] for f in os.listdir(subdir)
    if f.endswith(".md") and not f.endswith(".bak")
)

if not nodes:
    sys.exit(0)

# Build ## Submodules section
lines = ["## Submodules", ""]
lines.append(f"This is a monorepo containing **{len(nodes)} deployable submodules**:")
lines.append("")
for n in nodes:
    lines.append(f"- [[{repo}/{n}|{n}]]")
lines.append("")
submodules_section = "\n".join(lines)

# Replace or append
pattern = r'## Submodules\n.*?(?=\n## |\Z)'
if re.search(pattern, content, re.S):
    content = re.sub(pattern, submodules_section.rstrip('\n'), content, flags=re.S)
else:
    # Insert after first ## section or at end
    insert_after = re.search(r'\n## ', content)
    if insert_after:
        pos = insert_after.start()
        content = content[:pos] + "\n\n" + submodules_section + content[pos:]
    else:
        content = content.rstrip('\n') + "\n\n" + submodules_section

with open(parent_path, 'w') as f:
    f.write(content)

print(f"Updated {parent_path} with {len(nodes)} submodule links")
PYEOF
fi

log "Done: $REPO → $DEP_COUNT submodule nodes in $SUBDIR"
