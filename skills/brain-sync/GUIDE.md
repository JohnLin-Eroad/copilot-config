# Brain Sync — Execution Guide

## Search Commands

```bash
# Search all markdown files for a keyword
grep -r --include="*.md" -l "KEYWORD" "$BRAIN"

# Search inside files for line-level context
grep -r --include="*.md" -n "KEYWORD" "$BRAIN"

# List all files in a folder
ls "$BRAIN/01 - Services/"

# Find a note by partial name
find "$BRAIN" -name "*service-name*" -type f
```

If you find relevant notes, **read them fully** before starting work.

### Agent routing for Step 2

If the Brain doesn't have what you need:
- Technical implementation → Developer agent
- Security implications → Security agent
- Architecture constraints → Architect agent
- Business requirements → Product Manager agent

---

## Write-Back Rules

### Rule 1 — No Duplicates
```bash
find "$BRAIN" -name "*similar-name*" -type f
grep -r --include="*.md" -l "title: \"Similar Title\"" "$BRAIN"
```
If a note exists, **update it** with a new dated section rather than creating a new one.

### Rule 2 — Use Templates
```bash
cat "$BRAIN/Templates/Service.md"       # for service docs
cat "$BRAIN/Templates/Architecture.md"  # for architecture
cat "$BRAIN/Templates/Decision.md"      # for ADRs
cat "$BRAIN/Templates/Runbook.md"       # for runbooks
cat "$BRAIN/Templates/Knowledge.md"     # for general knowledge
```
Replace all `{{placeholders}}` with real values.

### Rule 3 — YAML Frontmatter Required
```yaml
---
title: "Descriptive Title"
tags:
  - relevant-tag
date: "YYYY-MM-DD"
---
```

### Rule 4 — Filename Convention
Lowercase, hyphen-separated (kebab-case). Examples: `payment-service.md`, `adr-007-event-driven-provisioning.md`

### Rule 5 — Append/Update Only
Never delete content. Mark superseded sections with:
```markdown
> **Superseded on YYYY-MM-DD:** ...
```

### Rule 6 — Cross-Link Notes
```markdown
See also: [[01 - Services/asset-management-service]]
Related decision: [[04 - Decisions/adr-007-event-driven-provisioning]]
```

---

## STM Integration

### Reading from STM

Before doing brain lookups, check the STM — the data may already be there:
```bash
cat "$STM_PATH"
```

The STM contains:
- `## [STM] Brain Data` — brain content already fetched for this task
- `## [STM] Fetch Manifest` — files already loaded (prevents duplicate fetches)
- `## [STM] Agent Contributions` — outputs from prior agents

### Requesting More Brain Data

If you need data not in the STM, emit:
```
PIPELINE_SIGNAL: NEED_DATA
TOPICS: <comma-separated list>
```

The Orchestrator invokes `brain-data-retrieval`, which fetches the data, updates the STM, and resumes your agent.

### Writing Your Outputs to STM

After completing work, write to STM via `write-stm.sh`:
```bash
bash ~/.copilot/scripts/write-stm.sh "$STM_PATH" "<agent-name>" "STATUS: complete
FINDINGS: <summary>
Brain notes written: <vault paths>
Learnings: <learning statements with scope>"
```
