---
name: brain-sync
description: >
  Invoke at the START of every task to look up relevant context from the brain
  SQL graph, and at the END of every task to persist new knowledge. The brain is
  the single source of truth for all institutional knowledge about EROAD's
  systems, services, and decisions.
---

# Brain Sync — SQL Graph Integration

The single source of truth is `~/.copilot/brain-graph.db` (SQLite, FTS5-indexed). Obsidian vaults (`~/eroad-brain`, `~/john-brain`) are no longer authoritative and their sync jobs are unloaded — **do not grep, read, or write `.md` files in those vaults**.

Vaults available in the graph: `eroad-brain` (858 nodes), `john-brain` (54 nodes).

## When to use

- **Start of every task** — fetch relevant context before specialist work begins.
- **Mid-task** — when an agent emits `PIPELINE_SIGNAL: NEED_DATA`.
- **End of every task** — write back learnings, decisions, and new entities.

## Lookup

```bash
# FTS keyword search (use first for most queries)
python3 ~/.copilot/scripts/brain-graph-query.py search \
  --query "KEYWORDS" --vault eroad-brain --max-results 10 --fetch-content --compact

# BFS traversal from a known node (use when you have an entry point)
python3 ~/.copilot/scripts/brain-graph-query.py traverse \
  --start-id "eroad-brain/01 - Services/media-service" --depth 2 --fetch-content
```

Vault routing:
- EROAD/Sovereign/company/services → `eroad-brain`
- Copilot config / personal / general → `john-brain`

## Write-back

Use SQL upserts into the `nodes` and `edges` tables. See `brain-consolidation.agent.md` for the full protocol. Never write `.md` files into the vaults.

## STM-first rule

Before invoking brain-sync, check the STM Fetch Manifest. If the data is already there, skip. If you need data that is NOT in the STM, emit `PIPELINE_SIGNAL: NEED_DATA` with the specific topics so the orchestrator can route to `brain-data-retrieval`.

## Gotchas

- **Always use `brain-graph-query.py`** — never query the SQLite DB directly. The FTS5 schema needs JOINs the script handles internally.
- **Route to the correct vault** — wrong vault = lost knowledge.
- **Do not duplicate nodes** — search first, then upsert. The graph's value comes from connectedness, not volume.
- **Per-repo `.github/learnings.md`** is unchanged — that is a separate, local learnings store and is still file-based.
