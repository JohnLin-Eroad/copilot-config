# Brain Decay — Hippo-Memory-Inspired Reinforcement Layer

> **Status:** Phases 1–8 complete. **182/182 tests green.** Production-ready.
> Feature-flagged via `BRAIN_DECAY_ENABLED=1` for reads; admin & housekeeping writes always work.
> Inspired by [kitfunso/hippo-memory](https://github.com/kitfunso/hippo-memory). Additive-only — does not change the base SQLite schema's existing semantics.

---

## 1. What problem does this solve?

The previous brain graph (`~/.copilot/brain-graph.db`) treated all nodes as equally true forever. Three failure modes:

| Failure mode | Symptom | Fix in this layer |
|---|---|---|
| **Knowledge rot** | Old superseded notes still surfaced by FTS | `node_memory.confidence='stale'` + exponential decay |
| **Conflicting facts** | Two ADRs both said "use X"; agent picked whichever ranked higher | `supersedes` edges — superseded loser drops 0.25 strength |
| **No usage signal** | Frequently-correct notes ranked the same as never-read ones | Reinforcement bumps on search/traverse/fetch + `node_access_log` |

The result: the graph now has a **memory** of which nodes were trusted, when they were last useful, and what they've been replaced by — without losing any historical data (append-only, supersedes is reversible).

---

## 2. Architecture at a glance

```
┌────────────────────────────────────────────────────────────────────┐
│                        Read path (gated)                           │
│                                                                    │
│  brain-graph-query.py search                                       │
│      │                                                             │
│      ▼                                                             │
│  FTS5 bm25 rank ── × ──→ apply_memory(blend) ──→ ranked results    │
│                          │                                         │
│                          ├── BLEND = bm25 × (0.5 + 0.5 × eff)      │
│                          ├── eff = strength × 0.5^(age/half_life)  │
│                          └── supersedes penalty: -0.25             │
│                                                                    │
│  IF BRAIN_DECAY_ENABLED=1 → blended order                          │
│  ELSE                     → pure bm25 (legacy behaviour)           │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ access logged either way
┌────────────────────────────────────────────────────────────────────┐
│                       Reinforce (always)                           │
│                                                                    │
│  Every hit bumps strength by:                                      │
│      search=+0.05  traverse=+0.05  fetch=+0.20                     │
│  And grows half_life by ×1.05 (capped at 180d, floor 0.05)         │
│  Bump is applied to the DECAYED strength, not the stored one       │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Admin (manual, agent-driven)                    │
│                                                                    │
│  brain-graph-admin.py                                              │
│    mark-confidence  ─ set verified/observed/inferred/stale         │
│    decide           ─ resolve conflict (winner supersedes loser)   │
│    inspect          ─ debug a node (memory + recent accesses)      │
│    list-stale       ─ enumerate decayed nodes                      │
│    mark-fresh       ─ reset strength=1.0 + last_retrieved_at=now   │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│              Sleep (launchd, daily 03:15 local)                    │
│                                                                    │
│  com.johnlin.brain-sleep → brain-sleep-cron.sh                     │
│    └── brain-sleep.py run-all                                      │
│          ├── mark-stale (eff_strength ≤ 0.10 → confidence='stale') │
│          └── prune-access-log (rows older than 90 days)            │
│    Lockfile: /tmp/brain-sleep.lock (single-instance)               │
│    Log:      ~/.copilot/logs/brain-sleep.log                       │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│           Consolidation (end of every pipeline)                    │
│                                                                    │
│  brain-consolidation.agent.md — rewritten to use:                  │
│    • brain-graph-query.py search    (dedup before write)           │
│    • SQL upsert + mark-confidence    (write knowledge)             │
│    • decide                          (resolve contradictions)      │
│    • SQLite is immediate — no git push, no .md files               │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. Schema additions

Two new tables, zero modifications to existing tables (`nodes`, `edges`, `nodes_fts` untouched).

```sql
CREATE TABLE node_memory (
    node_id          TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
    confidence       TEXT CHECK(confidence IN ('verified','observed','inferred','stale')),
    strength         REAL NOT NULL DEFAULT 1.0,
    half_life_days   REAL NOT NULL DEFAULT 7.0,
    last_retrieved_at TEXT NOT NULL DEFAULT (datetime('now')),
    retrieval_count  INTEGER NOT NULL DEFAULT 0,
    superseded_by    TEXT REFERENCES nodes(id),
    superseded_at    TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_node_memory_confidence ON node_memory(confidence);
CREATE INDEX idx_node_memory_superseded ON node_memory(superseded_by);

CREATE TABLE node_access_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT NOT NULL,
    operation   TEXT NOT NULL,        -- 'search' | 'traverse' | 'fetch'
    accessed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_node_access_log_node ON node_access_log(node_id);
CREATE INDEX idx_node_access_log_time ON node_access_log(accessed_at);
```

Migrated forward via `migrate-brain-decay.py` (idempotent, safe to re-run).

---

## 4. Constants (`brain_graph_memory.py`)

| Const | Value | Why |
|---|---|---|
| `DECAY_FLOOR` | 0.05 | Stale nodes are still findable, just down-weighted |
| `SUPERSEDES_PENALTY` | 0.25 | Loser of a `decide` call drops a quarter of its score |
| `BLEND_BASE` / `BLEND_SLOPE` | 0.5 / 0.5 | Preserves exact-match dominance even at low strength |
| `MAX_HALF_LIFE` | 180 days | Caps reinforcement runaway |
| `HALF_LIFE_GROWTH` | 1.05 | Each access slightly extends memory |
| `DEFAULT_HALF_LIFE` | 7.0 days | Conservative starting point |
| `BUMPS` | search/traverse 0.05, fetch 0.20 | Fetch = strongest signal of intent |
| `FEATURE_FLAG_ENV` | `BRAIN_DECAY_ENABLED` | Read-path opt-in; admin/sleep ignore it |

---

## 5. CLI cheatsheet

```bash
# Enable decay-aware ranking
export BRAIN_DECAY_ENABLED=1

# Search (now uses decay blend if flag set)
python3 ~/.copilot/scripts/brain-graph-query.py search \
    --query "media pipeline" --vault eroad-brain --compact

# Mark a node as verified ground truth
python3 ~/.copilot/scripts/brain-graph-admin.py mark-confidence \
    --node-id "eroad-brain/04 - Decisions/adr-015-stm-pattern" \
    --confidence verified

# Resolve a conflict (winner supersedes loser)
python3 ~/.copilot/scripts/brain-graph-admin.py decide \
    --winner "eroad-brain/04 - Decisions/adr-022-new-auth" \
    --loser  "eroad-brain/04 - Decisions/adr-009-old-auth"

# Inspect any node's memory state
python3 ~/.copilot/scripts/brain-graph-admin.py inspect \
    --node-id "eroad-brain/01 - Services/media-service"

# List currently-stale nodes
python3 ~/.copilot/scripts/brain-graph-admin.py list-stale --limit 20

# Reset a node back to "fresh"
python3 ~/.copilot/scripts/brain-graph-admin.py mark-fresh \
    --node-id "eroad-brain/01 - Services/media-service"

# Manual housekeeping (launchd does this daily at 03:15)
python3 ~/.copilot/scripts/brain-sleep.py run-all --dry-run
launchctl kickstart -k gui/$(id -u)/com.johnlin.brain-sleep
```

---

## 6. File inventory

### Production code (8 files)
| Path | Purpose | Phase |
|---|---|---|
| `scripts/migrate-brain-decay.py` | Idempotent schema migration | P1 |
| `scripts/brain_graph_memory.py` | `effective_strength()`, `apply_memory()`, constants | P2 |
| `scripts/brain-graph-query.py` | Read-path enrichment (gated on flag) | P2, P4 (edits) |
| `scripts/brain-graph-admin.py` | 5-subcommand admin CLI | P5 |
| `scripts/brain-sleep.py` | Housekeeping CLI (3 subcommands) | P6 |
| `scripts/brain-sleep-cron.sh` | launchd wrapper (lockfile + log) | P8 |
| `~/Library/LaunchAgents/com.johnlin.brain-sleep.plist` | Daily 03:15 schedule | P8 |
| `agents/brain-consolidation.agent.md` | Rewritten end-of-pipeline workflow | P7 |

### Test suites (8 files, 182 checks)
| Suite | Checks | Covers |
|---|---|---|
| `test-brain-decay-phase1.py` | 22 | Schema, indices, FK constraints, migration idempotency |
| `test-brain-memory.py` | 27 | `effective_strength`, `apply_memory`, blend formula, supersedes penalty |
| `test-brain-reinforce.py` | 16 | Bumps, half-life growth, decayed-base reinforcement |
| `test-brain-output.py` | 21 | search/traverse output enrichment, flag gating |
| `test-brain-admin.py` | 39 | All 5 admin subcommands, error handling, idempotency |
| `test-brain-sleep.py` | 27 | mark-stale, prune-access-log, run-all, dry-run, flag-off |
| `test-brain-consolidation-e2e.py` | 15 | Full documented playbook against real DB |
| `test-brain-sleep-cron.py` | 15 | Wrapper, plist, lockfile, launchd registration |

---

## 7. Troubleshooting

| Symptom | Diagnosis |
|---|---|
| Search results unchanged after enabling flag | `BRAIN_DECAY_ENABLED` not exported, or no `node_memory` rows exist yet (graph defaults to bm25 when no memory data) |
| `FOREIGN KEY constraint failed` on test cleanup | Some node has `superseded_by=<test-node>` — delete those memory rows first, then the test nodes |
| `mark-fresh` on a node that doesn't exist | Admin creates a minimal `node_memory` row with `confidence='observed'` — by design |
| brain-sleep skipped at 03:15 (no log entry) | Machine was asleep; `RunAtLoad=false` means launchd doesn't catch up. Manual kickstart works |
| `/tmp/brain-sleep.lock` orphaned | Wrapper checks `kill -0 $pid` and reclaims if dead; no manual cleanup needed |
| Want to disable decay temporarily | `unset BRAIN_DECAY_ENABLED` — falls back to pure bm25, all admin/sleep state preserved |

---

## 8. What's deliberately NOT included

- **No vector embeddings.** Hippo-memory uses embeddings; we stick with FTS5 + memory blend. Embeddings can be added as a future `node_embedding` table without touching this layer.
- **No automatic supersedes detection.** `decide` is explicitly agent/human-driven. We don't want a clustering algorithm silently rewriting the graph.
- **No write to remote DBs.** Brain is local SQLite only. Per global rules, agents never write to EROAD remote DBs.
- **No git commits of brain-graph.db.** It's a working file. The schema + scripts are versioned; the data is regenerated from source.

---

## 9. Rollback procedure

If something goes catastrophically wrong:

```bash
# 1. Disable the read path
unset BRAIN_DECAY_ENABLED

# 2. Stop the housekeeping cron
launchctl unload ~/Library/LaunchAgents/com.johnlin.brain-sleep.plist

# 3. (Nuclear) Drop the new tables — base graph is unaffected
sqlite3 ~/.copilot/brain-graph.db <<'SQL'
DROP TABLE IF EXISTS node_access_log;
DROP TABLE IF EXISTS node_memory;
SQL

# 4. Restore consolidation agent if needed
cp ~/.copilot/agents/brain-consolidation.agent.md.bak-20260529-153614 \
   ~/.copilot/agents/brain-consolidation.agent.md
```

All read tooling continues to work in legacy mode (pure bm25) after step 1.
