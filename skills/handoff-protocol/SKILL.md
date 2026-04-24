---
name: handoff-protocol
description: >
  Defines the structure of TASK_CONTEXT.md — the shared context document that agents
  pass between each other during a pipeline run. Use this skill to understand how to
  read context from prior agents and how to append your own output. Also defines the
  pushback/feedback protocol for flagging issues back upstream.
---

# Handoff Protocol — Task Context Document

## What is TASK_CONTEXT.md?

`TASK_CONTEXT.md` is a structured markdown document created by the Orchestrator at the start of every task. Each agent in the pipeline reads all prior sections, then appends its own. This is the in-session context carrier.

---

## Document Structure

```markdown
# Task Context Document
<!-- Created by Orchestrator. Do not delete sections — only append. -->

## [v0] Task Brief — Orchestrator
## [v1] Product Manager — Spec
## [v2] Architect — Design
## [v3] Security — Architecture Review
## [v4] Developer — Implementation Notes
## [v5] Security — Code Review
## [v6] QA Engineer — Test Report
## [v7] DevOps — CI/CD Notes
## [v8] Code Reviewer — Final Review
## [v9] Orchestrator — Closing Summary

---
## Feedback Log
<!-- Agents append pushbacks here. Orchestrator monitors and routes. -->
```

---

## Pipeline Signals

| Signal | Meaning |
|---|---|
| `PIPELINE_SIGNAL: CONTINUE` | Work complete, pass to next agent |
| `PIPELINE_SIGNAL: PUSHBACK` | Issue found, needs upstream fix |
| `PIPELINE_SIGNAL: RESOLVED` | Pushback resolved, resume pipeline |
| `PIPELINE_SIGNAL: DONE` | Pipeline complete |
| `PIPELINE_SIGNAL: AGENT_MISSING` | No suitable agent — trigger Agent Factory |
| `PIPELINE_SIGNAL: CHECKPOINT` | Checkpoint written, awaiting user decision |

---

## Progressive Loading

This skill has **3 tiers**. You are reading **Tier 1** (brief).

📘 **GUIDE.md** — Read when you need to read/write sections or handle pushbacks.
Contains: how to read the document, section write template, pushback protocol, resolving pushbacks.

```bash
cat ~/.copilot/skills/handoff-protocol/GUIDE.md
```

📖 **DETAIL.md** — Read when the Orchestrator needs checkpoint file format or user command handling.
Contains: checkpoint file template, orchestrator presentation protocol, user command table, amendments log format.

```bash
cat ~/.copilot/skills/handoff-protocol/DETAIL.md
```
