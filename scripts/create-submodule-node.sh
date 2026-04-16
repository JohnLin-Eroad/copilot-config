#!/usr/bin/env bash
# create-submodule-node.sh — Create or update a submodule vault node
#
# Usage:
#   bash create-submodule-node.sh <repo-name> <submodule-name>
#   bash create-submodule-node.sh vehicle-service vehicle-ejb
#
# Creates: ~/eroad-brain/01 - Services/{repo}/{module}.md

set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

REPO="${1:-}"
MODULE="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "$REPO" || -z "$MODULE" ]]; then
  echo "Usage: $0 <repo-name> <submodule-name>" >&2
  exit 1
fi

BRAIN_DIR="$HOME/eroad-brain"
SUBDIR="$BRAIN_DIR/01 - Services/$REPO"
NODE="$SUBDIR/${MODULE}.md"
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

log() { echo "[create-sub] $*" >&2; }

mkdir -p "$SUBDIR"

# Extract submodule data
log "Extracting data for $REPO/$MODULE..."
bash "$SCRIPT_DIR/extract-submodule-data.sh" "$REPO" "$MODULE" > "$TMP/data.json" 2>/tmp/extract-sub-${REPO}-${MODULE}.log

# Generate the node
python3 - "$TMP/data.json" "$REPO" "$MODULE" "$NODE" << 'PYEOF'
import json, sys, os, re
from datetime import date

data_path  = sys.argv[1]
repo       = sys.argv[2]
module     = sys.argv[3]
node_path  = sys.argv[4]

with open(data_path) as f:
    d = json.load(f)

role        = d.get("role", "submodule")
description = d.get("description", "").strip()
endpoints   = d.get("openapi", {}).get("endpoints", [])
schemas     = d.get("openapi", {}).get("schemas", {})
tables      = d.get("tables", [])
classes     = d.get("service_classes", [])
deps        = d.get("dependencies", [])

# ── Module role descriptions (fallback only) ───────────────────────────────
ROLE_DESC = {
    "HTTP API / Entry Point":          "Exposes REST endpoints; the public-facing layer of the service.",
    "Business Logic (EJB)":            "Contains core business logic, transaction management, and domain services.",
    "Deployable EAR Assembly":         "Packages all EJB/WAR modules into a single deployable enterprise archive.",
    "Serverless Lambda Function":       "AWS Lambda function triggered by events or API Gateway.",
    "Event Processor / Consumer":       "Consumes messages from SQS/SNS/Kinesis and processes them.",
    "Integration Adapter":             "Adapts between EROAD's internal events and an external system's format.",
    "Event Publisher / Producer":      "Publishes domain events to a messaging bus (SQS/SNS/Kinesis).",
    "Domain Model Layer":              "Contains domain entities, value objects, and DTOs shared across modules.",
    "Event Handler":                   "Handles specific incoming events and delegates to business logic.",
    "Scheduled Job":                   "Runs on a schedule (cron/EventBridge) to perform periodic tasks.",
    "Aggregation Layer":               "Aggregates data from multiple sources into a consolidated view.",
    "Background Worker":               "Long-running background task processing items from a queue.",
    "Shared Library":                  "Shared utilities, helpers, or common code used across modules.",
    "Data Persistence Layer":          "JPA entities, repositories, and ORM configuration.",
    "submodule":                       "Submodule within the monorepo.",
}
# Use real description from README/pom if available, otherwise fall back to role description
role_desc = description if description else ROLE_DESC.get(role, "Submodule within the monorepo.")

# ── If node exists, read and preserve existing content ─────────────────────
existing = ""
if os.path.exists(node_path):
    with open(node_path) as f:
        existing = f.read()

# ── Build sections ─────────────────────────────────────────────────────────
lines = []

# Always write header (we always rewrite the full file)
lines.append(f"# {module}")
lines.append("")
lines.append(f"**Parent Repo:** [[{repo}]]  ")
lines.append(f"**Role:** {role}  ")
lines.append(f"**Description:** {role_desc}")
lines.append("")

# Domain Entities section
lines.append("## Domain Entities")
lines.append("")
if tables:
    for t in tables:
        cols = t.get("columns", [])
        lines.append(f"### `{t['name']}`")
        if cols:
            lines.append("| Column | Type |")
            lines.append("|--------|------|")
            for c in cols:
                lines.append(f"| `{c['name']}` | `{c['type']}` |")
        lines.append("")
elif schemas:
    for schema_name, props in list(schemas.items())[:8]:
        lines.append(f"### `{schema_name}`")
        if props:
            lines.append("**Fields:** " + ", ".join(f"`{p}`" for p in props[:12]))
        lines.append("")
else:
    lines.append("_No DB schema found — likely a library, client, or infrastructure module._")
    lines.append("")

# API Endpoints section
lines.append("## API Endpoints")
lines.append("")
if endpoints:
    lines.append("| Method | Path | Summary |")
    lines.append("|--------|------|---------|")
    for ep in endpoints[:30]:
        summary = ep.get("summary","").replace("|","/")[:80]
        lines.append(f"| `{ep['method']}` | `{ep['path']}` | {summary} |")
    lines.append("")
    # Workflow descriptions for key endpoints
    lines.append("### Key Endpoint Workflows")
    lines.append("")
    for ep in endpoints[:5]:
        method = ep.get("method","")
        path   = ep.get("path","")
        op_id  = ep.get("operationId","")
        summary = ep.get("summary","") or op_id
        lines.append(f"**{method} {path}**  ")
        if summary:
            lines.append(f"{summary}")
        lines.append("")
else:
    lines.append("_No OpenAPI spec found for this submodule._")
    lines.append("")

# Service Classes section
if classes:
    lines.append("## Key Classes")
    lines.append("")
    for c in classes:
        lines.append(f"- **`{c['file']}`** — {c.get('content_snippet','')[:120].strip()}")
    lines.append("")

# Dependencies section
lines.append("## Key Dependencies")
lines.append("")
if deps:
    for dep in deps:
        lines.append(f"- `{dep}`")
else:
    lines.append("_No notable service dependencies found._")
lines.append("")

# Tags / metadata footer
lines.append("---")
lines.append(f"*Submodule of [[{repo}]] · Auto-enriched {date.today().isoformat()}*")

new_sections = "\n".join(lines)

# If file exists, replace Domain Entities + API Endpoints sections
if existing:
    def replace_section(content, heading, new_body):
        # Find heading, replace until next ## heading
        pattern = rf'(## {re.escape(heading)}\n)(.*?)(?=\n## |\Z)'
        replacement = f'## {heading}\n{new_body}\n'
        result = re.sub(pattern, replacement, content, flags=re.S)
        if f'## {heading}' not in result:
            result = result.rstrip('\n') + f'\n\n## {heading}\n{new_body}\n'
        return result

    # For a new submodule node always write fresh
    with open(node_path, 'w') as f:
        f.write(new_sections + "\n")
else:
    with open(node_path, 'w') as f:
        f.write(new_sections + "\n")

ep_count  = len(endpoints)
tbl_count = len(tables)
dep_count = len(deps)
print(f"created: {ep_count} endpoints, {tbl_count} tables, {dep_count} deps → {node_path}")
PYEOF
