---
name: brain-sync
description: >
  Invoke at the START of every task to look up relevant context from the Obsidian
  knowledge vault (the Brain), and at the END of every task to persist new knowledge.
  The Brain is the single source of truth for all institutional knowledge about EROAD's
  systems, services, and decisions.
---

# Brain Sync — SQL Graph Integration

> ## ⚡ SQL-ONLY MODE (active 2026-05-19)
>
> **Obsidian vaults are toggled OFF as a knowledge source.** The single source of truth is now `~/.copilot/brain-graph.db` (SQLite). The `obsidian-sync` and `brain-repo-sync` launchd jobs have been unloaded.
>
> ### Lookup (replaces "grep the vault")
>
> ```bash
> # FTS search across the graph
> python3 ~/.copilot/scripts/brain-graph-query.py search \
>   --query "KEYWORDS" --vault eroad-brain --max-results 10 --fetch-content --compact
>
> # BFS traversal from a known node
> python3 ~/.copilot/scripts/brain-graph-query.py traverse \
>   --start-id "eroad-brain/01 - Services/media-service" --depth 2 --fetch-content
> ```
>
> Vaults available in the graph: `eroad-brain` (858 nodes), `john-brain` (54 nodes).
>
> ### Write-back (replaces creating `.md` files)
>
> See `brain-consolidation.agent.md` for the SQL upsert protocol. **Do not write `.md` files into `~/eroad-brain` or `~/john-brain`** — they are no longer authoritative.
>
> Everything below this block describing `grep -r "$BRAIN"`, file-based templates, wiki-link `.md` cross-references, etc. is retained for reference but is **superseded**. Use the SQL graph.

---

# Brain Sync — Obsidian Vault Integration (LEGACY, superseded by SQL-Only Mode above)

## Vault Location

```
~/eroad-brain        # EROAD/work context  ($BRAIN)
~/john-brain         # Personal/general context
```

---

## When to Use

- **START of every task** — search the Brain for relevant context before doing any work
- **END of every task** — write new knowledge back to the Brain

---

## Knowledge Lookup — 3-Step Escalation

1. **Search the Brain** — `grep -r --include="*.md" -l "KEYWORD" "$BRAIN"` — read any relevant notes fully
2. **Ask another agent** — if Brain doesn't have what you need, signal the Orchestrator to delegate to a specialist
3. **Ask the user** — only after steps 1-2 are exhausted; explain what you searched for and why you couldn't find it

---

## Core Write-Back Principles

- **No duplicates** — check if a note exists before creating a new one; update existing notes with dated sections
- **Use templates** — always start from `$BRAIN/Templates/<Type>.md` when creating new notes
- **YAML frontmatter required** — every note needs `title`, `tags`, `date` at minimum
- **Append-only** — never delete content; mark superseded sections with a blockquote
- **Cross-link** — use `[[wiki-link]]` syntax to connect related notes

---

## Gotchas

- **Always search before creating** — duplicate notes are the #1 brain pollution problem. `find "$BRAIN" -name "*keyword*"` first.
- **Check STM before searching the Brain** — the data may already be fetched. Don't waste tool calls on redundant lookups.
- **Never delete content** — if something is wrong, mark it superseded with a dated blockquote. Append-only vault.
- **Don't forget YAML frontmatter** — notes without `title`, `tags`, `date` break Obsidian's graph and search index.
- **Use kebab-case filenames only** — `payment-service.md` not `PaymentService.md`. Obsidian wiki-links are case-sensitive.
- **Don't use `~` in wiki-links** — use relative Obsidian syntax: `[[01 - Services/payment-service]]` not absolute paths.
- **Route to the correct vault** — `~/eroad-brain` for EROAD/work, `~/john-brain` for personal/general. Wrong vault = lost knowledge.

---

## STM Integration

Before doing brain lookups, **check the STM first** — the data may already be there. If you need brain data not in the STM, emit `PIPELINE_SIGNAL: NEED_DATA` with the topics you need.

---

## Progressive Loading

When ready to execute brain operations:
```bash
cat ~/.copilot/skills/brain-sync/GUIDE.md     # Search commands, write-back rules, STM protocol
```

For session log templates and folder routing:
```bash
cat ~/.copilot/skills/brain-sync/DETAIL.md    # Folder structure, templates, session log format
```
