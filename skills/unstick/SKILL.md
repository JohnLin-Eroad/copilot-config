---
name: unstick
description: >
  Tactical escalation skill for agents that are stuck. Spawns a claude-opus-4.6
  consultation with the exact stuck context and returns a concrete alternative approach.
  Use when the same action has failed 3+ times or no progress has been made after 5+
  tool calls. Lighter and faster than advisor — one model, one answer, actionable steps.
---

# Skill: Unstick

## Purpose

When you are stuck — looping on a failing action, hitting a tool limitation, or making no forward progress — stop and run this skill. It escalates your context to a higher-capability model and returns a **concrete alternative approach** in ≤5 steps.

Do not keep retrying the same failing action. Recognise the loop early and escalate.

---

## When to Trigger

Trigger this skill if **any** of these are true:
- You have attempted the same tool call 3+ times with the same or worsening result
- You have made 5+ tool calls with no measurable forward progress (no files written, no state changed)
- You hit a hard constraint (tool unavailable, permission denied, file not found after retrying)
- You are about to retry something you've already tried twice
- **Background agent: `elapsed > 15s` AND `0 changes made`** — agent is stalled; escalate immediately

---

## How to Use

**Step 1 — Stop.** Do not retry. Output the following signal:

```
PIPELINE_SIGNAL: STUCK
Attempting: <one sentence — what you were trying to do>
Constraint: <the specific error, limitation, or barrier>
Tried so far:
  1. <attempt 1 + result>
  2. <attempt 2 + result>
  3. <attempt 3 + result if applicable>
```

**Step 2 — Escalate.** Spawn a sub-agent using the `task` tool:

```
agent_type: general-purpose
model: claude-opus-4.6
mode: sync
prompt: |
  You are a senior engineer advising an agent that is stuck.

  ## What the agent was trying to do
  <goal>

  ## The constraint it hit
  <specific error or limitation>

  ## What it tried
  <list of attempts>

  ## Context
  <relevant environment — tools available, file paths, current state>

  Give a concrete alternative approach in ≤5 numbered steps.
  Be specific — include exact commands, file paths, or tool calls.
  Do not suggest retrying what already failed.
```

**Step 3 — Act.** Follow the opus advice exactly. If the advice also fails, output the result and stop — do not loop further. Surface the failure to the caller.

---

## Output Contract

The unstick consultation returns one of:
- **Alternative approach** (≤5 steps, concrete, immediately actionable)
- **Graceful stop** — "This cannot be done with the available tools. Here is what was completed: [list]. Caller must handle: [remaining work]."

A graceful stop is not failure — it is correct behaviour. The agent surfaces the gap; the caller (orchestrator or human) handles it.

---

## Comparison

| Skill | Use when |
|---|---|
| `unstick` | Agent is looping / hitting a tool wall — need tactical escape |
| `advisor` | Strategic or architectural decision — need diverse perspectives |
| `critical-thinker` | Evaluating a plan before committing — need risk/strength breakdown |
| `dual-critique` | HIGH blast-radius decision — need adversarial pressure-testing |
