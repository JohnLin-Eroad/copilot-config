# Handoff Protocol — Full Reference (Tier 3)

Checkpoint file format, orchestrator presentation, user commands, and amendments log.

---

## Checkpoint Protocol

After **every agent completes**, the Orchestrator must:
1. Write a checkpoint file
2. Present a summary to the user
3. **Wait for explicit user approval** before invoking the next agent

### Checkpoint File

**Location:** `./checkpoints/CHECKPOINT-vN-<agent-name>.md`

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
| `change: <instruction>` | Modify something before proceeding |
| `redo: <agent>` | Re-run a specific agent |
| `skip: <agent>` | Skip the next agent |
| `stop` | Halt the pipeline — save all progress |
| `status` | Show the full TASK_CONTEXT.md so far |

---
*Checkpoint file saved to: `./checkpoints/CHECKPOINT-v{N}-{agent-name}.md`*
```

---

## How the Orchestrator Presents the Checkpoint

After writing the checkpoint file, output the full checkpoint content directly in the conversation so the user can read it without opening a file, then ask:

> **Pipeline paused. What would you like to do?**
> Reply `continue` to proceed to [Next Agent], or see the command table above.

The Orchestrator does **not** invoke the next agent until the user explicitly responds.

---

## Handling User Commands at a Checkpoint

| User says | Orchestrator action |
|---|---|
| `continue` | Invoke next agent as planned |
| `change: <instruction>` | Amend the relevant section of TASK_CONTEXT.md, log in `## User Amendments`, then continue from the appropriate agent (re-run current if change affects its output) |
| `redo: <agent>` | Re-invoke that agent from scratch, replacing its TASK_CONTEXT.md section. Generate a new checkpoint after. |
| `skip: <agent>` | Mark as `⏭️ Skipped (user)` in progress table, proceed to next |
| `stop` | Write current state to `$BRAIN/06 - AI Agent Outputs/` as partial session log, inform user pipeline is saved |
| `status` | Print the full TASK_CONTEXT.md to the conversation |

---

## User Amendments Log

When a user makes a `change:` instruction, append to TASK_CONTEXT.md:

```markdown
## User Amendments

### Amendment {N} — After {Agent Name} — YYYY-MM-DD
**User instruction:** {verbatim}
**Applied to:** {which section / agent was affected}
**Action taken:** {what was changed and where}
```
