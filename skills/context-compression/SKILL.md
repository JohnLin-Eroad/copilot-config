---
name: context-compression
description: >
  Invoke when STM exceeds 200KB / ~50k tokens, when response quality is degrading (agent
  repeating itself, ignoring prior context), or before passing STM to brain-consolidation.
---

# Context Compression

Compress the STM to its **essential signal** — decisions, paths, findings, and action items. Discard verbose tool output and intermediate drafts.

**Core principle:** Lossless for decisions, lossy for verbosity.

---

## When to Trigger

- STM file size exceeds **200KB** (`wc -c "$STM_PATH"`)
- Agent context approaching **50k tokens**
- Response quality degrading (ignoring context, repeating itself, losing thread)
- User says "compress context" or "clean up the STM"
- Before passing STM to `brain-consolidation`
- After tool-output-heavy phases (build logs, test suites, grep scans)

**Do NOT trigger if:**
- STM under 50KB — overhead not worth it
- Pipeline just started — nothing to compress
- Mid-reasoning — finish the thought first, then compress

---

## What to Preserve vs Discard

**Always preserve:**
- Task brief (verbatim — never compress)
- Decisions + rationale
- File paths changed
- Action items remaining
- Key findings (conclusions, not raw output)
- Fetch manifest (prevents duplicate brain fetches)
- Negative context

**Always discard:**
- Full file contents read for reference (keep path + insight only)
- Verbose tool output (build logs, grep dumps, test output)
- Superseded drafts
- Duplicate findings across agents
- Abandoned plans
- Exploratory thoughts that didn't produce a decision

---

## Gotchas

- **Never compress the Task Brief** — it must survive verbatim; downstream agents need the original request
- **Never discard the Fetch Manifest** — losing it causes duplicate brain fetches that waste context
- **Two-pass compression** — if still over 100KB after first pass, you weren't aggressive enough; do a second pass
- **Don't compress mid-reasoning** — finish your current thought chain first; compressing breaks the thread
- **Agent Contributions compress to conclusions** — keep "chose X because Y", discard the 50 lines of tool output that led to it
- **Check section count after writing** — a compressed STM missing `[STM] Negative Context` or `[STM] Fetch Manifest` is broken

---

## Progressive Loading

📘 **GUIDE.md** — Read when you're about to execute compression. Contains the 5-step process and the full preserve/discard lists.

```bash
cat ~/.copilot/skills/context-compression/GUIDE.md
```

📖 **DETAIL.md** — Read when you need the exact STM template structure or the output report format.

```bash
cat ~/.copilot/skills/context-compression/DETAIL.md
```
