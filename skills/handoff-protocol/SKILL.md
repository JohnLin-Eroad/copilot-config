---
name: handoff-protocol
description: >
  Defines how agents hand off context to each other during a pipeline run. Each handoff
  is targeted — only what the next agent needs. If more context is required, the agent
  checks STM first, then raises NEED_DATA for brain retrieval.
---

# Handoff Protocol — Targeted Context Passing

## Core Principle

**Agents receive only what they need.** The orchestrator constructs a targeted handoff for each agent transition — not a monolithic shared document. This keeps agent context lean and focused.

---

## Context Escalation Chain

When an agent needs information to do its work:

1. **Handoff payload** — what the orchestrator passed you (always check this first)
2. **STM** — the session's short-term memory file (read if handoff is insufficient)
3. **NEED_DATA signal** — raise this if STM doesn't have what you need → orchestrator invokes brain-data-retrieval

```
Handoff payload → STM → PIPELINE_SIGNAL: NEED_DATA → brain-data-retrieval
```

---

## Pipeline Signals

| Signal | Meaning |
|---|---|
| `PIPELINE_SIGNAL: CONTINUE` | Work complete, pass to next agent |
| `PIPELINE_SIGNAL: PUSHBACK` | Issue with prior agent's output, needs fix |
| `PIPELINE_SIGNAL: NEED_DATA` | Insufficient context — request brain retrieval |
| `PIPELINE_SIGNAL: RESOLVED` | Pushback resolved, resume pipeline |
| `PIPELINE_SIGNAL: DONE` | Pipeline complete |
| `PIPELINE_SIGNAL: AGENT_MISSING` | No suitable agent — trigger Agent Factory |
| `PIPELINE_SIGNAL: STUCK` | Agent is stuck — trigger unstick escalation |

---

## Progressive Loading

This skill has **3 tiers**. You are reading **Tier 1** (brief).

📘 **GUIDE.md** — Read when you need to write a handoff, handle a pushback, or signal for more data.
Contains: handoff payload format, how to write your output, pushback protocol, NEED_DATA protocol.

```bash
cat ~/.copilot/skills/handoff-protocol/GUIDE.md
```

📖 **DETAIL.md** — Read when you are the orchestrator constructing handoffs for agents.
Contains: orchestrator handoff construction rules, what to include per agent role, checkpoint protocol.

```bash
cat ~/.copilot/skills/handoff-protocol/DETAIL.md
```
