# Brain Graph Migration — Final Plan v3

**Status:** PLAN (Round 3 — FINAL, post-adversarial convergence)
**Date:** 2025-07-18
**Author:** Planner (adversarial collaboration with Critiquer, 3 rounds)

---

## Critique Response Dispositions (Round 2 → Round 3)

### 🔴 CRITICAL 1 — FTS TOKENIZATION PARITY WITH GREP NOT GUARANTEED
**ACCEPTED — concrete resolution.**

The critiquer is right that porter+unicode61 will tokenize `media-service` as two tokens (`media`, `servic`) while grep matches the literal hyphenated string. A narrow 20-query test set can pass while production queries fail on path-like terms, acronyms, and punctuation-embedded identifiers.

**Resolution:**
1. **Expanded frozen query suite**: 50 queries (up from 20), explicitly including:
   - 10 hyphenated identifiers (`media-service`, `central-service`, `configuration-core`)
   - 5 path-like terms (`01 - Services/media-service`)
   - 5 acronyms/abbreviations (`SQS`, `RUCUS`, `DVR`, `ELD`, `HOS`)
   - 5 code-like patterns (`onEldEvent`, `MediaServiceConfig`)
   - 5 domain compound terms (`mass-management`, `driver-safety`)
   - 20 standard keyword queries (existing set)
2. **Per-query parity check** (not just aggregate): For EACH of the 50 queries, `grep -ri` results ⊆ FTS results. Any single query where grep finds a file that FTS misses = FAIL.
3. **FTS tokenizer configuration**: Add `detail=full` to FTS5 and use phrase queries with `"media-service"` (FTS5 matches adjacent tokens in order). For terms where tokenization diverges, the query engine will issue both the phrase form AND the individual token form.
4. **Fallback token strategy**: Query rewriter that, for hyphenated terms, issues: `"media service"` (phrase) OR `media-service` (literal via LIKE on content column as backup).

**Schema change**: None — FTS5 with porter+unicode61 is kept, but the query engine compensates.

**AC-1 revised**: See §5.1 below.

---

### 🔴 CRITICAL 2 — SINGLE POINT OF FAILURE IN BATCHED CALL
**ACCEPTED — concrete resolution.**

The critiquer is right. A single Python script that does sync+FTS+rerank+expand+gap in one call has a wide failure surface. An ImportError, DB corruption, or unhandled exception = zero results. Feature flag doesn't help if the script never starts.

**Resolution: In-call fallback ladder.**

```python
def retrieve(query, vault, manifest, max_results):
    """Three-tier fallback. Each tier catches ALL exceptions from prior."""
    
    # Tier 1: Full pipeline (sync + FTS + graph rerank + expand + gap)
    try:
        ensure_db_readable(db_path)  # fast check: file exists, sqlite3 opens, nodes table exists
        incremental_sync_if_stale(vault, db_path, touched_paths=query_touched_paths(query))
        results = full_pipeline(query, vault, manifest, max_results)
        results['tier'] = 1
        return results
    except Exception as e:
        log_warning(f"Tier 1 (full pipeline) failed: {e}")
    
    # Tier 2: FTS-only (skip graph rerank/expand, skip sync)
    try:
        results = fts_only_search(query, vault, manifest, max_results)
        results['tier'] = 2
        results['degraded'] = True
        return results
    except Exception as e:
        log_warning(f"Tier 2 (FTS-only) failed: {e}")
    
    # Tier 3: Legacy grep fallback (no DB at all)
    try:
        results = legacy_grep_search(query, vault, manifest, max_results)
        results['tier'] = 3
        results['degraded'] = True
        return results
    except Exception as e:
        log_error(f"Tier 3 (grep fallback) failed: {e}")
    
    # Tier 4: Empty result with error signal (never silently fail)
    return {'results': [], 'tier': 4, 'error': 'All retrieval tiers failed', 'degraded': True}
```

**Key properties:**
- Each tier has its own `try/except Exception` — no shared failure mode
- Tier 3 (grep) has ZERO dependency on SQLite, NetworkX, or the DB file — it's the same code path as legacy retrieval
- Tier 4 returns empty results with explicit error, never raises to caller
- `results['tier']` field tells the agent which tier was used (for monitoring/debugging)
- `results['degraded']` flag lets the agent append "retrieval was degraded" to STM

**Import safety:** The script uses lazy imports within each tier. Tier 3 imports only `subprocess`, `os`, `json` (stdlib). Even if `networkx` fails to import, Tier 3 still works.

```python
# Top of script — only stdlib
import sys, os, json, subprocess, hashlib, time

# Lazy imports for Tier 1/2 — inside try blocks
def full_pipeline(...):
    import sqlite3     # stdlib, but connection can fail on corrupt DB
    import networkx    # pip dependency
    ...
```

---

### 🔴 CRITICAL 3 — 60s STALENESS WINDOW
**ACCEPTED — concrete resolution.**

The critiquer identifies a real race: brain-consolidation writes a file, brain-data-retrieval reads within 60s, gets stale FTS index. This is especially problematic in pipelines where write→read happens in the same orchestrator run.

**Resolution: Touched-path sync + age-based sync as backstop.**

The query engine accepts an optional `--touched-paths` argument (or reads from a well-known file):

```bash
python3 brain-graph-query.py \
  --vault eroad \
  --query "media-service" \
  --touched-paths "01 - Services/media-service.md,Brain/Learnings/Domain_Safety/new-learning.md"
```

**Sync logic (replaces pure age check):**

```python
def sync_if_needed(vault, db_path, touched_paths=None, max_age_seconds=60):
    """Sync specific paths immediately, full incremental if stale."""
    
    if touched_paths:
        # ALWAYS sync these paths, regardless of age
        for path in touched_paths:
            sync_single_file(vault, db_path, path)
    
    # Age-based full incremental sync as backstop
    if time.time() - last_sync_time(db_path) > max_age_seconds:
        incremental_sync(vault, db_path)
```

**Integration with brain-consolidation:**
The brain-consolidation agent already knows which files it writes. After writing, it appends those paths to `~/.copilot/brain-graph-touched.txt` (one path per line). The query engine reads and clears this file at query time.

```python
TOUCHED_PATHS_FILE = os.path.expanduser("~/.copilot/brain-graph-touched.txt")

def query_touched_paths(query):
    """Read and clear the touched-paths file."""
    if not os.path.exists(TOUCHED_PATHS_FILE):
        return []
    with open(TOUCHED_PATHS_FILE, 'r') as f:
        paths = [line.strip() for line in f if line.strip()]
    os.remove(TOUCHED_PATHS_FILE)  # clear after reading
    return paths
```

**Worst case (no touched-paths file):** Falls back to 60s age-based sync. This is the same as v2 — no regression.

**Best case (consolidation writes touched file):** Zero staleness for files written in the same pipeline.

---

### 🟠 MAJOR 1 — AC-3 USES MEAN ONLY
**ACCEPTED — concrete resolution.**

Mean ≤7 hides tail spikes. Adding percentile gates.

**AC-3 revised:**

| Metric | Threshold |
|---|---|
| Mean tool calls per retrieval | ≤ 7 |
| p95 tool calls per retrieval | ≤ 8 |
| Max tool calls per retrieval (any single run) | ≤ 10 |

Measured across 20 pipeline runs (up from 10). If p95 ≤ 8 but max = 11 on one outlier, that is a FAIL — investigate and fix before Phase 3.

---

### 🟠 MAJOR 2 — UNNORMALIZED GRAPH RERANK
**ACCEPTED — concrete resolution.**

Raw overlap count rewards dense clusters. A file with 8 of its 10 neighbors in the hit set scores the same as one with 8 of 200 neighbors, but the former is a much stronger signal.

**Resolution: Jaccard normalization + capped bonus.**

```python
def graph_rerank(fts_hits, graph):
    hit_ids = {h['id'] for h in fts_hits}
    for hit in fts_hits:
        neighbors = set(graph.neighbors(hit['id']))
        if not neighbors:
            hit['graph_bonus'] = 0.0
            continue
        overlap = neighbors & hit_ids
        jaccard = len(overlap) / len(neighbors | hit_ids)
        # Cap bonus at 0.5 to prevent graph from dominating BM25
        hit['graph_bonus'] = min(jaccard * 0.5, 0.5)
        hit['combined_score'] = hit['bm25_score'] + hit['graph_bonus']
    return sorted(fts_hits, key=lambda h: h['combined_score'], reverse=True)
```

**Properties:**
- Jaccard normalizes for cluster density (isolated doc with 2/3 neighbors in hits scores higher than hub with 8/200)
- Cap at 0.5 ensures BM25 remains the primary signal (BM25 scores are typically 2.0–15.0 for good matches)
- An isolated orphan with BM25=5.0 and graph_bonus=0.0 still outranks a weakly-related linked doc with BM25=3.0 and graph_bonus=0.5

---

### 🟠 MAJOR 3 — STATIC HUB CUTOFF (>50) IS BRITTLE
**ACCEPTED — concrete resolution.**

Static threshold won't survive vault growth or different vaults.

**Resolution: Percentile-based adaptive threshold.**

```python
def compute_hub_threshold(graph, percentile=98):
    """Top 2% of in-degree nodes are hubs. Recomputed at full sync time."""
    if graph.number_of_nodes() == 0:
        return 50  # safe default
    in_degrees = [graph.in_degree(n) for n in graph.nodes()]
    import numpy as np
    threshold = int(np.percentile(in_degrees, percentile))
    return max(threshold, 10)  # floor of 10 to avoid over-pruning in sparse graphs
```

**Current vault:** 98th percentile ≈ 48 (close to our static 50, validating the original heuristic).

**Stored in DB** at full sync time in `sync_meta` table. Incremental syncs read this value rather than recomputing. Recomputed weekly during full reconciliation.

```sql
INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('hub_threshold', '48');
```

**numpy dependency concern:** We don't need numpy for this. Pure Python fallback:

```python
def percentile_pure(values, pct):
    """Pure Python percentile (no numpy needed)."""
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_vals) else f
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])
```

---

### 🟠 MAJOR 4 — 1-HOP STALLS ON MULTI-HOP CHAINS
**ACCEPTED AS RISK — explicit justification.**

The critiquer suggests allowing constrained 2-hop when confidence is low. I **disagree on the implementation** but **accept the problem exists**.

**Why 2-hop is not worth the complexity:**
1. **Predictability**: 1-hop from 5 seeds = max 50 candidates. 2-hop from 5 seeds = up to 2,500 candidates. Even with strict caps, the result set becomes non-deterministic depending on traversal order.
2. **Diminishing returns on THIS vault**: With 80.6% orphans, 2-hop mostly re-traverses the same large component (553 nodes). The second hop adds noise, not signal.
3. **Real multi-hop chains are rare**: Empirically, the vault's dependency chains rarely exceed depth 2 (service → domain → department). The 1-hop + iterative NEED_DATA handles this in 2 calls.
4. **Cost of wrong 2-hop**: Surfacing 10 irrelevant 2-hop results wastes the agent's context window (which is the actual scarce resource, not tool calls).

**What we DO instead (compromise):**
- When the query returns < 3 FTS hits with BM25 > threshold, emit a `low_confidence: true` flag in the response
- The agent can then issue a targeted follow-up query with refined terms
- This is cheaper and more precise than speculative 2-hop expansion

**Risk accepted:** For chains A→B→C where C is the desired result and only A matches the query, the user must do two retrievals. This costs 1 extra tool call (within budget) and is preferable to 2-hop's non-determinism.

---

### 🟠 MAJOR 5 — ALIAS BASENAME COLLISION
**ACCEPTED — concrete resolution.**

Same filename in different directories (e.g., `media-service.md` under both `01 - Services/` and `Brain/Departments/.../Projects/`) can cause wrong canonical mapping if aliases only track basename.

**Resolution: Composite alias key.**

```sql
-- REVISED aliases table
CREATE TABLE aliases (
    vault TEXT NOT NULL,
    rel_path TEXT NOT NULL,           -- old relative path (primary lookup)
    content_hash TEXT,                -- hash at time of aliasing (for move detection)
    canonical_id TEXT NOT NULL,       -- current node ID
    alias_basename TEXT NOT NULL,     -- old basename (secondary hint for wiki-link resolution)
    created_at TEXT NOT NULL,
    PRIMARY KEY (vault, rel_path),
    FOREIGN KEY (canonical_id) REFERENCES nodes(id)
);

CREATE INDEX idx_aliases_basename ON aliases(alias_basename);
CREATE INDEX idx_aliases_canonical ON aliases(canonical_id);
```

**Wiki-link resolution order:**
1. Exact match on `nodes.basename` — if unique, done
2. If ambiguous (multiple nodes with same basename): match against `nodes.rel_path` using the wiki-link's path hint (e.g., `[[01 - Services/media-service]]` → match `01 - Services/media-service.md`)
3. If the link target doesn't exist in `nodes`: check `aliases.alias_basename` + `aliases.rel_path` for a renamed/moved file
4. If no match anywhere: create a dangling edge (target_id = `_unresolved/{link_text}`) for gap analysis

---

### 🟠 MAJOR 6 — RENAME/MOVE RACE CREATES DUPES
**ACCEPTED — concrete resolution.**

Delete + create events reordered (or observed in a single incremental sync walk) can produce a split identity: old node tombstoned AND new node created as separate entity.

**Resolution: Move detection heuristic in incremental sync.**

```python
def incremental_sync(vault, db_path):
    current_files = walk_vault(vault)  # {rel_path: (mtime, content_hash, size)}
    known_nodes = load_nodes(db_path)  # {rel_path: (content_hash, size, id)}
    
    new_files = set(current_files.keys()) - set(known_nodes.keys())
    deleted_files = set(known_nodes.keys()) - set(current_files.keys())
    
    # MOVE DETECTION: Before tombstoning deletes, check if any new file
    # has the same content_hash + similar size (±10%) as a deleted file.
    # If so, it's a move/rename, not delete+create.
    moves = detect_moves(new_files, deleted_files, current_files, known_nodes)
    
    for old_path, new_path in moves:
        # Update node in-place (same ID lineage)
        update_node_path(db_path, old_path, new_path)
        # Add alias from old path → new canonical
        add_alias(db_path, vault, old_path, current_files[new_path]['content_hash'], 
                  get_node_id(new_path))
        new_files.discard(new_path)
        deleted_files.discard(old_path)
    
    # Process remaining true deletes
    for path in deleted_files:
        tombstone_node(db_path, path)
    
    # Process remaining true creates
    for path in new_files:
        create_node(db_path, vault, path, current_files[path])

def detect_moves(new_files, deleted_files, current, known, size_tolerance=0.1):
    """Match new files to deleted files by content hash + size."""
    moves = []
    used_new = set()
    used_deleted = set()
    
    for deleted_path in deleted_files:
        d_hash = known[deleted_path]['content_hash']
        d_size = known[deleted_path]['size']
        for new_path in new_files:
            if new_path in used_new:
                continue
            n_hash = current[new_path]['content_hash']
            n_size = current[new_path]['size']
            # Exact hash match = definitely same content (rename/move)
            if d_hash == n_hash:
                moves.append((deleted_path, new_path))
                used_new.add(new_path)
                used_deleted.add(deleted_path)
                break
            # Similar size + same basename = probable move with minor edits
            if (abs(n_size - d_size) / max(d_size, 1) <= size_tolerance and
                os.path.basename(deleted_path) == os.path.basename(new_path)):
                moves.append((deleted_path, new_path))
                used_new.add(new_path)
                used_deleted.add(deleted_path)
                break
    
    return moves
```

**Edge case:** If a file is both moved AND substantially edited in one sync cycle, the hash won't match and basename may differ. This becomes a true delete + create. Acceptable — the alias from the weekly full reconciliation will eventually link them.

---

### 🟠 MAJOR 7 — GAP ANALYSIS DEPENDS ON DOMAIN LABELING QUALITY
**ACCEPTED — concrete resolution.**

If a file's domain is misclassified (e.g., a safety learning mis-tagged as "Core Data"), gap analysis reports "Safety: 0 hits" when a hit actually exists.

**Resolution:**

1. **Domain taxonomy from vault structure (not heuristics):**
   ```python
   DOMAIN_MAP = {
       '01 - Services': 'service',
       '02 - Domain Models': 'domain_model',
       '03 - Architecture': 'architecture',
       '04 - Decisions': 'decision',
       '06 - AI Agent Outputs': 'ai_output',
       'Brain/Departments': 'department',
       'Brain/Learnings': 'learning',
   }
   
   def classify_domain(rel_path):
       for prefix, domain in DOMAIN_MAP.items():
           if rel_path.startswith(prefix):
               return domain
       return 'unclassified'  # explicit unknown bucket
   ```

2. **Explicit `unclassified` domain:** Files that don't match any prefix go into `unclassified`. Gap analysis reports this bucket separately:
   ```json
   {
     "gap_analysis": {
       "service": {"total": 249, "hits": 3},
       "domain_model": {"total": 45, "hits": 0},
       "unclassified": {"total": 12, "hits": 1, "note": "12 files have unknown domain classification"}
     }
   }
   ```

3. **Domain validation at sync time:** Full sync logs any file whose domain changed since last sync (path prefix changed). Alerts if `unclassified` bucket exceeds 5% of vault.

4. **Sub-domain extraction for deeper directories:**
   For files under `Brain/Departments/Engineering/Domains/Safety/Projects/`, extract sub-domain from path:
   ```python
   # Extract "Safety" from "Brain/Departments/Engineering/Domains/Safety/Projects/x.md"
   def extract_subdomain(rel_path):
       parts = rel_path.split('/')
       if 'Domains' in parts:
           idx = parts.index('Domains')
           if idx + 1 < len(parts):
               return parts[idx + 1]
       return None
   ```

---

### 🟡 MINOR 1 — Weekly reconciliation too sparse after bulk edits
**ACCEPTED — concrete resolution.**

**Resolution:** In addition to the weekly full sync, trigger a full reconciliation when:
- Incremental sync detects ≥ 20 changes in a single run (bulk edit threshold)
- A manual `--force-full` flag is passed
- The `sync_meta.last_full_sync` is older than 7 days

```python
def should_full_sync(db_path, changes_detected):
    last_full = get_sync_meta(db_path, 'last_full_sync')
    days_since = (time.time() - parse_iso(last_full)) / 86400
    return (
        changes_detected >= 20 or   # bulk edit threshold
        days_since >= 7 or           # weekly backstop
        not last_full                # never done
    )
```

---

### 🟡 MINOR 2 — Rollout phases lack explicit abort criteria
**ACCEPTED — concrete resolution.**

**Revised rollout with abort criteria:**

| Phase | Mode | Duration | Gate to Proceed | Abort Criteria |
|---|---|---|---|---|
| 0 — Build | n/a | 1 week | Schema + sync + 50-query parity pass | >3 parity failures after fix attempts |
| 1 — Shadow | hybrid | 2 weeks | Graph logs collected, no crashes in 20+ runs | >2 unrecoverable Tier 1 failures per week |
| 2 — Validate | hybrid | 1 week | ALL AC-1 through AC-7 pass | Any AC gate fails after 1 fix iteration |
| 3 — Switch | graph | 2 weeks | No regressions in weekly benchmarks | Any benchmark dimension drops >5 points |
| 4 — Cleanup | graph | 1 week | 2 clean weeks in Phase 3 | Rollback to `legacy` flag if any regression |

**Abort action at any phase:** Set `brain_retrieval_mode` to `"legacy"` in feature-flags.json. Zero-downtime rollback. No code changes needed.

---

## [FINAL] §1.1 — SQLite Schema (revised from v2)

```sql
-- Nodes table (unchanged from v2 except clarifying comments)
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,          -- vault_scope + '/' + relative_path_without_ext
    vault TEXT NOT NULL,           -- 'eroad' or 'john'
    rel_path TEXT NOT NULL,        -- relative path from vault root, with .md
    basename TEXT NOT NULL,        -- filename without extension (for wiki-link matching)
    title TEXT,                    -- first H1 or basename
    content TEXT NOT NULL,         -- full markdown content (for FTS backing)
    content_hash TEXT NOT NULL,    -- SHA-256 of file content
    size_bytes INTEGER,
    modified_at TEXT,              -- ISO 8601 mtime
    domain TEXT,                   -- classified via DOMAIN_MAP (§MAJOR 7)
    subdomain TEXT,                -- extracted sub-domain for Brain/Departments paths
    indexed_at TEXT NOT NULL,
    tombstone INTEGER DEFAULT 0
);

-- FTS index (unchanged)
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    id, basename, title, content,
    tokenize='porter unicode61'
);

-- Edges table (unchanged from v2)
CREATE TABLE edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'wiki_link',
    weight REAL DEFAULT 1.0,
    PRIMARY KEY (source_id, target_id, edge_type),
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

-- REVISED aliases table (§MAJOR 5 — composite key, not basename-only)
CREATE TABLE aliases (
    vault TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    content_hash TEXT,
    canonical_id TEXT NOT NULL,
    alias_basename TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (vault, rel_path),
    FOREIGN KEY (canonical_id) REFERENCES nodes(id)
);

-- Sync metadata (§MAJOR 3 — stores adaptive hub threshold)
CREATE TABLE sync_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Sync log (unchanged from v2)
CREATE TABLE sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault TEXT NOT NULL,
    sync_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    files_added INTEGER DEFAULT 0,
    files_updated INTEGER DEFAULT 0,
    files_deleted INTEGER DEFAULT 0,
    files_moved INTEGER DEFAULT 0,  -- NEW: track moves separately
    edges_rebuilt INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running'
);

-- Indexes
CREATE INDEX idx_nodes_vault ON nodes(vault);
CREATE INDEX idx_nodes_basename ON nodes(basename);
CREATE INDEX idx_nodes_domain ON nodes(domain);
CREATE INDEX idx_nodes_tombstone ON nodes(tombstone);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_aliases_basename ON aliases(alias_basename);
CREATE INDEX idx_aliases_canonical ON aliases(canonical_id);
```

**Changes from v2:**
- `nodes` table adds `content` column (needed for Tier 2 FTS-only fallback) and `subdomain` column
- `aliases` table uses composite `(vault, rel_path)` PK instead of `(alias_basename, canonical_id)`
- `sync_log` adds `files_moved` counter
- `sync_meta` stores `hub_threshold` (adaptive, §MAJOR 3)

---

## [FINAL] §3 — Retrieval Pipeline (revised from v2)

### 3.1 Single-Call Batched API (with fallback ladder)

```bash
python3 ~/.copilot/scripts/brain-graph-query.py \
  --vault eroad \
  --query "media-service SQS event processing" \
  --manifest /path/to/manifest.json \
  --max-results 15 \
  --mode full
```

This ONE call performs internally (Tier 1):
1. **Read touched-paths file** — sync specific paths immediately if present (§CRITICAL 3)
2. **Incremental sync** (if stale >60s) — ~200ms backstop
3. **FTS search** with query rewriting for hyphenated terms (§CRITICAL 1)
4. **Graph re-rank** with Jaccard-normalized overlap + capped bonus (§MAJOR 2)
5. **1-hop expand** from top 5 hits, using adaptive hub threshold (§MAJOR 3)
6. **Merge + deduplicate** against manifest
7. **Gap analysis** with `unclassified` domain bucket (§MAJOR 7)
8. **Output** — structured JSON with ranked results + gap report + tier indicator

**Fallback ladder** (§CRITICAL 2):
- Tier 1 fails → Tier 2 (FTS-only, no graph)
- Tier 2 fails → Tier 3 (legacy grep, no DB)
- Tier 3 fails → Tier 4 (empty result with error signal)

### 3.2 Query Rewriting (§CRITICAL 1)

```python
def rewrite_query(raw_query):
    """Handle hyphenated terms, paths, and acronyms."""
    tokens = raw_query.split()
    fts_parts = []
    like_fallbacks = []
    
    for token in tokens:
        if '-' in token or '/' in token:
            # Hyphenated: issue phrase query + LIKE fallback
            clean = token.replace('-', ' ').replace('/', ' ')
            fts_parts.append(f'"{clean}"')  # FTS phrase: "media service"
            like_fallbacks.append(token)     # LIKE backup: %media-service%
        elif token.isupper() and len(token) <= 6:
            # Acronym: exact match (skip stemmer)
            fts_parts.append(f'"{token}"')
        else:
            fts_parts.append(token)
    
    return {
        'fts_query': ' '.join(fts_parts),
        'like_fallbacks': like_fallbacks,  # used only if FTS misses expected hits
    }
```

### 3.3 Hub-Aware Expansion (adaptive threshold)

```python
def expand_neighbors(node_id, graph, hub_threshold, max_neighbors=10):
    neighbors = list(graph.neighbors(node_id))
    neighbors = [n for n in neighbors if graph.in_degree(n) <= hub_threshold]
    neighbors.sort(key=lambda n: graph[node_id][n].get('weight', 1.0), reverse=True)
    return neighbors[:max_neighbors]
```

`hub_threshold` read from `sync_meta` table (computed at full sync as 98th percentile in-degree, floor of 10).

### 3.4 Low-Confidence Signal (§MAJOR 4 compromise)

When FTS returns < 3 hits above a BM25 threshold of 2.0:

```json
{
  "results": [...],
  "low_confidence": true,
  "suggestion": "Consider refining query terms or requesting specific file paths",
  "tier": 1
}
```

The agent can issue a follow-up query — this is cheaper and more precise than speculative 2-hop.

### 3.5 Output Format

```json
{
  "results": [
    {
      "id": "eroad/01 - Services/media-service",
      "rel_path": "01 - Services/media-service.md",
      "title": "media-service",
      "bm25_score": 8.5,
      "graph_bonus": 0.23,
      "combined_score": 8.73,
      "source": "fts"
    },
    {
      "id": "eroad/01 - Services/central-service",
      "rel_path": "01 - Services/central-service.md",
      "title": "central-service",
      "bm25_score": 0,
      "graph_bonus": 0,
      "combined_score": 0,
      "source": "graph_expand"
    }
  ],
  "gap_analysis": {
    "service": {"total": 249, "hits": 3},
    "domain_model": {"total": 45, "hits": 0, "negative_context": "No domain model docs matched"},
    "unclassified": {"total": 8, "hits": 0}
  },
  "low_confidence": false,
  "tier": 1,
  "degraded": false,
  "sync_stats": {"touched_paths_synced": 0, "incremental_run": true},
  "query_rewritten": "\"media service\" SQS event processing"
}
```

---

## [FINAL] §5 — Acceptance Criteria (revised from v2)

### 5.1 Hard Gates (must ALL pass before Phase 3)

| ID | Criterion | Measurement | Threshold |
|---|---|---|---|
| AC-1 | No coverage regression | Run **50** test queries (§CRITICAL 1 expanded set). For EACH query, files found by `grep -ri` must be ⊆ files found by graph mode. **Per-query check, not aggregate.** | 100% per-query parity (zero missed files on any query) |
| AC-2 | Gap handling improvement | Benchmark gap_handling dimension on P2-dvir-system prompt. | ≥ 80/100 |
| AC-3 | Tool call budget (mean) | Count tool calls per retrieval across **20** pipeline runs. | Mean ≤ 7 |
| AC-3a | Tool call budget (p95) | 95th percentile of tool calls. | p95 ≤ 8 |
| AC-3b | Tool call budget (max) | Maximum tool calls in any single run. | Max ≤ 10 |
| AC-4 | No hallucination regression | Benchmark no_hallucination dimension. | ≥ 85/100 |
| AC-5 | Overall retrieval score | Benchmark context_retrieval score. | ≥ 85/100 |
| AC-6 | Sync correctness | Full sync → incremental sync → full sync. Node/edge counts must match. | Exact match |
| AC-7 | Orphan reachability | Query for 10 known orphan files by keyword. All must be returned. | 100% |
| AC-8 | Fallback ladder works | Corrupt DB → Tier 2 activates. Delete DB → Tier 3 activates. Both return results. | Pass (manual test) |

### 5.2 Test Query Corpus (50 queries)

| Category | Count | Examples |
|---|---|---|
| Hyphenated identifiers | 10 | `media-service`, `central-service`, `configuration-core`, `task-media`, `driver-safety` |
| Path-like terms | 5 | `01 - Services/media-service`, `Brain/Learnings/Domain_Safety` |
| Acronyms | 5 | `SQS`, `RUCUS`, `DVR`, `ELD`, `HOS` |
| Code patterns | 5 | `onEldEvent`, `MediaServiceConfig`, `DriverHasFleets` |
| Domain compounds | 5 | `mass-management`, `driver-safety`, `vehicle-tracking` |
| Standard keywords | 15 | `auth patterns`, `database schema`, `API endpoints`, etc. |
| Negative queries | 5 | `kubernetes deployment`, `terraform modules` (not in vault) |

Each query has **expected results file list** frozen before implementation.

---

## [FINAL] §4.2 — Rollout Phases (revised with abort criteria)

| Phase | Mode | Duration | Gate to Proceed | Abort Criteria |
|---|---|---|---|---|
| 0 — Build | n/a | 1 week | Schema + sync + 50-query parity pass | >3 parity failures after fix attempts |
| 1 — Shadow | hybrid | 2 weeks | Graph logs collected, 0 crashes in 20+ runs | >2 unrecoverable Tier 1 failures per week |
| 2 — Validate | hybrid | 1 week | ALL AC-1 through AC-8 pass | Any AC gate fails after 1 fix iteration |
| 3 — Switch | graph | 2 weeks | No regressions in weekly benchmarks | Any benchmark dimension drops >5 points |
| 4 — Cleanup | graph | 1 week | 2 clean weeks in Phase 3 | Rollback to `legacy` flag |

**Abort = set `brain_retrieval_mode` to `"legacy"`. Zero downtime.**

---

## [FINAL] §7.1 — Phase 0 Build Tasks (revised)

| Task | Output | Notes |
|---|---|---|
| 7.1.1 Create SQLite schema | `brain-graph-schema.sql` | Includes revised aliases, sync_meta, subdomain |
| 7.1.2 Write sync engine | `brain-graph-sync.py` | With move detection (§MAJOR 6), bulk-edit trigger (§MINOR 1), touched-path sync (§CRITICAL 3) |
| 7.1.3 Write edge parser + tests | `brain-edge-parser.py` | Wiki-link resolution with disambiguation (§MAJOR 5) |
| 7.1.4 Write query engine | `brain-graph-query.py` | With fallback ladder (§CRITICAL 2), query rewriting (§CRITICAL 1), Jaccard rerank (§MAJOR 2), adaptive hub threshold (§MAJOR 3), low-confidence signal (§MAJOR 4) |
| 7.1.5 Write feature flag reader | In agent startup | Reads `feature-flags.json` |
| 7.1.6 Create test query corpus | `brain-graph-test-queries.json` | **50 queries** with expected results (§CRITICAL 1) |
| 7.1.7 Run full sync on eroad-brain | `~/.copilot/brain-graph.db` | Validate hub_threshold stored in sync_meta |
| 7.1.8 Validate AC-6, AC-7, AC-8 | Pass/fail | AC-8 = fallback ladder test |
| 7.1.9 Wire touched-paths integration | `brain-consolidation` writes `~/.copilot/brain-graph-touched.txt` | 2-line change in consolidation agent |

---

## [FINAL] §10 — Risk Register (Residual, v3)

| Risk | Likelihood | Impact | Mitigation | Accepted? |
|---|---|---|---|---|
| FTS5 tokenization diverges from grep on edge cases | Low | Medium | 50-query parity suite with per-query check. Query rewriter handles hyphenation + acronyms. | Mitigated |
| Single Python call fails completely | Low | High | 4-tier fallback ladder. Tier 3 = legacy grep with zero new dependencies. | Mitigated |
| Stale content during active editing | Low | Medium | Touched-paths file written by consolidation, read by query engine. 60s backstop. | Mitigated |
| 2-hop chains require iterative retrieval | Medium | Low | 1 extra tool call within budget. Low-confidence signal helps agent decide. | **ACCEPTED AS RISK** |
| Domain misclassification for files outside known path prefixes | Low | Low | `unclassified` bucket explicit in gap report. Alert if >5% of vault. | Mitigated |
| Move detection fails on simultaneous rename + major edit | Low | Low | Weekly full reconciliation catches drift. Alias created at next full sync. | **ACCEPTED AS RISK** |
| numpy not available for percentile calc | Negligible | Negligible | Pure Python fallback included. | Mitigated |
| 29MB vault includes binary (images) | Low | Low | Sync only `.md` files. | Mitigated |

---

## Summary: What Changed v2 → v3

### Changes Made

1. **FTS query rewriting** (CRITICAL 1): Hyphenated terms, acronyms, and path-like terms get rewritten to phrase queries + LIKE fallbacks. Test corpus expanded from 20 → 50 queries with per-query parity checks.

2. **4-tier fallback ladder** (CRITICAL 2): Full pipeline → FTS-only → legacy grep → empty+error. Lazy imports isolate dependency failures. Each tier has independent try/except.

3. **Touched-paths sync** (CRITICAL 3): brain-consolidation writes recently-modified paths to a well-known file. Query engine syncs those paths immediately, regardless of age timer. Zero-staleness for same-pipeline writes.

4. **AC-3 percentile gates** (MAJOR 1): Added p95 ≤ 8 and max ≤ 10 alongside mean ≤ 7. Measured across 20 runs.

5. **Jaccard-normalized rerank** (MAJOR 2): Graph bonus uses Jaccard similarity instead of raw overlap count. Capped at 0.5 to keep BM25 dominant.

6. **Adaptive hub threshold** (MAJOR 3): 98th percentile in-degree, computed at full sync, stored in sync_meta. Floor of 10 for sparse graphs.

7. **Composite alias keys** (MAJOR 5): Aliases keyed on `(vault, rel_path)` not `(alias_basename, canonical_id)`. Wiki-link resolution uses multi-step disambiguation.

8. **Move detection heuristic** (MAJOR 6): Content hash + basename matching before tombstoning. Prevents split identity on rename/move.

9. **Domain taxonomy with `unclassified` bucket** (MAJOR 7): Path-prefix-based classification, explicit unknown domain, >5% alert threshold.

10. **Bulk-edit sync trigger** (MINOR 1): ≥ 20 changes in incremental sync triggers full reconciliation.

11. **Abort criteria per rollout phase** (MINOR 2): Explicit abort conditions and rollback action (flag flip to legacy).

12. **AC-8 added** (new): Fallback ladder functional test — corrupt DB → Tier 2, missing DB → Tier 3.

### Risks Explicitly Accepted

1. **Multi-hop chains (MAJOR 4)**: 1-hop + iterative NEED_DATA instead of 2-hop. Costs 1 extra tool call in worst case. Accepted because 2-hop's non-determinism and noise outweigh the cost of an extra tool call on rare deep chains.

2. **Move + major edit in same sync cycle (MAJOR 6 edge case)**: If a file is renamed AND substantially edited between syncs, move detection fails and it becomes delete+create. Weekly full reconciliation catches this. Accepted because simultaneous rename+edit is extremely rare in this vault.
