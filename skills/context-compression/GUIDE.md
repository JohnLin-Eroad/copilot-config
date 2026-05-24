# Context Compression — Execution Guide

## 5-Step Compression Process

### Step 1 — Check STM Size

```bash
wc -c "$STM_PATH" | awk '{print $1/1024 " KB"}'
```

If under 200KB → report the size and stop. If over → proceed.

### Step 2 — Read the Full STM

```bash
cat "$STM_PATH"
```

### Step 3 — Extract the Essential Signal

**Preserve** (do NOT discard):
- **Task brief** — original user request and classification (verbatim)
- **Decisions made** — every decision with rationale (e.g. "chose PostgreSQL because...")
- **File paths changed** — every file created, modified, or deleted
- **Action items remaining** — things still to do
- **Key findings** — conclusions reached, not raw output that produced them
- **Brain notes written** — vault paths of any notes persisted
- **Pushbacks and resolutions** — feedback loops that occurred
- **Fetch manifest** — all fetched brain paths (prevents duplicate fetches)
- **Negative context** — topics searched but not found in brain

**Discard:**
- Full file contents read for reference (keep path + insight only)
- Verbose tool output (build logs, grep dumps, test suites)
- Intermediate drafts superseded by later versions
- Duplicate findings stated by multiple agents
- Abandoned plans replaced by a different approach
- Exploratory thoughts that didn't produce a decision

### Step 4 — Rewrite the STM

Write the compressed STM back to `$STM_PATH`. See DETAIL.md for the exact template structure.

Key rules:
- Add `compressed:` and `compression_note:` to frontmatter
- Task Brief section stays verbatim — never compress it
- Agent Contributions compress to conclusions + decisions + file paths only
- Brain Data compresses to one line per concept (drop full file contents)

### Step 5 — Verify Size and Integrity

```bash
# Check new size
wc -c "$STM_PATH" | awk '{print $1/1024 " KB"}'

# Verify required sections present
grep -c "Task Brief\|Fetch Manifest\|Agent Contributions\|Action Items" "$STM_PATH"
```

Target: under **100KB**. If still over after first pass, do a second pass — you weren't aggressive enough.
