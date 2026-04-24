# Brain Sync — Reference Detail

## Folder Structure & Routing

Every artifact belongs in a specific folder. Always route to the correct one:

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

## Agent Session Log Format

At the end of every Orchestrator-managed task, write a session log to `06 - AI Agent Outputs/<task-slug>/`:

### Folder Structure
```
06 - AI Agent Outputs/
└── YYYY-MM-DD-<task-slug>/
    └── session-log.md              ← full pipeline summary
```

### `session-log.md` Template

```markdown
---
title: "Agent Session: <task title>"
date: "YYYY-MM-DD"
tags:
  - agent-output
  - session-log
agents_involved:
  - orchestrator
  - <list all agents used>
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

## Links
- Jira: <ticket URL>
- PR: <PR URL>
- Confluence: <page URL>
```

---

## Vault Routing by Agent Role

| Agent | Reads From | Writes To |
|---|---|---|
| Product Manager | `01 - Services/`, `04 - Decisions/` | `01 - Services/` (feature section) |
| Architect | `03 - Architecture/`, `04 - Decisions/` | `04 - Decisions/` (new ADRs) |
| Developer | `01 - Services/`, `02 - Runbooks/` | `01 - Services/` (implementation notes) |
| Security | `01 - Services/`, `03 - Architecture/` | `01 - Services/` (security notes) |
| QA Engineer | `01 - Services/`, `02 - Runbooks/` | `01 - Services/` (test notes) |
| Discovery | All folders | `05 - Scratch/` (findings), `01 - Services/` (new service docs) |
| brain-consolidation | STM Agent Contributions | All folders (harvests learnings) |
