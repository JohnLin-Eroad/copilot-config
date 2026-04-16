#!/usr/bin/env bash
# extract-service-data.sh — Extract structured data from an EROAD GitHub repo
#
# Usage:
#   bash extract-service-data.sh <service-name>
#   bash extract-service-data.sh replay-service
#
# Outputs JSON to stdout:
#   {
#     "service": "...",
#     "description": "...",
#     "owner": "...",
#     "system": "...",
#     "openapi": { endpoints: [...], schemas: {...} },
#     "tables": [ { name, columns: [...] } ],
#     "service_classes": [ { file, content_snippet } ],
#     "dependencies": [...],
#     "readme_excerpt": "..."
#   }

set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

SERVICE="${1:-}"
if [[ -z "$SERVICE" ]]; then
  echo "Usage: $0 <service-name>" >&2
  exit 1
fi

ORG="eroad"
REPO="$ORG/$SERVICE"
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

log() { echo "[extract] $*" >&2; }

# ─────────────────────────────────────────────────────────────
# 1. File tree
# ─────────────────────────────────────────────────────────────
log "Fetching file tree for $REPO..."
TREE_FILE="$TMP/tree.txt"
gh api "repos/$REPO/git/trees/HEAD?recursive=1" --jq '.tree[].path' > "$TREE_FILE" 2>/dev/null \
  || { echo '{"error":"repo not found or not accessible"}'; exit 0; }

# ─────────────────────────────────────────────────────────────
# 2. catalog-info.yaml → owner/system/domain
# ─────────────────────────────────────────────────────────────
OWNER=""
SYSTEM=""
DOMAIN=""
CATALOG_PATH=$(grep -m1 'catalog-info.yaml$' "$TREE_FILE" || true)
if [[ -n "$CATALOG_PATH" ]]; then
  log "Reading catalog-info.yaml..."
  CATALOG=$(gh api "repos/$REPO/contents/$CATALOG_PATH" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || true)
  OWNER=$(echo "$CATALOG" | grep 'owner:' | head -1 | sed 's/.*owner: *//' | tr -d '"' || true)
  SYSTEM=$(echo "$CATALOG" | grep 'system:' | head -1 | sed 's/.*system: *//' | tr -d '"' || true)
  DOMAIN=$(echo "$CATALOG" | grep 'domain:' | head -1 | sed 's/.*domain: *//' | tr -d '"' || true)
fi

# ─────────────────────────────────────────────────────────────
# 3. README.md — first 30 lines for description
# ─────────────────────────────────────────────────────────────
README_EXCERPT=""
README_PATH=$(grep -m1 '^README.md$' "$TREE_FILE" || true)
if [[ -n "$README_PATH" ]]; then
  log "Reading README..."
  README_EXCERPT=$(gh api "repos/$REPO/contents/$README_PATH" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null | head -30 | tr '`"\\' ' ' || true)
fi

# ─────────────────────────────────────────────────────────────
# 4. OpenAPI spec (api.json, api/*.json, *-api.json)
# ─────────────────────────────────────────────────────────────
ENDPOINTS_JSON="[]"
SCHEMAS_JSON="{}"
API_SPEC_PATH=""

# Priority: api.json at root > api/*.json > *-api.json > swagger.json
for pattern in "^api\.json$" "^api/[^/]*api[^/]*\.json$" "^[^/]*api\.json$" "^swagger\.json$"; do
  API_SPEC_PATH=$(grep -E "$pattern" "$TREE_FILE" | head -1 || true)
  [[ -n "$API_SPEC_PATH" ]] && break
done

if [[ -n "$API_SPEC_PATH" ]]; then
  log "Parsing OpenAPI spec at $API_SPEC_PATH..."
  gh api "repos/$REPO/contents/$API_SPEC_PATH" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null > "$TMP/api.json" || true

  if [[ -s "$TMP/api.json" ]]; then
    python3 - "$TMP/api.json" << 'PYEOF' > "$TMP/endpoints.json" 2>/dev/null || echo '[]' > "$TMP/endpoints.json"
import json, sys

with open(sys.argv[1]) as f:
    spec = json.load(f)

endpoints = []
paths = spec.get('paths', {})
for path, methods in paths.items():
    for method, op in methods.items():
        if method not in ('get', 'post', 'put', 'patch', 'delete', 'head'):
            continue
        # Extract request body fields
        req_fields = []
        req_body = op.get('requestBody', {})
        content = req_body.get('content', {})
        for ct, ct_val in content.items():
            schema = ct_val.get('schema', {})
            props = schema.get('properties', schema.get('items', {}).get('properties', {}))
            if props:
                req_fields = list(props.keys())[:15]  # cap at 15
                break

        # Extract response schema (200/201)
        resp_fields = []
        responses = op.get('responses', {})
        for code in ('200', '201'):
            resp = responses.get(code, {})
            content = resp.get('content', {})
            for ct, ct_val in content.items():
                schema = ct_val.get('schema', {})
                props = schema.get('properties', {})
                if not props:
                    items = schema.get('items', {})
                    props = items.get('properties', {})
                if props:
                    resp_fields = list(props.keys())[:15]
                    break
            if resp_fields:
                break

        # Extract path params
        params = [p.get('name') for p in op.get('parameters', []) if p.get('in') == 'path']

        endpoints.append({
            'method': method.upper(),
            'path': path,
            'summary': op.get('summary', ''),
            'description': (op.get('description') or '').strip(),
            'tags': op.get('tags', []),
            'path_params': params,
            'request_fields': req_fields,
            'response_fields': resp_fields,
        })

print(json.dumps(endpoints, indent=2))
PYEOF

    # Extract top-level schemas (models)
    python3 - "$TMP/api.json" << 'PYEOF' > "$TMP/schemas.json" 2>/dev/null || echo '{}' > "$TMP/schemas.json"
import json, sys

with open(sys.argv[1]) as f:
    spec = json.load(f)

# OpenAPI 3.x
components = spec.get('components', {})
schemas = components.get('schemas', {})
# OpenAPI 2.x
if not schemas:
    schemas = spec.get('definitions', {})

# Trim to just property names and types
slim = {}
for name, defn in list(schemas.items())[:30]:  # cap at 30 models
    props = defn.get('properties', {})
    slim[name] = {
        k: v.get('type', v.get('$ref', '?').split('/')[-1])
        for k, v in list(props.items())[:20]
    }

print(json.dumps(slim, indent=2))
PYEOF

    ENDPOINTS_JSON=$(cat "$TMP/endpoints.json")
    SCHEMAS_JSON=$(cat "$TMP/schemas.json")
  fi
fi

# ─────────────────────────────────────────────────────────────
# 5. Flyway SQL migrations → table schemas
# ─────────────────────────────────────────────────────────────
TABLES_JSON="[]"
# Find first Flyway migration file (V1__*.sql)
MIGRATION_PATH=$(grep -E 'V1__.*\.sql$' "$TREE_FILE" | head -1 || true)

if [[ -n "$MIGRATION_PATH" ]]; then
  log "Parsing Flyway schema from $MIGRATION_PATH..."
  gh api "repos/$REPO/contents/$MIGRATION_PATH" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null > "$TMP/schema.sql" || true

  if [[ -s "$TMP/schema.sql" ]]; then
    python3 << PYEOF > "$TMP/tables.json" 2>/dev/null || echo '[]' > "$TMP/tables.json"
import re, json

with open("$TMP/schema.sql") as f:
    sql = f.read()

tables = []
# Match CREATE TABLE blocks
blocks = re.finditer(
    r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?["\w.]+\.([\w"]+)\s*\((.*?)\);',
    sql, re.DOTALL | re.IGNORECASE
)
for match in blocks:
    tname = match.group(1).strip('"')
    body = match.group(2)
    columns = []
    for line in body.splitlines():
        line = line.strip().rstrip(',')
        if not line or line.upper().startswith(('CONSTRAINT', 'PRIMARY', 'UNIQUE', 'FOREIGN', 'INDEX', 'KEY', '--')):
            continue
        # Parse "col_name type [modifiers]"
        parts = line.split()
        if len(parts) >= 2:
            col = parts[0].strip('"')
            typ = parts[1].rstrip(',')
            nullable = 'NOT NULL' not in line.upper()
            columns.append({'name': col, 'type': typ, 'nullable': nullable})
    if columns:
        tables.append({'table': tname, 'columns': columns})

print(json.dumps(tables, indent=2))
PYEOF
    TABLES_JSON=$(cat "$TMP/tables.json")
  fi
fi

# ─────────────────────────────────────────────────────────────
# 6. Service layer Java — extract business logic signals
# ─────────────────────────────────────────────────────────────
SERVICE_CLASSES_JSON="[]"
SERVICE_FILES=$(grep -E 'Service\.java$' "$TREE_FILE" | grep -v 'Test' | head -6 || true)

if [[ -n "$SERVICE_FILES" ]]; then
  log "Sampling service layer Java files..."
  # Write file list to a temp file so Python reads it without shell interpolation issues
  echo "$SERVICE_FILES" > "$TMP/service_files.txt"
  python3 - "$TMP/service_files.txt" "$REPO" > "$TMP/service_classes.json" 2>/dev/null << 'PYEOF' || echo '[]' > "$TMP/service_classes.json"
import subprocess, json, re, sys, base64

with open(sys.argv[1]) as f:
    files = [l.strip() for l in f.readlines() if l.strip()]

repo = sys.argv[2]
results = []

for path in files[:4]:
    try:
        content_b64 = subprocess.check_output(
            ['gh', 'api', f'repos/{repo}/contents/{path}', '--jq', '.content'],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        content = base64.b64decode(content_b64).decode('utf-8', errors='replace')

        methods   = re.findall(r'(?:public|protected)\s+\w[\w<>,\s]*\s+(\w+)\s*\([^)]*\)', content)
        log_infos = re.findall(r'log\.info\("([^"]+)"', content)
        publishes = re.findall(r'(?:publish|send|emit|sendMessage)\s*\([^)]+\)', content)
        downstream = re.findall(r'(\w+(?:Api|Client|Service))\s*\.\s*(\w+)\s*\(', content)

        results.append({
            'file': path.split('/')[-1],
            'methods':         list(dict.fromkeys(methods))[:20],
            'log_infos':       list(dict.fromkeys(log_infos))[:15],
            'publishes':       list(dict.fromkeys([p[:120] for p in publishes]))[:10],
            'downstream_calls': list(dict.fromkeys([f'{c[0]}.{c[1]}' for c in downstream]))[:20],
            'imports_snippet': '\n'.join(content.splitlines()[:60]),
        })
    except Exception as e:
        results.append({'file': path, 'error': str(e)})

print(json.dumps(results, indent=2))
PYEOF
fi

# ─────────────────────────────────────────────────────────────
# 7. Assemble final JSON output (all via temp files — no shell interpolation of JSON)
# ─────────────────────────────────────────────────────────────
log "Assembling output..."

# Write metadata pieces to files so Python reads them, not shell-interpolates
echo "$SERVICE"          > "$TMP/meta_service.txt"
echo "$REPO"             > "$TMP/meta_repo.txt"
echo "$OWNER"            > "$TMP/meta_owner.txt"
echo "$SYSTEM"           > "$TMP/meta_system.txt"
echo "$DOMAIN"           > "$TMP/meta_domain.txt"
echo "$API_SPEC_PATH"    > "$TMP/meta_spec_path.txt"
printf '%s' "$README_EXCERPT" > "$TMP/meta_readme.txt"

# Ensure all JSON files exist
[[ -f "$TMP/endpoints.json" ]] || echo '[]' > "$TMP/endpoints.json"
[[ -f "$TMP/schemas.json" ]]   || echo '{}' > "$TMP/schemas.json"
[[ -f "$TMP/tables.json" ]]    || echo '[]' > "$TMP/tables.json"
[[ -f "$TMP/service_classes.json" ]] || echo '[]' > "$TMP/service_classes.json"

python3 - "$TMP" << 'PYEOF'
import json, sys, os

d = sys.argv[1]

def read(f): 
    with open(os.path.join(d, f)) as fh: return fh.read().strip()

def readjson(f):
    with open(os.path.join(d, f)) as fh: return json.load(fh)

endpoints = readjson('endpoints.json')
output = {
    "service":       read('meta_service.txt'),
    "repo":          "https://github.com/" + read('meta_repo.txt'),
    "owner":         read('meta_owner.txt'),
    "system":        read('meta_system.txt'),
    "domain":        read('meta_domain.txt'),
    "readme_excerpt": read('meta_readme.txt')[:600],
    "openapi": {
        "spec_path":      read('meta_spec_path.txt'),
        "endpoint_count": len(endpoints),
        "endpoints":      endpoints,
        "schemas":        readjson('schemas.json'),
    },
    "tables":          readjson('tables.json'),
    "service_classes": readjson('service_classes.json'),
}
print(json.dumps(output, indent=2))
PYEOF
