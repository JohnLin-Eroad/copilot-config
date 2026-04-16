#!/usr/bin/env bash
# extract-submodule-data.sh — Extract data for a specific submodule within a monorepo
#
# Usage:
#   bash extract-submodule-data.sh <repo-name> <submodule-name>
#   bash extract-submodule-data.sh vehicle-service vehicle-ejb
#
# Outputs JSON to stdout

set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

REPO_NAME="${1:-}"
MODULE="${2:-}"
if [[ -z "$REPO_NAME" || -z "$MODULE" ]]; then
  echo "Usage: $0 <repo-name> <submodule-name>" >&2
  exit 1
fi

ORG="eroad"
REPO="$ORG/$REPO_NAME"
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

log() { echo "[extract-sub] $*" >&2; }

# ─────────────────────────────────────────────────────────────
# 1. File tree (reuse or fetch)
# ─────────────────────────────────────────────────────────────
TREE_FILE="$TMP/tree.txt"
gh api "repos/$REPO/git/trees/HEAD?recursive=1" --jq '.tree[].path' > "$TREE_FILE" 2>/dev/null \
  || { echo '{"error":"repo not found"}'; exit 0; }

# ─────────────────────────────────────────────────────────────
# 2. Infer module role from name suffix
# ─────────────────────────────────────────────────────────────
ROLE="submodule"
case "$MODULE" in
  *-war|*-api|*-server)     ROLE="HTTP API / Entry Point" ;;
  *-ejb)                    ROLE="Business Logic (EJB)" ;;
  *-ear)                    ROLE="Deployable EAR Assembly" ;;
  *-lambda)                 ROLE="Serverless Lambda Function" ;;
  *-processor|*-consumer)   ROLE="Event Processor / Consumer" ;;
  *-adapter)                ROLE="Integration Adapter" ;;
  *-publisher|*-producer)   ROLE="Event Publisher / Producer" ;;
  *-domain)                 ROLE="Domain Model Layer" ;;
  *-handler)                ROLE="Event Handler" ;;
  *-scheduler)              ROLE="Scheduled Job" ;;
  *-aggregate)              ROLE="Aggregation Layer" ;;
  *-worker)                 ROLE="Background Worker" ;;
  *-common|*-lib|*-util*)   ROLE="Shared Library" ;;
  *-orm|*-persistence)      ROLE="Data Persistence Layer" ;;
esac

# ─────────────────────────────────────────────────────────────
# 3. README and pom description for real human-readable description
# ─────────────────────────────────────────────────────────────
DESCRIPTION=""

# Write README extractor to temp file (avoids backtick bash-interpolation in -c strings)
cat > "$TMP/readme_extract.py" << 'PYEOF'
import sys, re
lines = sys.stdin.read().splitlines()
text = []
for l in lines:
    stripped = l.strip()
    if stripped.startswith('#') or stripped.startswith('```') or stripped.startswith('|'):
        if text: break
        continue
    # Skip badge/image lines (start with [ or ![ or contain shield.io/badge URLs)
    if stripped.startswith('[!') or stripped.startswith('[![') or stripped.startswith('!['):
        continue
    if stripped:
        text.append(stripped)
    elif text:
        break
print(' '.join(text)[:400])
PYEOF

# Try submodule README first
README_PATH=$(grep -E "^${MODULE}/README(\.[Mm][Dd])?$" "$TREE_FILE" | head -1 || true)
if [[ -n "$README_PATH" ]]; then
  DESCRIPTION=$(gh api "repos/$REPO/contents/$README_PATH" --jq '.content' 2>/dev/null \
    | base64 -d 2>/dev/null | head -20 | python3 "$TMP/readme_extract.py" 2>/dev/null || true)
fi

# Fall back to pom.xml <description>
if [[ -z "$DESCRIPTION" ]]; then
  POM_PATH2=$(grep -E "^${MODULE}/pom\.xml$" "$TREE_FILE" | head -1 || true)
  if [[ -n "$POM_PATH2" ]]; then
    DESCRIPTION=$(gh api "repos/$REPO/contents/$POM_PATH2" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null \
      | python3 -c 'import sys,re; m=re.search(r"<description>([^<]{10,})</description>",sys.stdin.read()); print(m.group(1).strip()[:300]) if m else print("")' \
      2>/dev/null || true)
  fi
fi

# Fall back to Javadoc on the main service/handler/lambda class
if [[ -z "$DESCRIPTION" ]]; then
  cat > "$TMP/javadoc_extract.py" << 'PYEOF'
import sys, re
src = sys.stdin.read()
# Find class-level Javadoc: /** ... */ immediately before public class/interface
matches = re.findall(r'/\*\*(.*?)\*/\s*(?:@\w+[^\n]*\n)*\s*(?:public|abstract)\s+(?:class|interface|enum)\s+\w', src, re.S)
if matches:
    doc = matches[0]
    # Strip leading * from each line, collapse whitespace
    lines = [re.sub(r'^\s*\*\s?', '', l).strip() for l in doc.splitlines()]
    text = ' '.join(l for l in lines if l and not l.startswith('@'))
    print(text[:350])
else:
    print('')
PYEOF
  MAIN_JAVA=$(grep -E "^${MODULE}/src/main/java/.*/(Service|Handler|Lambda|Processor|Consumer|Adapter|Resource|Controller)\w*\.java$" \
    "$TREE_FILE" | head -1 || \
    grep -E "^${MODULE}/src/main/java/.*\w+(Service|Handler|Lambda|Processor|Consumer|Adapter|Resource|Controller)\.java$" \
    "$TREE_FILE" | head -1 || true)
  if [[ -n "$MAIN_JAVA" ]]; then
    DESCRIPTION=$(gh api "repos/$REPO/contents/$MAIN_JAVA" --jq '.content' 2>/dev/null \
      | base64 -d 2>/dev/null | python3 "$TMP/javadoc_extract.py" 2>/dev/null || true)
  fi
fi

# Final fallback: root README first paragraph (relevant to whole repo, still useful)
if [[ -z "$DESCRIPTION" ]]; then
  DESCRIPTION=$(gh api "repos/$REPO/readme" --jq '.content' 2>/dev/null \
    | base64 -d 2>/dev/null | head -30 | python3 "$TMP/readme_extract.py" 2>/dev/null || true)
fi

# ─────────────────────────────────────────────────────────────
# 4. OpenAPI spec within submodule
# ─────────────────────────────────────────────────────────────
ENDPOINTS_JSON="[]"
SCHEMAS_JSON="{}"

for pattern in \
  "^${MODULE}/api\.json$" \
  "^${MODULE}/src/main/resources/api\.json$" \
  "^${MODULE}/src/main/resources/api/[^/]*\.json$" \
  "^${MODULE}/swagger\.json$" \
  "^${MODULE}/src/main/resources/swagger\.json$"; do
  API_PATH=$(grep -E "$pattern" "$TREE_FILE" | head -1 || true)
  [[ -n "$API_PATH" ]] && break
done

if [[ -n "${API_PATH:-}" ]]; then
  log "Found API spec at $API_PATH"
  API_CONTENT=$(gh api "repos/$REPO/contents/$API_PATH" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || true)
  if [[ -n "$API_CONTENT" ]]; then
    ENDPOINTS_JSON=$(echo "$API_CONTENT" | python3 -c "
import json,sys
try:
  spec=json.load(sys.stdin)
  paths=spec.get('paths',{})
  eps=[]
  for path,methods in paths.items():
    for method,op in methods.items():
      if method in ('get','post','put','patch','delete','options'):
        eps.append({'method':method.upper(),'path':path,
          'summary':op.get('summary',op.get('description',''))[:120],
          'operationId':op.get('operationId','')})
  print(json.dumps(eps))
except: print('[]')
" 2>/dev/null || echo "[]")
    SCHEMAS_JSON=$(echo "$API_CONTENT" | python3 -c "
import json,sys
try:
  spec=json.load(sys.stdin)
  comp=spec.get('components',spec.get('definitions',{}))
  schemas=comp.get('schemas',comp) if isinstance(comp,dict) else {}
  print(json.dumps({k:list(v.get('properties',{}).keys()) for k,v in list(schemas.items())[:15]}))
except: print('{}')
" 2>/dev/null || echo "{}")
  fi
fi

# ─────────────────────────────────────────────────────────────
# 4. Flyway migrations within submodule
# ─────────────────────────────────────────────────────────────
TABLES_JSON="[]"
FLYWAY_FILES=$(grep -E "^${MODULE}/.*/(V[^/]+\.sql|base/V[0-9]+.*\.sql)$" "$TREE_FILE" | head -5 || true)

if [[ -n "$FLYWAY_FILES" ]]; then
  TABLES_JSON=$(echo "$FLYWAY_FILES" | while IFS= read -r sql_path; do
    gh api "repos/$REPO/contents/$sql_path" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || true
  done | python3 -c "
import sys,re,json
sql=sys.stdin.read()
tables={}
for m in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"\''\`]?(\w+)[\"\''\`]?\s*\(([^;]{0,3000})',sql,re.I|re.S):
  name,body=m.group(1),m.group(2)
  cols=[]
  for cm in re.finditer(r'^\s+[\"\''\`]?(\w+)[\"\''\`]?\s+([\w]+(?:\([^)]+\))?)',body,re.M):
    col,typ=cm.group(1),cm.group(2)
    if col.upper() not in ('PRIMARY','UNIQUE','INDEX','KEY','CONSTRAINT','CHECK','FOREIGN'):
      cols.append({'name':col,'type':typ.upper()})
  if name.upper() not in ('INDEX','UNIQUE','PRIMARY','CONSTRAINT','IF') and cols:
    tables[name]=cols[:20]
print(json.dumps([{'name':k,'columns':v} for k,v in list(tables.items())[:10]]))
" 2>/dev/null || echo "[]")
fi

# ─────────────────────────────────────────────────────────────
# 5. Service/Controller Java classes within submodule
# ─────────────────────────────────────────────────────────────
SVC_CLASSES_JSON="[]"
JAVA_FILES=$(grep -E "^${MODULE}/src/main/java/.*/(.*Service|.*Controller|.*Resource|.*Handler|.*Lambda|.*Processor|.*Consumer|.*Adapter)\.java$" "$TREE_FILE" | head -8 || true)

if [[ -n "$JAVA_FILES" ]]; then
  SVC_CLASSES_JSON=$(echo "$JAVA_FILES" | while IFS= read -r java_path; do
    content=$(gh api "repos/$REPO/contents/$java_path" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null | head -60 || true)
    class=$(basename "$java_path" .java)
    echo "CLASS:$class"
    echo "$content" | grep -E '(class |@RestController|@Service|@Component|@Named|public.*method|void handle|public.*process)' | head -5
    echo "---"
  done | python3 -c "
import sys,re,json
text=sys.stdin.read()
classes=[]
for block in text.split('---'):
  if 'CLASS:' in block:
    name=re.search(r'CLASS:(\S+)',block)
    if name:
      snippet=block.replace('CLASS:'+name.group(1),'').strip()[:200]
      classes.append({'file':name.group(1),'content_snippet':snippet})
print(json.dumps(classes[:8]))
" 2>/dev/null || echo "[]")
fi

# ─────────────────────────────────────────────────────────────
# 6. pom.xml dependencies for this submodule
# ─────────────────────────────────────────────────────────────
DEPS_JSON="[]"
POM_PATH=$(grep -E "^${MODULE}/pom\.xml$" "$TREE_FILE" | head -1 || true)
if [[ -n "$POM_PATH" ]]; then
  DEPS_JSON=$(gh api "repos/$REPO/contents/$POM_PATH" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null | python3 -c "
import sys,re,json
pom=sys.stdin.read()
deps=[]
for m in re.finditer(r'<artifactId>([\w\-]+(?:-service|-api|-client|-gateway|-core|-common|-bus|-queue|-topic)[^<]*)</artifactId>',pom):
  a=m.group(1)
  if a not in deps and 'plugin' not in a: deps.append(a)
print(json.dumps(deps[:15]))
" 2>/dev/null || echo "[]")
fi

# Write description to temp file to avoid heredoc special-char issues
echo "$DESCRIPTION" > "$TMP/description.txt"

# ─────────────────────────────────────────────────────────────
# 7. Output JSON
# ─────────────────────────────────────────────────────────────
python3 - "$TMP/description.txt" << PYEOF
import json, sys

desc_file = sys.argv[1]
try:
    description = open(desc_file).read().strip()
except:
    description = ""

endpoints = $ENDPOINTS_JSON
schemas   = $SCHEMAS_JSON
tables    = $TABLES_JSON
classes   = $SVC_CLASSES_JSON
deps      = $DEPS_JSON

out = {
    "repo":        "$REPO_NAME",
    "module":      "$MODULE",
    "role":        "$ROLE",
    "description": description,
    "openapi": {
        "endpoint_count": len(endpoints),
        "endpoints":      endpoints,
        "schemas":        schemas
    },
    "tables":          tables,
    "service_classes": classes,
    "dependencies":    deps
}
print(json.dumps(out, indent=2))
PYEOF
