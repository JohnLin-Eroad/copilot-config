# Handoff Protocol — Guide (Tier 2)

How to read your handoff, write your output, handle pushbacks, and request more data.

---

## Reading Your Handoff

The orchestrator passes you a **targeted handoff** — not the full pipeline history. It contains only what you need:

- **Task brief** — what the user asked for
- **Relevant prior output** — only from agents whose work affects yours
- **Your specific instructions** — what the orchestrator expects you to produce
- **STM path** — where to find the session's short-term memory if you need more

**Start by reading your handoff completely.** If it's sufficient, proceed. If not, escalate (see below).

---

## Writing Your Output

When you complete your work, structure your output so the orchestrator can extract what the **next** agent needs (not everything you did):

```markdown
## Summary
<2-3 sentences: what you did and the key outcome>

## Key Outputs
- <concrete output 1 — file path, decision, finding>
- <concrete output 2>

## For Next Agent
<What the next agent specifically needs to know from your work.
Only include what's relevant to them — not your full reasoning.>

## Assumptions Made
- <any assumptions, especially where context was silent>

## Open Issues
- <anything unresolved that could affect downstream agents>
```

The orchestrator reads this and constructs the next agent's handoff from it.

---

## Requesting More Context

If your handoff doesn't contain enough information:

### Step 1 — Check STM

```bash
cat <STM_PATH>   # path provided in your handoff
```

Look for relevant prior agent contributions, brain data, or task context.

### Step 2 — Signal NEED_DATA

If STM doesn't have what you need either, signal the orchestrator:

```
PIPELINE_SIGNAL: NEED_DATA
TOPIC: <what you need — be specific>
REASON: <why you can't proceed without it>
```

The orchestrator will invoke `brain-data-retrieval`, inject the result into your context, and resume.

---

## Pushback Protocol

If you find an issue with a **prior agent's output** that blocks your work:

### Raise the Pushback

```
PIPELINE_SIGNAL: PUSHBACK
TARGET: <agent-name>
SEVERITY: BLOCKER | SHOULD_FIX | SUGGESTION
ISSUE: <clear description of the problem>
REFERENCE: <quote the specific part that is wrong>
REQUESTED_ACTION: <what you need them to fix>
```

Set your output status to `❌ Blocked` and stop. The orchestrator will re-invoke the target agent with your pushback, then resume from you.

### Resolving a Pushback (if you're the target)

1. Read the pushback in your handoff
2. Make the necessary changes
3. Output your revised work with a `## Revision` section explaining what changed
4. Signal: `PIPELINE_SIGNAL: RESOLVED`

---

## Next: Orchestrator Reference

For **how the orchestrator constructs handoffs** per agent role, **checkpoint protocol**, and **user commands**:

```bash
cat ~/.copilot/skills/handoff-protocol/DETAIL.md
```
