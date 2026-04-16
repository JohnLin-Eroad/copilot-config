#!/usr/bin/env bash
# enrich-service-node.sh — Enrich an eroad-brain service vault node
#
# Usage:
#   bash enrich-service-node.sh <service-name> [--dry-run]
#
# Steps:
#   1. Runs extract-service-data.sh to get structured JSON from GitHub
#   2. Reads the existing vault node
#   3. Generates enriched sections (Domain Entities, API Endpoints with workflows)
#   4. Writes back the updated vault node
#
# Requires: gh CLI, python3, jq

set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

SERVICE="${1:-}"
DRY_RUN="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "$SERVICE" ]]; then
  echo "Usage: $0 <service-name> [--dry-run]" >&2
  exit 1
fi

BRAIN_DIR="$HOME/Library/Group Containers/UBF8T346G9.OneDriveStandaloneSuite/OneDrive - EROAD.noindex/OneDrive - EROAD/Documents/eroad-brain"
VAULT_NODE="$BRAIN_DIR/01 - Services/${SERVICE}.md"
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

log() { echo "[enrich] $*" >&2; }
die() { echo "[enrich] ERROR: $*" >&2; exit 1; }

[[ -f "$VAULT_NODE" ]] || die "Vault node not found: $VAULT_NODE"

# ─────────────────────────────────────────────────────────────
# 1. Extract data from GitHub
# ─────────────────────────────────────────────────────────────
log "Extracting data from GitHub for $SERVICE..."
bash "$SCRIPT_DIR/extract-service-data.sh" "$SERVICE" > "$TMP/data.json" 2>/tmp/extract-${SERVICE}.log

if python3 -c "import json,sys; d=json.load(open('$TMP/data.json')); sys.exit(0 if 'openapi' in d else 1)" 2>/dev/null; then
  log "Extraction complete ($(python3 -c "import json; d=json.load(open('$TMP/data.json')); print(d['openapi']['endpoint_count'], 'endpoints,', len(d['tables']), 'tables,', len(d['service_classes']), 'service classes')") )"
else
  die "Extraction failed — see /tmp/extract-${SERVICE}.log"
fi

# ─────────────────────────────────────────────────────────────
# 2. Generate enriched vault sections via Python
# ─────────────────────────────────────────────────────────────
log "Generating enriched vault sections..."
python3 - "$TMP/data.json" "$VAULT_NODE" "$TMP/enriched.md" << 'PYEOF'
import json, sys, re
from datetime import datetime

data_path = sys.argv[1]
vault_path = sys.argv[2]
output_path = sys.argv[3]

with open(data_path) as f:
    d = json.load(f)

with open(vault_path) as f:
    original = f.read()

svc      = d['service']
owner    = d.get('owner', '')
system   = d.get('system', '')
domain   = d.get('domain', '')
tables   = d.get('tables', [])
endpoints = d['openapi']['endpoints']
schemas  = d['openapi']['schemas']
service_classes = d.get('service_classes', [])
readme   = d.get('readme_excerpt', '')

today = datetime.now().strftime('%Y-%m-%d')

# ─── Domain Entities section ───────────────────────────────
def build_entities_section(tables, schemas):
    lines = ['## Domain Entities', '']
    if not tables and not schemas:
        lines += ['_No database schema detected._', '']
        return '\n'.join(lines)

    for t in tables:
        lines.append(f'### `{t["table"]}` table')
        lines.append('')
        lines.append('| Column | Type | Nullable |')
        lines.append('|--------|------|----------|')
        for col in t['columns']:
            nullable = '✓' if col.get('nullable', True) else ''
            lines.append(f'| `{col["name"]}` | `{col["type"]}` | {nullable} |')
        lines.append('')

    # Also show API schema models if no DB tables
    if not tables and schemas:
        lines.append('### API Models')
        lines.append('')
        for model_name, fields in list(schemas.items())[:8]:
            lines.append(f'**{model_name}**: {", ".join(f"`{k}`" for k in list(fields.keys())[:12])}')
        lines.append('')

    return '\n'.join(lines)

# ─── Build downstream dependencies from service classes ────
def extract_deps(service_classes):
    deps = set()
    for sc in service_classes:
        for call in sc.get('downstream_calls', []):
            svc_ref = call.split('.')[0]
            # Filter to meaningful external service refs
            if svc_ref not in ('log', 'LOGGER', 'mapper', 'Mapper', 'result', 'response', 'request', 'Optional', 'List', 'Arrays', 'Collections'):
                deps.add(svc_ref)
    return sorted(deps)

# ─── Build workflow context from service classes ────────────
def build_workflow_context(endpoint, service_classes):
    """Synthesize workflow signals for an endpoint from service layer code."""
    path = endpoint['path']
    method = endpoint['method']
    desc = endpoint.get('description', '')
    tags = endpoint.get('tags', [])

    # Find relevant service methods by matching path segments against method names
    path_words = set(re.sub(r'[{}]', '', path).replace('/', ' ').replace('-', ' ').lower().split())

    relevant_methods = []
    relevant_logs = []
    relevant_publishes = []
    relevant_downstream = []

    for sc in service_classes:
        for m in sc.get('methods', []):
            m_lower = m.lower()
            if any(w in m_lower for w in path_words if len(w) > 3):
                relevant_methods.append(m)
        for l in sc.get('log_infos', []):
            l_lower = l.lower()
            if any(w in l_lower for w in path_words if len(w) > 3):
                relevant_logs.append(l)
        relevant_publishes.extend(sc.get('publishes', []))
        relevant_downstream.extend(sc.get('downstream_calls', []))

    return {
        'relevant_methods': relevant_methods[:5],
        'relevant_logs': relevant_logs[:5],
        'publishes': list(set(relevant_publishes))[:5],
        'downstream': list(set(relevant_downstream))[:8],
    }

# ─── API Endpoints section ──────────────────────────────────
def build_endpoints_section(endpoints, service_classes, schemas):
    lines = ['## API Endpoints', '']

    if not endpoints:
        lines += ['_No API endpoints detected._', '']
        return '\n'.join(lines)

    # Group by tag
    by_tag = {}
    for ep in endpoints:
        tag = ep['tags'][0] if ep['tags'] else 'General'
        by_tag.setdefault(tag, []).append(ep)

    for tag, eps in by_tag.items():
        lines.append(f'### {tag}')
        lines.append('')
        for ep in eps:
            method = ep['method']
            path = ep['path']
            desc = ep.get('description', '').strip()
            req_fields = ep.get('request_fields', [])
            resp_fields = ep.get('response_fields', [])
            path_params = ep.get('path_params', [])

            lines.append(f'**`{method} {path}`**')
            if desc:
                lines.append(f'> {desc}')
            lines.append('')

            # Workflow context
            wf = build_workflow_context(ep, service_classes)

            # Build workflow description
            workflow_parts = []
            if wf['downstream']:
                ds = [x for x in wf['downstream'] if not x.startswith(('log', 'LOGGER', 'mapper', 'result'))]
                if ds:
                    workflow_parts.append(f"Calls downstream: {', '.join(ds[:4])}.")
            if req_fields:
                workflow_parts.append(f"Accepts: {', '.join(f'`{f}`' for f in req_fields[:8])}.")
            if resp_fields:
                workflow_parts.append(f"Returns: {', '.join(f'`{f}`' for f in resp_fields[:8])}.")
            if wf['relevant_logs']:
                workflow_parts.append(f"Key operations: {'; '.join(wf['relevant_logs'][:2])}.")

            if workflow_parts:
                lines.append('*Workflow:* ' + ' '.join(workflow_parts))
                lines.append('')

            if path_params:
                lines.append(f'*Path params:* {", ".join(f"`{p}`" for p in path_params)}')
                lines.append('')

        lines.append('')

    return '\n'.join(lines)

# ─── Build the full enriched node ──────────────────────────
entities_section  = build_entities_section(tables, schemas)
endpoints_section = build_endpoints_section(endpoints, service_classes, schemas)
deps              = extract_deps(service_classes)

# ─── Update/inject sections into existing vault node ────────
def replace_or_append_section(content, section_name, new_section):
    """Replace an existing section or append if not found."""
    pattern = rf'^## {re.escape(section_name)}.*?(?=^## |\Z)'
    replacement = new_section.rstrip() + '\n\n'
    updated = re.sub(pattern, replacement, content, flags=re.MULTILINE | re.DOTALL)
    if updated == content:
        # Section not found — append before last section or at end
        updated = content.rstrip() + '\n\n' + new_section + '\n'
    return updated

# Update last_synced in frontmatter
updated = re.sub(r'last_synced: ".*?"', f'last_synced: "{today}"', original)

# Inject/replace Domain Entities
updated = replace_or_append_section(updated, 'Domain Entities', entities_section)

# Inject/replace API Endpoints
updated = replace_or_append_section(updated, 'API Endpoints', endpoints_section)

# Inject/replace Key Dependencies if we found any
if deps:
    dep_section = '## Key Dependencies\n\n' + '\n'.join(f'- `{d}`' for d in deps) + '\n'
    updated = replace_or_append_section(updated, 'Key Dependencies', dep_section)

# Update owner/system in Architecture section if found
if owner and system:
    updated = re.sub(r'\*\*Owner:\*\*.*', f'**Owner:** {owner}', updated)
    updated = re.sub(r'\*\*System:\*\*.*', f'**System:** {system}', updated)

with open(output_path, 'w') as f:
    f.write(updated)

print(f"enriched: {len(endpoints)} endpoints, {len(tables)} tables, {len(deps)} deps")
PYEOF

RESULT=$(python3 -c "
import sys
with open('$TMP/enriched.md') as f: content = f.read()
wc = len(content.split())
print(f'Generated {wc} words ({len(content)} chars)')
")
log "$RESULT"

# ─────────────────────────────────────────────────────────────
# 3. Write back (or dry-run)
# ─────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == "--dry-run" ]]; then
  log "DRY RUN — output written to: $TMP/enriched.md"
  log "Preview (first 80 lines):"
  head -80 "$TMP/enriched.md" >&2
  # Copy to a persistent location for inspection
  cp "$TMP/enriched.md" "/tmp/enrich-dry-run-${SERVICE}.md"
  log "Full output saved to: /tmp/enrich-dry-run-${SERVICE}.md"
else
  cp "$VAULT_NODE" "${VAULT_NODE}.bak"
  cp "$TMP/enriched.md" "$VAULT_NODE"
  log "✓ Vault node updated: $VAULT_NODE"
  log "  Backup saved: ${VAULT_NODE}.bak"

  # Log the enrichment
  bash "$SCRIPT_DIR/add-learning.sh" --global "[WORKFLOW] Enriched $SERVICE vault node with $(python3 -c "import json; d=json.load(open('$TMP/data.json')); print(d['openapi']['endpoint_count'], 'endpoints +', len(d['tables']), 'tables')")" 2>/dev/null || true
fi

log "Done."
