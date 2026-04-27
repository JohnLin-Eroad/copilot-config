# Brain Graph Migration — Revised Plan v2

**Status:** PLAN (Round 2 — post-critique revision)
**Date:** 2025-07-18
**Author:** Planner (adversarial collaboration with Critiquer)

---

## Ground Truth (verified empirically)

| Metric | Value |
|---|---|
| Total vault files | 823 |
| Wiki-links | 3,398 |
| Files with ≥1 incoming link | 160 (19.4%) |
| Files with 0 incoming links (orphans) | 663 (80.6%) |
| Connected components (undirected) | 94 |
| Largest component | 553 files |
| Isolates (size-1 components) | 31 |
| Small components (2–5) | 52 |
| Top hub: Engineering | 240 incoming |
| Top hub: configuration-core | 134 incoming |
| Top hub: central-service | 120 incoming |
| Vault size | 29 MB (mostly images) |
| Text content | ~100 KB markdown |
| Current retrieval score | 85/100 |
| Current gap handling score | 70/100 |
| Current tool call budget | 10 max |
| Current tool calls used | 5–8 per retrieval |

**Key insight from empirical data:** 80.6% of files are orphans — far worse than the critiquer's estimate of 61.5%. BFS-only retrieval would cover only ~19.4% of the vault. This makes CRITICAL 1 and CRITICAL 2 even more severe than stated.

---

## Architecture Decision: FTS-Primary, Graph-Secondary

[REVISED — addresses CRITICAL 1, CRITICAL 2, CRITICAL 4]

The critiquer is right: grep on 100KB is already fast. The real bottlenecks are:
1. **Gap handling** (70/100) — the agent doesn't know what it doesn't know
2. **Relevance scoring** — crude 0–3 heuristic, no structural awareness
3. **Cross-domain discovery** — grep hits files but misses structural neighbors

**Decision:** The graph is NOT a replacement for keyword search. It is an **augmentation layer** that provides:
- **Edge-aware re-ranking** of FTS hits (structurally connected docs score higher)
- **1-hop expansion** from top FTS hits to discover related docs grep would miss
- **Gap detection** — the graph knows what exists and what doesn't, enabling confident negative context
- **Coverage metadata** — node/edge counts per domain enable "vault has N docs about X" assertions

The retrieval pipeline becomes:
```
FTS search (primary) → graph re-rank → 1-hop expand → merge + deduplicate → deliver
```

NOT:
```
seed → BFS → BFS → BFS (the Round 1 approach — ABANDONED)
```

---

## 1. Data Model

### 1.1 SQLite Schema

```sql
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,          -- vault_scope + '/' + relative_path_without_ext
    vault TEXT NOT NULL,           -- 'eroad' or 'john'
    rel_path TEXT NOT NULL,        -- relative path from vault root, with .md
    basename TEXT NOT NULL,        -- filename without extension (for wiki-link matching)
    title TEXT,                    -- first H1 or basename
    content_hash TEXT NOT NULL,    -- SHA-256 of file content (for incremental sync)
    size_bytes INTEGER,
    modified_at TEXT,              -- ISO 8601 mtime from filesystem
    domain TEXT,                   -- extracted from path: '01 - Services', 'Brain/Learnings', etc.
    indexed_at TEXT NOT NULL,      -- when this node was last synced
    tombstone INTEGER DEFAULT 0   -- 1 = deleted from vault, retained for rename detection
);

-- FTS index for keyword search (replaces grep)
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    id, basename, title, content,
    tokenize='porter unicode61'
);

CREATE TABLE edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'wiki_link',  -- wiki_link | yaml_dep | folder_sibling
    weight REAL DEFAULT 1.0,
    PRIMARY KEY (source_id, target_id, edge_type),
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

-- Rename aliases for MAJOR 3
CREATE TABLE aliases (
    alias_basename TEXT NOT NULL,  -- old basename or case variant
    canonical_id TEXT NOT NULL,    -- current node ID
    PRIMARY KEY (alias_basename, canonical_id),
    FOREIGN KEY (canonical_id) REFERENCES nodes(id)
);

-- Sync metadata for MAJOR 4
CREATE TABLE sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault TEXT NOT NULL,
    sync_type TEXT NOT NULL,       -- 'incremental' or 'full'
    started_at TEXT NOT NULL,
    completed_at TEXT,
    files_added INTEGER DEFAULT 0,
    files_updated INTEGER DEFAULT 0,
    files_deleted INTEGER DEFAULT 0,
    edges_rebuilt INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running'  -- running | completed | failed
);

CREATE INDEX idx_nodes_vault ON nodes(vault);
CREATE INDEX idx_nodes_basename ON nodes(basename);
CREATE INDEX idx_nodes_domain ON nodes(domain);
CREATE INDEX idx_nodes_tombstone ON nodes(tombstone);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_aliases_basename ON aliases(alias_basename);
```

[REVISED — addresses MAJOR 3] Node IDs are vault-scoped: `eroad/01 - Services/media-service` not just `01 - Services/media-service`. Aliases table handles renames and case variants.

[REVISED — addresses MAJOR 4] Content hash + tombstones + sync_log enable incremental sync with drift detection.

### 1.2 In-Memory Graph (NetworkX)

Loaded lazily from `edges` table. Used ONLY for:
- 1-hop neighbor expansion from FTS hits
- Degree queries (hub detection)
- Connected component analysis (gap detection)

NOT used for multi-hop BFS traversal (abandoned per CRITICAL 1/2).

---

## 2. Sync Engine (`brain-graph-sync.py`)

### 2.1 Full Sync

Run on first build and weekly (Sunday night via launchd).

```
1. Walk vault directory, compute content_hash for each .md file
2. For each file: INSERT OR REPLACE into nodes + nodes_fts
3. Rebuild ALL edges from scratch (parse wiki-links, yaml deps, folder siblings)
4. Mark any node not seen in walk as tombstone=1
5. Rebuild aliases from tombstoned nodes (old basename → current canonical)
6. Log to sync_log with sync_type='full'
7. VACUUM and ANALYZE
```

### 2.2 Incremental Sync

Run at pipeline start (takes <500ms on 823 files).

```
1. Walk vault, compare mtime + content_hash against nodes table
2. For changed files only: update node, rebuild that file's outgoing edges
3. For deleted files: set tombstone=1, add alias entry
4. For new files: insert node + edges
5. Log to sync_log with sync_type='incremental'
```

[REVISED — addresses MAJOR 4] Content hash comparison catches mtime-granularity races. Full weekly sync catches any drift. Tombstones + aliases handle deletes/renames without data loss.

### 2.3 Edge Extraction

```python
EDGE_TYPES = {
    'wiki_link': r'\[\[([^\]|]+)',           # [[Target]] or [[Target|alias]]
    'yaml_dep':  r'depends[_-]on:\s*(.+)',   # YAML frontmatter dependency
    'folder_sibling': None,                   # computed: same parent directory
}
```

Edge weights:
- `wiki_link`: 1.0 (standard)
- `yaml_dep`: 1.5 (stronger signal — explicit dependency declaration)
- `folder_sibling`: 0.3 (weak — co-location, not explicit linkage)

[REVISED — addresses MINOR 1] Test corpus: 50 representative files covering each edge type. Parser validated against manually-counted edges before deployment.

---

## 3. Retrieval Pipeline (`brain-graph-query.py`)

[REVISED — addresses CRITICAL 1, CRITICAL 2, CRITICAL 3, CRITICAL 4, MAJOR 1, MAJOR 2]

### 3.1 Single-Call Batched API

The retrieval agent calls ONE script that does everything:

```bash
python3 ~/.copilot/scripts/brain-graph-query.py \
  --vault eroad \
  --query "media-service SQS event processing" \
  --manifest /path/to/manifest.json \
  --max-results 15 \
  --mode full           # full | search-only | expand-only
```

This ONE call performs internally:
1. **Incremental sync** (if stale >60s) — ~200ms
2. **FTS search** on `nodes_fts` — returns top 20 keyword hits with BM25 scores
3. **Graph re-rank** — for each FTS hit, compute graph_score = BM25 + 0.3 × (neighbor overlap with other hits)
4. **1-hop expand** — for top 5 re-ranked hits, fetch direct neighbors (wiki_link + yaml_dep only, NOT folder_sibling)
5. **Hub guard** — if a neighbor has in-degree > 50, skip it (it's a hub, not informative) [MAJOR 1]
6. **Merge + deduplicate** against manifest (skip already-fetched files)
7. **Gap analysis** — count nodes per domain, report domains with 0 hits as negative context
8. **Output** — structured JSON with ranked results + gap report

**Tool call budget impact:** This replaces 3–4 grep calls with 1 python call. Net budget usage:

| Step | Calls | Notes |
|---|---|---|
| Sync + Search + Expand (batched) | 1 | `brain-graph-query.py --mode full` |
| Read top results (batched cat) | 2–3 | Read 5–10 files in 2–3 batched reads |
| Write STM | 1 | Write brain data section |
| Negative context | 0 | Included in query output |
| Manifest update | 1 | Single manifest write |
| **Total** | **5–6** | **vs current 5–8** |

[CRITICAL 3 resolved] Budget is 5–6 calls vs 10 max. Leaves 4–5 calls for edge cases, mid-pipeline requests, and manifest housekeeping.

### 3.2 Hub-Aware Expansion [MAJOR 1]

```python
def expand_neighbors(node_id, graph, max_neighbors=10):
    neighbors = graph.neighbors(node_id)
    # Filter: skip hubs (in-degree > 50)
    neighbors = [n for n in neighbors if graph.in_degree(n) <= 50]
    # Sort by edge weight (yaml_dep > wiki_link > folder_sibling)
    neighbors.sort(key=lambda n: graph[node_id][n].get('weight', 1.0), reverse=True)
    return neighbors[:max_neighbors]
```

Hub threshold of 50 is derived from the data: the top 3 hubs have 120–240 incoming links. The 10th-ranked node has 38. A threshold of 50 cleanly separates hubs from informative nodes.

### 3.3 No Deep BFS [MAJOR 2]

[REVISED] The Round 1 plan proposed BFS to depth 3 with 50-node cap. This is abandoned.

The revised approach uses exactly 1-hop expansion from FTS hits. This is:
- Predictable (no truncation of deep paths — there are no deep paths)
- Fast (1 hop from 5 seeds = max 50 candidates pre-filter, ~10 post-filter)
- Sufficient (the graph's value is in direct relationships, not transitive chains)

For deep dependency chains (e.g., A → B → C → D), the agent fetches A via FTS, discovers B via 1-hop, and if B mentions C, the agent can request a second retrieval for C in a follow-up call. This is deliberate — deep chains are rare and better handled by iterative NEED_DATA requests than speculative deep traversal.

### 3.4 Orphan Coverage [CRITICAL 1]

80.6% of files are orphans (zero incoming links). These are ONLY reachable via FTS. The revised pipeline guarantees:

1. FTS is ALWAYS the primary retrieval path — every query hits the FTS index
2. Graph expansion is additive — it can only ADD results, never REMOVE FTS hits
3. Orphans are fully indexed in `nodes_fts` — they have the same FTS discoverability as linked files

**Coverage guarantee:** Any file findable by current `grep -r` is findable by FTS5 (same tokenization, better ranking). Coverage ≥ 100% of current grep approach.

### 3.5 Cross-Component Discovery [CRITICAL 2]

The vault has 94 connected components. A global learning about auth in component #7 is unreachable via BFS from component #1. But it IS reachable via FTS — the keyword "auth" matches regardless of graph structure.

The graph's role is limited to augmenting FTS hits with structural context, not replacing keyword search. Cross-component documents are found by FTS first, then their local graph neighborhood is explored for additional context.

---

## 4. Feature Flag & Rollout [REVISED — addresses MAJOR 6]

### 4.1 Runtime Feature Flag

```bash
# ~/.copilot/config/feature-flags.json
{
  "brain_retrieval_mode": "legacy",  # "legacy" | "graph" | "hybrid"
  "graph_db_path": "~/.copilot/brain-graph.db",
  "fallback_on_error": true
}
```

- **legacy**: Current grep-based retrieval. No graph involved.
- **graph**: New FTS + graph pipeline. Falls back to legacy if `fallback_on_error` is true.
- **hybrid**: Runs BOTH, merges results, logs divergence. For A/B comparison during validation.

The `brain-data-retrieval` agent reads this flag at startup. No agent prompt changes needed for switching modes. [MAJOR 6 resolved — runtime flag, not file-level switching]

### 4.2 Rollout Phases

| Phase | Mode | Duration | Gate |
|---|---|---|---|
| 0 — Build | n/a | 1 week | Schema + sync + tests pass |
| 1 — Shadow | hybrid | 2 weeks | Graph results logged but not used for delivery |
| 2 — Validate | hybrid | 1 week | A/B comparison against acceptance criteria |
| 3 — Switch | graph | ongoing | Flag flip, legacy code retained |
| 4 — Cleanup | graph | 1 week | Remove legacy grep paths after 2 weeks clean |

---

## 5. Acceptance Criteria [REVISED — addresses CRITICAL 4, CRITICAL 5]

### 5.1 Hard Gates (must ALL pass before Phase 3)

| ID | Criterion | Measurement | Threshold |
|---|---|---|---|
| AC-1 | No coverage regression | Run 20 test queries. Count files returned by graph mode vs legacy grep. Graph must return ≥ all grep results. | 100% (zero missed files) |
| AC-2 | Gap handling improvement | Benchmark gap_handling dimension on P2-dvir-system prompt. Currently 70/100. | ≥ 80/100 |
| AC-3 | Tool call budget | Count tool calls per retrieval across 10 pipeline runs. | ≤ 7 (mean) |
| AC-4 | No hallucination regression | Benchmark no_hallucination dimension. Currently 85/100. | ≥ 85/100 |
| AC-5 | Overall retrieval score | Benchmark context_retrieval score. Currently 85/100. | ≥ 85/100 |
| AC-6 | Sync correctness | Full sync → incremental sync → full sync. Node/edge counts must match. | Exact match |
| AC-7 | Orphan reachability | Query for 10 known orphan files by keyword. All must be returned. | 100% |

### 5.2 Stretch Goals (nice-to-have, not gates)

| ID | Goal | Target |
|---|---|---|
| SG-1 | Retrieval score improvement | ≥ 90/100 |
| SG-2 | Gap handling score | ≥ 85/100 |
| SG-3 | Cross-domain discovery | Graph expansion surfaces ≥ 2 relevant files per query that grep misses |

### 5.3 Test Corpus

20 test queries spanning:
- Single-service lookup (e.g., "media-service endpoints")
- Cross-domain query (e.g., "auth patterns across services")
- Deep dependency chain (e.g., "what depends on configuration-core")
- Orphan file retrieval (e.g., "360-backoffice" — an orphan with 0 incoming links)
- Negative query (e.g., "kubernetes deployment" — not in vault)

Each query has expected results defined before implementation (test-first).

---

## 6. Session State & Lifecycle [REVISED — addresses MAJOR 5]

### 6.1 No Persistent Prune State

The Round 1 plan proposed session-scoped prune state. This is abandoned.

The revised approach has NO mutable session state in the graph. The graph is a read-only derived index. Pruning decisions are made per-query in `brain-graph-query.py` and discarded after the response. The manifest (which tracks what was fetched) is the only per-session state, and it already has a well-defined lifecycle managed by `brain-manifest.sh`.

[MAJOR 5 resolved] No TTL needed, no undo semantics needed, no cross-session leaks possible.

### 6.2 Query-Time Filtering

Instead of mutating graph state, filtering happens in the query:

```python
def query(terms, manifest_fetched_ids):
    fts_hits = fts_search(terms)
    expanded = expand_neighbors(fts_hits[:5])
    merged = fts_hits + expanded
    # Exclude already-fetched (from manifest)
    merged = [n for n in merged if n.id not in manifest_fetched_ids]
    return rank(merged)
```

---

## 7. Implementation Plan

### 7.1 Phase 0 — Build (Week 1)

| Task | Output | Owner |
|---|---|---|
| 7.1.1 Create SQLite schema | `brain-graph-schema.sql` | developer |
| 7.1.2 Write sync engine | `brain-graph-sync.py` | developer |
| 7.1.3 Write edge parser + test corpus (50 files) | `brain-edge-parser.py` + tests | developer |
| 7.1.4 Write query engine | `brain-graph-query.py` | developer |
| 7.1.5 Write feature flag reader | Reads `feature-flags.json` at agent startup | developer |
| 7.1.6 Create test query corpus (20 queries) | `brain-graph-test-queries.json` | developer |
| 7.1.7 Run full sync on eroad-brain | `~/.copilot/brain-graph.db` populated | developer |
| 7.1.8 Validate: AC-6 (sync correctness), AC-7 (orphan reachability) | Pass/fail | developer |

### 7.2 Phase 1 — Shadow (Weeks 2–3)

| Task | Output | Owner |
|---|---|---|
| 7.2.1 Add `--mode hybrid` to retrieval agent | Agent runs both paths, logs divergence | developer |
| 7.2.2 Collect divergence data over 20+ real pipeline runs | `shadow-results.json` | automated |
| 7.2.3 Analyze: what does graph find that grep misses? What does grep find that graph misses? | Analysis report | developer |

### 7.3 Phase 2 — Validate (Week 4)

| Task | Output | Owner |
|---|---|---|
| 7.3.1 Run benchmark suite with graph mode | Scores for AC-1 through AC-7 | benchmark-runner |
| 7.3.2 Go/no-go decision | All AC-1 through AC-7 pass → proceed. Any fail → fix or abort. | human |

### 7.4 Phase 3 — Switch (Week 5)

| Task | Output | Owner |
|---|---|---|
| 7.4.1 Flip flag to `"graph"` | `feature-flags.json` update | human |
| 7.4.2 Monitor for 2 weeks | No regressions in weekly benchmarks | automated |

### 7.5 Phase 4 — Cleanup (Week 7)

| Task | Output | Owner |
|---|---|---|
| 7.5.1 Remove legacy grep paths from agent | Simplified agent prompt | developer |
| 7.5.2 Archive legacy code | Git tag `legacy-grep-retrieval` | developer |

---

## 8. File Locations

All new files live under `~/.copilot/scripts/` and `~/.copilot/config/`:

```
~/.copilot/
├── scripts/
│   ├── brain-graph-sync.py      # Sync engine
│   ├── brain-graph-query.py     # Query engine (FTS + graph)
│   ├── brain-edge-parser.py     # Edge extraction + test harness
│   └── brain-manifest.sh        # Existing manifest manager (unchanged)
├── config/
│   ├── feature-flags.json       # Runtime mode switching
│   └── brain-graph-test-queries.json  # 20 test queries with expected results
├── brain-graph.db               # SQLite database (derived, not committed)
└── ...
```

[REVISED — addresses MINOR 2] Scripts are Python (not bash) for the graph/query logic, reducing shell fragility. The only bash dependency is the existing `brain-manifest.sh` which is already proven. Python 3 is guaranteed present (macOS ships it, and it's used by existing copilot scripts).

---

## 9. Critique Response Matrix

| Finding | Severity | Resolution | Section |
|---|---|---|---|
| CRITICAL 1 — Orphan coverage regression | 🔴 | FTS is primary path. Graph is additive only. 80.6% orphans fully covered by FTS. | §3.4 |
| CRITICAL 2 — Connected-component lock-in | 🔴 | FTS searches across all components. Graph expansion is local augmentation, not primary retrieval. | §3.5 |
| CRITICAL 3 — 10-call budget mismatch | 🔴 | Batched single-call query engine. 5–6 calls total vs 10 budget. | §3.1 |
| CRITICAL 4 — Solving speed not quality | 🔴 | Graph targets gap handling (70→80+) and relevance scoring, not speed. Acceptance criteria gate on quality benchmarks. | §5.1 |
| CRITICAL 5 — No acceptance criteria | 🔴 | 7 hard gates with measurable thresholds. Go/no-go at Phase 2. | §5.1 |
| MAJOR 1 — Hub node explosion | 🟠 | In-degree > 50 filter. Data-derived threshold. | §3.2 |
| MAJOR 2 — Depth/node caps truncate paths | 🟠 | No deep BFS. 1-hop only. Deep chains handled by iterative NEED_DATA. | §3.3 |
| MAJOR 3 — Deterministic slug ID collisions | 🟠 | Vault-scoped IDs + aliases table for renames. | §1.1 |
| MAJOR 4 — Incremental sync drift | 🟠 | Content hash + tombstones + weekly full reconciliation. | §2.2 |
| MAJOR 5 — Session prune state leaks | 🟠 | No mutable graph state. Query-time filtering only. Manifest is sole session state. | §6.1 |
| MAJOR 6 — Rollback not behaviorally safe | 🟠 | Runtime feature flag (legacy/graph/hybrid). No prompt-level switching. | §4.1 |
| MINOR 1 — Edge extraction quality | 🟡 | 50-file test corpus validated before deployment. | §2.3 |
| MINOR 2 — Script packaging fragility | 🟡 | Python scripts (not bash) for graph logic. Single Python 3 dependency. | §8 |

---

## 10. Risk Register (Residual)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FTS5 tokenization misses grep-findable terms | Low | Medium | AC-1 tests for zero coverage regression. Hybrid mode catches divergence in shadow phase. |
| 29MB vault includes non-text (images). Sync slow on large files. | Low | Low | Sync only .md files. Skip binary. |
| NetworkX memory on 823-node graph | Negligible | Negligible | 823 nodes + 3398 edges ≈ 2MB RAM. |
| Python 3 version differences across machines | Low | Low | Require 3.9+. No exotic dependencies (sqlite3 and networkx only). |
| Feature flag misconfigured (wrong mode) | Low | Medium | Default to legacy. Explicit logging of active mode at agent startup. |

---

## Summary of Key Changes from Round 1

1. **FTS-primary, not BFS-primary** — the biggest architectural shift. Graph augments keyword search, doesn't replace it.
2. **1-hop only, no deep BFS** — simpler, predictable, no truncation risk.
3. **Batched single-call query** — 1 Python call replaces 4+ grep calls. Fits in tool budget.
4. **Hard acceptance criteria** — 7 gates with measurable thresholds, tested before rollout.
5. **Runtime feature flag** — switch modes without touching agent prompts.
6. **No mutable session state** — graph is read-only index, manifest handles session state.
7. **Vault-scoped IDs + aliases** — handles renames and multi-vault correctly.
8. **Content hash sync** — drift-proof incremental updates.
