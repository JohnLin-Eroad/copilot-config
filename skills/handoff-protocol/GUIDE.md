# Handoff Protocol — Guide (Tier 2)

How to read/write TASK_CONTEXT.md sections and handle pushbacks between agents.

---

## Reading the Document

Before starting your work, read ALL prior sections of TASK_CONTEXT.md:

```bash
cat TASK_CONTEXT.md
```

Pay attention to:
- The original **Task Brief** — this is the ground truth
- Any **Feedback Log** entries addressed to you — resolve them before proceeding
- Prior agents' outputs — your work must be consistent with them unless you are pushing back

---

## Writing Your Section

After completing your work, append your section to TASK_CONTEXT.md:

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

If you discover an issue with a **prior agent's output** that must be resolved before you can continue:

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

```
PIPELINE_SIGNAL: PUSHBACK
TARGET: <agent-name>
REASON: <one line summary>
```

The Orchestrator will re-invoke the target agent with the Feedback Log entry, then resume the pipeline from your position once resolved.

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

## Next: Checkpoint & User Command Reference

For the **checkpoint file format**, **orchestrator presentation protocol**, and **user command handling**:

```bash
cat ~/.copilot/skills/handoff-protocol/DETAIL.md
```
