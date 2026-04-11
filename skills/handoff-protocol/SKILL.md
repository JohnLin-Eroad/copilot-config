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

`TASK_CONTEXT.md` is a structured markdown document created by the Orchestrator at the
start of every task. It lives in the current working directory (or a temp location the
Orchestrator specifies). Each agent in the pipeline reads all prior sections, then
appends its own section. This is the in-session context carrier.

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

## Reading the Document

Before starting your work, read ALL prior sections of TASK_CONTEXT.md:

```bash
cat TASK_CONTEXT.md
```

Pay attention to:
- The original **Task Brief** — this is the ground truth
- Any **Feedback Log** entries addressed to you — you must resolve them before proceeding
- Prior agents' outputs — your work must be consistent with them unless you are explicitly
  pushing back on something (in which case, log it in the Feedback Log)

---

## Writing Your Section

After completing your work, append your section to TASK_CONTEXT.md. Use this format:

```markdown
## [vN] <Your Agent Name> — <Section Title>
**Status:** ✅ Complete | ⚠️ Complete with issues | ❌ Blocked
**Date:** YYYY-MM-DD

### Summary
<2-3 sentences summarising what you did>

### Key Outputs
- <output 1>
- <output 2>

### Assumptions Made
- <any assumptions, especially where Brain or spec was silent>

### Open Issues
- <anything unresolved that the next agent should know about>

### Brain Notes Written
- [[path/to/note]] — <what it contains>
```

---

## Pushback Protocol

If you discover an issue with a **prior agent's output** that must be resolved before
you can continue, do the following:

### Step 1 — Append to the Feedback Log

```markdown
## Feedback Log

### [PUSHBACK] <Your Agent> → <Target Agent> — YYYY-MM-DD
**Severity:** 🔴 Blocker | 🟡 Should Fix | 🟢 Suggestion
**Issue:** <clear description of the problem>
**Specific reference:** <quote the exact part of the prior section that is wrong>
**Requested action:** <what you need the target agent to do>
**Status:** OPEN
```

### Step 2 — Set Your Section Status to Blocked

```markdown
## [vN] <Your Agent> — <Section Title>
**Status:** ❌ Blocked — see Feedback Log entry from <Your Agent> → <Target Agent>
```

### Step 3 — Signal the Orchestrator

End your turn by outputting:

```
PIPELINE_SIGNAL: PUSHBACK
TARGET: <agent-name>
REASON: <one line summary>
```

The Orchestrator will re-invoke the target agent with the Feedback Log entry, and then
resume the pipeline from your position once the pushback is resolved.

---

## Resolving a Pushback

If the Orchestrator re-invokes you with a Feedback Log entry targeting you:

1. Read the pushback carefully
2. Make the necessary changes
3. Update the Feedback Log entry status from `OPEN` to `RESOLVED`:
   ```markdown
   **Status:** RESOLVED — <brief description of what changed>
   ```
4. Update your section (append a `### Revision` subsection — do not overwrite)
5. Signal the Orchestrator:
   ```
   PIPELINE_SIGNAL: RESOLVED
   RESUME_FROM: <agent-that-pushed-back>
   ```

---

## Pipeline Signals Reference

| Signal | Meaning |
|---|---|
| `PIPELINE_SIGNAL: CONTINUE` | Work complete, pass to next agent |
| `PIPELINE_SIGNAL: PUSHBACK` | Issue found, needs upstream fix |
| `PIPELINE_SIGNAL: RESOLVED` | Pushback resolved, resume pipeline |
| `PIPELINE_SIGNAL: DONE` | Final signal from Orchestrator — pipeline complete |
| `PIPELINE_SIGNAL: AGENT_MISSING` | No suitable agent found — trigger Agent Factory |
| `PIPELINE_SIGNAL: CHECKPOINT` | Orchestrator has written a checkpoint and is awaiting user decision |

---

## Checkpoint Protocol

After **every agent completes**, the Orchestrator must:
1. Write a checkpoint file
2. Present a summary to the user
3. **Wait for explicit user approval** before invoking the next agent

This gives the user full visibility and control at every handoff.

### Checkpoint File

**Location:** `./checkpoints/CHECKPOINT-vN-<agent-name>.md` (created in the current working directory)

**Filename examples:**
- `checkpoints/CHECKPOINT-v1-product-manager.md`
- `checkpoints/CHECKPOINT-v2-architect.md`
- `checkpoints/CHECKPOINT-v3-security-arch.md`

**Format:**
```markdown
# ✅ Checkpoint v{N} — {Agent Name} Complete
**Date:** YYYY-MM-DD HH:MM
**Pipeline:** {Task slug}

---

## 📊 Pipeline Progress

| # | Agent | Status |
|---|---|---|
| 1 | Product Manager | ✅ Done |
| 2 | Architect | ✅ Done |
| 3 | Security (arch pass) | ⏳ Just completed |
| 4 | Developer | ⬜ Up next |
| 5 | Security (code pass) | ⬜ Pending |
| 6 | QA Engineer | ⬜ Pending |
| 7 | DevOps | ⬜ Pending |
| 8 | Code Reviewer | ⬜ Pending |

---

## 🔍 What {Agent Name} Did

### Summary
{2-3 sentences}

### Key Outputs
- {output 1}
- {output 2}

### Decisions Made
- {any significant choices made and why}

### Issues / Flags
{List any ⚠️ warnings or open questions. "None." if clean.}

### Brain Notes Written
- {vault path} — {what it contains}

---

## 🔮 What's Next — {Next Agent Name}

**{Next Agent}** will:
- {what it will do, based on what's been produced so far}

**Inputs it will use:**
- {key artefacts from prior agents it will rely on}

---

## 🔁 Pushbacks This Round
{List any pushback/resolution cycles that happened during this agent's work. "None." if clean.}

---

## 💬 Your Options

Reply with one of the following:

| Command | What happens |
|---|---|
| `continue` | Proceed to {Next Agent} |
| `change: <instruction>` | Modify something before proceeding (e.g. `change: the API should use GraphQL not REST`) |
| `redo: <agent>` | Re-run a specific agent (e.g. `redo: architect`) |
| `skip: <agent>` | Skip the next agent (e.g. `skip: security`) |
| `stop` | Halt the pipeline here — save all progress |
| `status` | Show the full TASK_CONTEXT.md so far |

---
*Checkpoint file saved to: `./checkpoints/CHECKPOINT-v{N}-{agent-name}.md`*
```

### How the Orchestrator Presents the Checkpoint

After writing the checkpoint file, the Orchestrator outputs the full checkpoint content
directly in the conversation so the user can read it without opening a file, then asks:

> **Pipeline paused. What would you like to do?**
> Reply `continue` to proceed to [Next Agent], or see the command table above.

The Orchestrator does **not** invoke the next agent until the user explicitly responds.

### Handling User Commands at a Checkpoint

| User says | Orchestrator action |
|---|---|
| `continue` | Invoke next agent as planned |
| `change: <instruction>` | Amend the relevant section of TASK_CONTEXT.md with the user's change, log it in a `## User Amendments` section, then continue from the appropriate agent (re-run current agent if the change affects its output) |
| `redo: <agent>` | Re-invoke that agent from scratch, replacing its TASK_CONTEXT.md section. Generate a new checkpoint after. |
| `skip: <agent>` | Mark that agent as `⏭️ Skipped (user)` in the progress table, proceed to the one after |
| `stop` | Write the current state to `$BRAIN/06 - AI Agent Outputs/` as a partial session log, inform the user the pipeline is saved and can be resumed |
| `status` | Print the full TASK_CONTEXT.md to the conversation |

### User Amendments Log

When a user makes a `change:` instruction, append to TASK_CONTEXT.md:

```markdown
## User Amendments

### Amendment {N} — After {Agent Name} — YYYY-MM-DD
**User instruction:** {verbatim}
**Applied to:** {which section / agent was affected}
**Action taken:** {what was changed and where}
```
