---
name: context-compression
description: >
  Compresses the Short-Term Memory (STM) file or agent context when it exceeds 200KB /
  ~50k tokens. Extracts decisions, file paths, action items, and key findings — discards
  verbose tool output and intermediate drafts. Run before passing STM to a new agent or
  when response quality is degrading due to context length.
---

# Skill: Context Compression

## Purpose

Long-running pipelines accumulate verbose tool output, intermediate drafts, superseded plans, and full file contents in the STM. This bloats the context window, degrades model response quality, and slows agent handoffs. This skill compresses the STM to its **essential signal** — decisions, paths, findings, and action items — without losing anything that future agents need.

Compression is **lossless for decisions, lossy for verbosity**.

---

## When to Trigger

Trigger this skill when **any** of these are true:
- STM file size exceeds **200KB**
- Agent context token count is approaching **50k tokens**
- Response quality has visibly degraded (agent is ignoring prior context, repeating itself, or losing thread)
- User says "compress context", "summarise what we've done", or "clean up the STM"
- Before passing the STM to a new agent (especially `brain-consolidation`)
- After a long tool-output-heavy phase (e.g. after a build run, test suite output, or grep scan)

Do **not** trigger if:
- The STM is under 50KB — overhead not worth the risk
- The pipeline has just started (nothing to compress yet)
- You are in the middle of an active reasoning chain — finish first, then compress

---

## How to Use

### Step 1 — Check STM Size
```bash
wc -c "$STM_PATH" | awk '{print $1/1024 " KB"}'
```

If under 200KB, report the size and stop — compression is not needed. If over 200KB, proceed.

### Step 2 — Read the Full STM
Read the entire STM file into context:
```bash
cat "$STM_PATH"
```

### Step 3 — Extract the Essential Signal
Identify and preserve the following (do NOT discard):
- **Task brief** — the original user request and classification
- **Decisions made** — every decision with its rationale (e.g. "chose PostgreSQL over MySQL because...")
- **File paths changed** — every file that was created, modified, or deleted
- **Action items remaining** — things still to be done
- **Key findings from agents** — the conclusions reached, not the raw output that produced them
- **Brain notes written** — vault paths of any notes persisted
- **Pushbacks and resolutions** — any feedback loops that occurred
- **Fetch manifest** — which brain files have already been loaded (prevents duplicate fetches)
- **Negative context** — topics searched but not found in brain

Discard the following:
- ❌ Full file contents that were read for reference (keep only the path and the insight derived)
- ❌ Verbose tool output (full build logs, full grep results, full test suite output)
- ❌ Intermediate drafts that were superseded
- ❌ Duplicate information (the same finding stated multiple times by different agents)
- ❌ Plans that were abandoned in favour of a different approach
- ❌ Exploratory thoughts that didn't produce a decision

### Step 4 — Rewrite the STM
Write the compressed STM back to `$STM_PATH`. Preserve the structure:

```markdown
---
task: "<task-slug>"
created: "<original ISO timestamp>"
compressed: "<compression ISO timestamp>"
compression_note: "Compressed by context-compression skill. Original size: <N>KB → <M>KB"
---

# Short-Term Memory — <task-slug>

## [STM] Task Brief
<original task brief — verbatim, never compress this>

---

## [STM] Classification
<classification block verbatim>

---

## [STM] Fetch Manifest
<all fetched brain paths — verbatim>

---

## [STM] Negative Context
<topics not found — verbatim>

---

## [STM] Brain Data
<compressed: key facts only, one line per concept. Drop full file contents.>

---

## [STM] Agent Contributions

### [<agent-name>] — <ISO timestamp>
**Status:** <status>
**Key outputs:** <bullet points — conclusions only, not verbose output>
**Decisions:** <bullet points with rationale>
**Files changed:** <paths only>
**Brain notes written:** <paths only>

<!-- Repeat for each agent -->

---

## [STM] Action Items Remaining
- [ ] <item>
- [ ] <item>
```

### Step 5 — Verify Size and Integrity
```bash
# Check new size
wc -c "$STM_PATH" | awk '{print $1/1024 " KB"}'

# Verify no critical sections are missing
grep -c "Task Brief\|Fetch Manifest\|Agent Contributions\|Action Items" "$STM_PATH"
```

The compressed STM must:
- Be under **100KB**
- Contain all decisions with rationale
- Contain all file paths changed
- Contain all action items remaining
- Contain the full fetch manifest (to prevent duplicate brain fetches)

If the compressed file is still over 100KB, do a second pass — the first pass was not aggressive enough about removing verbose output.

---

## Output Contract

Report compression results as follows:

```
## Context Compression Report

Original size: {N} KB
Compressed size: {M} KB
Reduction: {P}%

Preserved:
  - Task brief: ✅
  - Decisions with rationale: ✅ ({N} decisions)
  - Files changed: ✅ ({N} paths)
  - Action items: ✅ ({N} items)
  - Fetch manifest: ✅ ({N} entries)
  - Negative context: ✅

Discarded:
  - Verbose tool output: {N} KB removed
  - Full file contents read for reference: {N} KB removed
  - Superseded drafts: {N} KB removed
  - Duplicate findings: {N} KB removed

STM written to: {STM_PATH}
Integrity check: ✅ All required sections present
```

If anything critical could not be safely discarded and the STM remains over 100KB after two passes, report:
```
COMPRESSION_INCOMPLETE
Remaining size: {N} KB
Reason: {why further compression would lose critical data}
Recommendation: {split STM / archive early agents / proceed with current size}
```

---

## Comparison

| Skill | Use when |
|---|---|
| `context-compression` | STM > 200KB or context degrading — compress to essential signal |
| `brain-sync` | Writing permanent knowledge to the Obsidian vault |
| `session-summary` | Producing a human-readable summary of what the pipeline achieved |
| `handoff-protocol` | Structuring targeted agent-to-agent handoffs |
