---
name: brain-sync
description: >
  Teaches agents how to read from and write to the Obsidian knowledge vault (the Brain).
  Use this skill at the START of every task to look up relevant context, and at the END
  of every task to persist new knowledge. This is the single source of truth for all
  institutional knowledge about EROAD's systems, services, and decisions.
---

# Brain Sync — Obsidian Vault Integration

## Vault Location

```
/Users/johnlin/Library/Group Containers/UBF8T346G9.OneDriveStandaloneSuite/OneDrive - EROAD.noindex/OneDrive - EROAD/Documents/eroad-brain
```

Shorthand: `$BRAIN`

---

## Folder Structure & Routing

Every artifact you produce belongs in a specific folder. Always route to the correct one:

| Artifact Type | Brain Folder | Template |
|---|---|---|
| Service documentation | `01 - Services/` | `Templates/Service.md` |
| Operational runbooks | `02 - Runbooks/` | `Templates/Runbook.md` |
| Architecture documents | `03 - Architecture/` | `Templates/Architecture.md` |
| ADRs / Decisions | `04 - Decisions/` | `Templates/Decision.md` |
| Working notes / scratch | `05 - Scratch/` | None (freeform) |
| Agent session logs & task summaries | `06 - AI Agent Outputs/` | None (freeform) |
| General knowledge articles | Any relevant folder | `Templates/Knowledge.md` |

---

## Knowledge Lookup Protocol

**Before starting any task**, follow this order:

### Step 1 — Search the Brain
Search the vault for relevant notes before doing any other work. Use these search strategies:

```bash
# Search all markdown files for a keyword
grep -r --include="*.md" -l "KEYWORD" "$BRAIN"

# Search inside files for context
grep -r --include="*.md" -n "KEYWORD" "$BRAIN"

# List all files in a folder
ls "$BRAIN/01 - Services/"

# Find a note by partial name
find "$BRAIN" -name "*service-name*" -type f
```

If you find relevant notes, read them fully. Use the information to inform your work.

### Step 2 — Ask Another Agent
If the Brain does not contain what you need, identify which specialist agent would know
and signal the Orchestrator to delegate the question. For example:
- Technical implementation details → Developer agent
- Security implications → Security agent  
- Architecture constraints → Architect agent
- Business requirements → Product Manager agent

### Step 3 — Ask the User
Only if Steps 1 and 2 have been exhausted and the question cannot be inferred. Phrase
the question clearly, explain what you searched for and why you couldn't find it.

---

## Write-Back Rules

After completing your work, write your outputs to the Brain. Follow these rules:

### Rule 1 — No Duplicates
Before creating a new note, check if one already exists:
```bash
find "$BRAIN" -name "*similar-name*" -type f
grep -r --include="*.md" -l "title: \"Similar Title\"" "$BRAIN"
```
If a note exists, **update it** rather than creating a new one. Add a new dated section
rather than overwriting existing content.

### Rule 2 — Use Templates
When creating a new note, always start from the correct template:
```bash
cat "$BRAIN/Templates/Service.md"       # for service docs
cat "$BRAIN/Templates/Architecture.md"  # for architecture
cat "$BRAIN/Templates/Decision.md"      # for ADRs
cat "$BRAIN/Templates/Runbook.md"       # for runbooks
cat "$BRAIN/Templates/Knowledge.md"     # for general knowledge
```

Replace all `{{placeholders}}` with real values before writing the file.

### Rule 3 — YAML Frontmatter is Required
Every note must have valid YAML frontmatter. At minimum:
```yaml
---
title: "Descriptive Title"
tags:
  - relevant-tag
date: "YYYY-MM-DD"
---
```

### Rule 4 — Filename Convention
- Lowercase, hyphen-separated (kebab-case)
- Descriptive and unique
- Examples: `payment-service.md`, `adr-007-event-driven-provisioning.md`

### Rule 5 — Vault is Append/Update Only
Never delete content from the Brain. If something is superseded, mark the old section
with a `> **Superseded on YYYY-MM-DD:** ...` blockquote and add the new content below.

### Rule 6 — Cross-Link Notes
Use Obsidian wiki-link syntax to link related notes:
```markdown
See also: [[01 - Services/asset-management-service]]
Related decision: [[04 - Decisions/adr-007-event-driven-provisioning]]
```

---

## Agent Session Log Format

At the end of every Orchestrator-managed task, write a session log to `06 - AI Agent Outputs/<task-slug>/`:

**Folder structure:**
```
06 - AI Agent Outputs/
└── YYYY-MM-DD-<task-slug>/
    ├── session-log.md              ← full pipeline summary
    ├── CHECKPOINT-v1-product-manager.md
    ├── CHECKPOINT-v2-architect.md
    ├── CHECKPOINT-v3-security-arch.md
    ├── CHECKPOINT-v4-developer.md
    ├── CHECKPOINT-v5-security-code.md
    ├── CHECKPOINT-v6-qa-engineer.md
    ├── CHECKPOINT-v7-devops.md
    └── CHECKPOINT-v8-code-reviewer.md
```

The checkpoints provide a complete decision trail — what each agent did, what the user approved or changed, and any pushbacks that occurred.

**`session-log.md` format:**

```markdown
---
title: "Agent Session: <task title>"
date: "YYYY-MM-DD"
tags:
  - agent-output
  - session-log
agents_involved:
  - orchestrator
  - product-manager
  - architect
  - developer
  - qa-engineer
---

# Agent Session: <task title>

## Task Brief
<original user request>

## Pipeline Summary
| Agent | Status | Key Output |
|---|---|---|
| Product Manager | ✅ Done | Jira ticket XYZ, Confluence spec |
| Architect | ✅ Done | ADR written to brain |
| Developer | ✅ Done | PR #123 opened |
| Security | ⚠️ Flagged | 2 issues found, 1 pushed back to Dev |
| QA | ✅ Done | 47 tests written, 100% pass |
| DevOps | ✅ Done | CI pipeline updated |
| Code Reviewer | ✅ Done | 1 nit, approved |

## User Amendments
<any changes the user made at checkpoints>

## Pushback Log
<any feedback loops that occurred>

## Brain Notes Written
- [[03 - Architecture/payment-flow-redesign]]
- [[04 - Decisions/adr-012-jwt-auth]]

## Checkpoints
All checkpoint files are in this folder.

## Links
- Jira: <ticket URL>
- PR: <PR URL>
- Confluence: <page URL>
```

---

## Short-Term Memory (STM) Integration

Every Orchestrator-managed pipeline uses a **Short-Term Memory file** as the shared in-session context. As a brain-interacting agent, you must be aware of this:

### Reading from STM

Before doing any brain lookups yourself, check the STM first — the data may already be there:

```bash
# The STM path is passed to you in your prompt as: STM: /tmp/sov-task-<slug>/short-term-memory.md
cat "$STM_PATH"
```

The STM contains:
- `## [STM] Brain Data` — all brain content already fetched for this task
- `## [STM] Fetch Manifest` — list of brain files already loaded (prevents duplicate fetches)
- `## [STM] Agent Contributions` — outputs from prior agents in the pipeline

### Requesting More Brain Data

If you need brain data not in the STM, **do not fetch it yourself**. Append a request and signal the Orchestrator:

```markdown
### REQUEST from <your-agent-name> — <ISO timestamp>
**Topics needed:**
- <specific service, domain, ADR topic>
**Reason:** <why you need this>
**Status:** PENDING
```

Then emit:
```
PIPELINE_SIGNAL: NEED_DATA
TOPICS: <comma-separated list>
```

The Orchestrator invokes `brain-data-retrieval`, which fetches the data, updates the STM, and resumes your agent.

### Writing Your Outputs to STM

After completing your work, append your key outputs to the STM under `## [STM] Agent Contributions`:

```markdown
### [<your-agent-name>] — <ISO timestamp>
**Status:** ✅ Complete
**Key outputs:**
- <output 1>
- <output 2>
**Brain notes written:**
- <vault path> — <what it contains>
**Learnings identified:**
- <learning statement> [scope: repo | project | domain | global]
```

This allows the `brain-consolidation` agent to harvest all learnings at the end of the pipeline in one pass without missing anything.
