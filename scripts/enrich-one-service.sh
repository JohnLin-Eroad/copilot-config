#!/bin/bash
# enrich-one-service.sh — Launches an orchestrator enrichment run on a single service node
# Usage: bash enrich-one-service.sh <repo-name>
# Example: bash enrich-one-service.sh myeroad-driver-service

set -euo pipefail

SERVICE="$1"
BRAIN_NODE=~/eroad-brain/01\ -\ Services/"${SERVICE}".md
STANDARD=~/eroad-brain/Brain/Service\ Node\ Enrichment\ Standard.md

if [[ ! -f "$BRAIN_NODE" ]]; then
  echo "❌ Brain node not found: $BRAIN_NODE"
  exit 1
fi

echo "🚀 Launching enrichment pipeline for: $SERVICE"
echo "   Brain node: $BRAIN_NODE"
echo "   Standard: $STANDARD"

# Read current node content for context
CURRENT_CONTENT=$(head -80 "$BRAIN_NODE")

cat <<PROMPT
## Task: Deep Enrichment of eroad-brain Service Node

You are enriching the brain node for ONE service with comprehensive, accurate data gathered from GitHub source code, Confluence documentation, and Jira tickets.

**Service:** \`${SERVICE}\`
**GitHub:** \`https://github.com/eroad/${SERVICE}\`
**Brain node:** \`${BRAIN_NODE}\`

---

## Enrichment Standard

Read the full enrichment standard before starting:
\`cat "$STANDARD"\`

Every section in that standard is REQUIRED. Follow it exactly.

---

## Current Node (what we have — needs to be replaced with accurate data)

\`\`\`
${CURRENT_CONTENT}
\`\`\`

---

## Steps

### STEP 1 — Discovery Agent: Deep code analysis
Assign discovery to:
1. Fetch full file tree: \`gh api repos/eroad/${SERVICE}/git/trees/HEAD?recursive=1 | jq '[.tree[].path]'\`
2. Read README.md and catalog-info.yaml for service description and metadata
3. Find ALL @Entity classes → read each → extract table name + all @Column fields
4. Find ALL Controller/Resource classes → read each → extract HTTP method, path, @Operation description
5. Find ALL Service implementation classes (not interfaces) → read each → understand:
   - What DB queries are made (which repo methods, what filters)
   - What downstream HTTP calls are made (Feign clients, RestTemplate)
   - What SQS/Kinesis/SNS messages are published or consumed
   - What the log statements reveal about the business workflow
6. Find all Feign client interfaces → list every downstream service called
7. Find SQS listener classes → list every queue consumed and what the handler does
8. Find event publisher classes → list every queue published to and what triggers the publish

Output: Full structured extraction of all above — this feeds the workflow descriptions.

### STEP 2 — Integration Agent: Confluence + Jira
Assign sov-integration to:
1. Search Confluence for "${SERVICE}" and "${SERVICE} service" — extract any architecture docs, data flow diagrams, API docs
2. Try Jira project keys based on service name (e.g. for myeroad-driver-service try: DRV, MDS, DRIVER, DIME, CEP)
3. Fetch 5-10 recent Jira issues from the matching project to understand current work
4. Return: Confluence page IDs+titles+URLs found, Jira project key, recent ticket summaries

### STEP 3 — Developer Agent: Write workflow descriptions
Assign sov-developer to write the Integration Graph and API endpoint workflow descriptions.

Using the code extracted in Step 1:
1. For EACH integration flow (inbound AND outbound), write a 2-4 sentence description that covers:
   - **Inbound:** What triggers this call, what the caller needs, what this service does to fulfil it (aggregation/validation/transformation), what is returned
   - **Outbound:** Why this service calls the target, what specific data it requests, what happens if the target is unavailable (fail-hard / degrade / cache), how the result affects the response
   - **Event (SQS in):** What triggers the message, what data it carries, what this service does when it receives it, and the business outcome
   - **Event (SQS out):** What action triggers the publish, what the message contains, who consumes it, and what the downstream outcome is

2. For EACH API endpoint, write a 3-5 sentence workflow description:
   - Auth/org context resolution (JWT claims, selectedOrgGid header, fleet membership check)
   - What data is read or written and from/to where
   - Any side effects (events published, caches invalidated, audit trail entries)
   - Return value and key error cases

CRITICAL: Every description must be based on actual code read in Step 1. NO fabrication.

### STEP 4 — Brain Consolidation: Write the enriched node
Assign brain-consolidation to write the complete enriched node to \`${BRAIN_NODE}\`.

Follow the schema in the Enrichment Standard exactly. Include ALL sections.

After writing, verify the file was written correctly by reading the first 50 lines.

Then run: \`bash ~/.copilot/scripts/brain-git-push.sh\`

---

## Success Criteria

Report at the end:
- ✅/❌ Service description (≥4 sentences)
- ✅/❌ Domain entities (table populated or explicit stateless statement)  
- ✅/❌ All API endpoints have unique workflow descriptions
- ✅/❌ Integration graph has ≥2 sentence descriptions per row
- ✅/❌ Jira project key identified
- ✅/❌ Confluence: links found or "none found" stated
- ✅/❌ Brain file written and pushed
PROMPT
