# Context Compression — Reference Detail

## Compressed STM Template

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

---

## Output Report Format

After compression, report:

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

---

## Incomplete Compression Signal

If STM remains over 100KB after two passes:

```
COMPRESSION_INCOMPLETE
Remaining size: {N} KB
Reason: {why further compression would lose critical data}
Recommendation: {split STM / archive early agents / proceed with current size}
```
