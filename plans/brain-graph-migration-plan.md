# Brain Graph Migration Plan

**Status:** PLAN — awaiting approval  
**Author:** Copilot (adversarial planning mode)  
**Date:** 2025-07-15  
**Blast Radius:** MEDIUM (new capability, non-destructive, vault unchanged)

---

## Executive Summary

Migrate the EROAD brain from grep-on-filesystem retrieval to a local SQLite + NetworkX graph with FTS5 full-text search. The Obsidian vault remains the source of truth — the graph is a derived index rebuilt in <2 seconds from 823 markdown files. Agents get a single CLI tool (`brain-graph`) that replaces `find`/`grep` with O(1) adjacency lookups, O(log n) full-text search, and native BFS traversal with session-scoped pruning.

**Key numbers:**
- 823 nodes, ~3,400 edges, ~1.8MB content
- Full rebuild: <2s. Incremental sync: <500ms
- BFS 2-layer expansion: <50ms (entire graph fits in memory)
- Zero infrastructure — pure Python, SQLite (built-in), NetworkX (pip install)

---

## 1. Technology Choice: SQLite + NetworkX + FTS5

### Decision

**Primary store:** SQLite 3 with FTS5 extension  
**In-memory graph:** NetworkX (loaded on demand for BFS)  
**Language:** Python 3.12 (already installed)  
**Location:** `~/.copilot/brain-graph/eroad.db` (and `john.db`)

### Why This Stack

| Criterion | SQLite+NetworkX | Neo4j | Pure NetworkX | DuckDB |
|-----------|----------------|-------|---------------|--------|
| Zero infrastructure | ✅ built-in | ❌ Docker/JVM | ✅ | ✅ |
| Persistent storage | ✅ | ✅ | ❌ must serialize | ✅ |
| Native BFS | ✅ via NetworkX | ✅ Cypher | ✅ | ❌ |
| Full-text search | ✅ FTS5 | ✅ Lucene | ❌ | ✅ |
| Ecosystem precedent | ✅ john-brain uses SQLite | ❌ | ❌ | ❌ |
| Graph viz/debug | ✅ NetworkX + matplotlib | ✅ browser | ✅ | ❌ |
| Startup latency | <100ms | ~5s cold start | <50ms | ~200ms |
| pip install size | ~2MB (networkx) | N/A | ~2MB | ~80MB |

**Rejected alternatives:**
- **Neo4j**: Requires Docker or JVM. 5s cold start. Overkill for 823 nodes. Agent tooling can't easily talk Bolt protocol.
- **Pure NetworkX (pickle serialized)**: No full-text search. No SQL for metadata queries. No concurrent access safety.
- **DuckDB**: Excellent for analytics but no native graph traversal. Would need recursive CTEs for BFS — clunky and slow for multi-hop.
- **igraph**: Faster than NetworkX for huge graphs (millions of nodes). At 823 nodes, irrelevant. NetworkX has better Python API.

### Dependencies

```bash
pip3 install networkx pyyaml  # only new deps; sqlite3 is built-in
```

`pyyaml` is already installed (confirmed in pip list). `networkx` is the only new dependency.

---

## 2. Data Model

### 2.1 Node Table

```sql
CREATE TABLE nodes (
    id          TEXT PRIMARY KEY,   -- slug: "services/media-service"
    vault       TEXT NOT NULL,      -- "eroad" or "john"
    path        TEXT NOT NULL,      -- relative path: "01 - Services/media-service.md"
    type        TEXT NOT NULL,      -- enum: service|domain_model|architecture|decision|domain|project|learning|ai_output|standard|index
    title       TEXT NOT NULL,      -- human-readable: "media-service"
    content     TEXT NOT NULL,      -- full markdown content
    summary     TEXT,               -- first description paragraph or first 500 chars
    content_hash TEXT NOT NULL,     -- SHA256 for change detection
    tags        TEXT DEFAULT '[]',  -- JSON array: ["service","java","spring-boot"]
    metadata    TEXT DEFAULT '{}',  -- JSON: all YAML frontmatter
    tribe       TEXT,               -- extracted: "SUSTAIN", "DIME", etc.
    squad       TEXT,               -- extracted: "Video Safety", etc.
    domain_name TEXT,               -- extracted: "Safety", "Core Data", etc.
    file_mtime  TEXT NOT NULL,      -- ISO8601 file modification time
    last_synced TEXT NOT NULL,      -- ISO8601 when this node was last synced to graph
    line_count  INTEGER DEFAULT 0   -- for compression decisions
);

CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_vault ON nodes(vault);
CREATE INDEX idx_nodes_domain ON nodes(domain_name);
CREATE INDEX idx_nodes_path ON nodes(path);
```

### 2.2 Edge Table

```sql
CREATE TABLE edges (
    source_id   TEXT NOT NULL REFERENCES nodes(id),
    target_id   TEXT NOT NULL REFERENCES nodes(id),
    type        TEXT NOT NULL,      -- enum below
    label       TEXT,               -- human-readable: "syncs boundaries to"
    metadata    TEXT DEFAULT '{}',  -- JSON: flow description, direction, etc.
    weight      REAL DEFAULT 1.0,   -- for future relevance scoring
    PRIMARY KEY (source_id, target_id, type)
);

CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_type ON edges(type);
```

### 2.3 Edge Types (Enumerated)

| Edge Type | Source → Target | Extracted From | Count (est.) |
|-----------|----------------|----------------|--------------|
| `wiki_link` | any → any | `[[path/to/note]]` patterns | ~3,400 |
| `parent_repo` | submodule → repo | `**Parent Repo:** [[...]]` | ~249 |
| `related_entity` | domain_model → domain_model | `related:` frontmatter | ~30 |
| `owns_service` | domain_model → service | `owning_services:` frontmatter | ~20 |
| `integration` | service → service | `## Integration Graph` table rows | ~500 |
| `related_service` | service → service | `## Related Services` section | ~600 |
| `domain_has_service` | domain → service | Domain file service lists + Projects/ | ~300 |
| `domain_has_learning` | domain → learning | `[[Brain/Learnings/Domain_X/...]]` | ~20 |
| `department_has_domain` | department → domain | `[[Brain/Departments/...]]` | ~20 |
| `has_project` | domain → project | Files in `Domains/X/Projects/` | ~200 |

**Integration sub-types** (stored in `metadata.direction`):
- `INBOUND` — another service calls this one
- `OUTBOUND` — this service calls another
- `BIDIRECTIONAL` — both directions

### 2.4 FTS5 Virtual Table

```sql
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    title,
    content,
    tags,
    summary,
    domain_name,
    content='nodes',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, title, content, tags, summary, domain_name)
    VALUES (new.rowid, new.title, new.content, new.tags, new.summary, new.domain_name);
END;

CREATE TRIGGER nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, title, content, tags, summary, domain_name)
    VALUES ('delete', old.rowid, old.title, old.content, old.tags, old.summary, old.domain_name);
END;

CREATE TRIGGER nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, title, content, tags, summary, domain_name)
    VALUES ('delete', old.rowid, old.title, old.content, old.tags, old.summary, old.domain_name);
    INSERT INTO nodes_fts(rowid, title, content, tags, summary, domain_name)
    VALUES (new.rowid, new.title, new.content, new.tags, new.summary, new.domain_name);
END;
```

### 2.5 Session Prune Table (Ephemeral)

```sql
-- Created per-session, stored in same DB but cleared per invocation
CREATE TABLE IF NOT EXISTS session_prune (
    session_id  TEXT NOT NULL,      -- STM task slug or UUID
    node_id     TEXT NOT NULL,      -- pruned node
    pruned_at   TEXT NOT NULL,      -- ISO8601
    reason      TEXT,               -- optional: "irrelevant to security task"
    PRIMARY KEY (session_id, node_id)
);

CREATE INDEX idx_prune_session ON session_prune(session_id);
```

### 2.6 Sync Metadata Table

```sql
CREATE TABLE sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Stores: last_full_build, last_incremental_sync, vault_path, node_count, edge_count
```

---

## 3. Node ID Scheme

Deterministic, human-readable slugs derived from file paths:

| File Path | Node ID |
|-----------|---------|
| `01 - Services/media-service.md` | `services/media-service` |
| `01 - Services/central-service/central-service-core.md` | `services/central-service/central-service-core` |
| `02 - Domain Models/Driver.md` | `models/driver` |
| `03 - Architecture/sovereign-v2-spec.md` | `architecture/sovereign-v2-spec` |
| `04 - Decisions/ADR-001.md` | `decisions/adr-001` |
| `Brain/Departments/Engineering/Domains/Safety/Safety.md` | `domains/safety` |
| `Brain/Departments/Engineering/Domains/Safety/Projects/media-service.md` | `projects/safety/media-service` |
| `Brain/Learnings/Domain_Safety/Learnings - Safety.md` | `learnings/domain/safety` |
| `Brain/Learnings/Global/Global Learnings.md` | `learnings/global` |
| `Brain/Learnings/Project_Level/media-service.md` | `learnings/project/media-service` |
| `06 - AI Agent Outputs/2026-05-12-brain-enrichment-271-nodes/session-log.md` | `outputs/2026-05-12-brain-enrichment-271-nodes` |

**Mapping function:**
```python
def path_to_id(rel_path: str) -> str:
    """Convert vault-relative path to deterministic node ID."""
    p = rel_path.removesuffix('.md').lower()
    # Prefix mapping
    rules = [
        ('01 - services/', 'services/'),
        ('02 - domain models/', 'models/'),
        ('03 - architecture/', 'architecture/'),
        ('04 - decisions/', 'decisions/'),
        ('brain/departments/engineering/domains/', 'domains/'),  # further split below
        ('brain/learnings/project_level/', 'learnings/project/'),
        ('brain/learnings/domain_', 'learnings/domain/'),
        ('brain/learnings/global/', 'learnings/global'),
        ('brain/learnings/department_', 'learnings/department/'),
        ('06 - ai agent outputs/', 'outputs/'),
        ('brain/', 'brain/'),
    ]
    for prefix, replacement in rules:
        if p.startswith(prefix):
            p = replacement + p[len(prefix):]
            break
    # Clean up: replace spaces with hyphens, collapse slashes
    return re.sub(r'[^a-z0-9/_-]', '-', p).strip('-/')
```

**Wiki-link resolution:** The parser resolves `[[01 - Services/central-service]]` and `[[central-service]]` (short form) to the same node ID by maintaining an alias map (basename → full path → node ID).

---

## 4. Migration Script: `build-brain-graph.py`

### 4.1 Location & Structure

```
~/.copilot/scripts/
├── brain-graph.py          # Main CLI (the tool agents call)
├── brain_graph/
│   ├── __init__.py
│   ├── builder.py          # Full rebuild + incremental sync
│   ├── parser.py           # Markdown → node + edges extraction
│   ├── bfs.py              # BFS engine with pruning
│   ├── search.py           # FTS5 search wrapper
│   ├── writer.py           # Write-through (graph + vault)
│   ├── models.py           # Dataclasses for Node, Edge
│   └── utils.py            # ID generation, path resolution, hashing
└── brain_graph_test.py     # Minimal smoke tests
```

### 4.2 Parser Logic (`parser.py`)

For each `.md` file, the parser extracts:

1. **YAML frontmatter** (between `---` delimiters) → `metadata` JSON, `tags` list, `title`, `last_synced`
2. **Node type** — inferred from file path prefix (see mapping in §3)
3. **Title** — from frontmatter `title:` field, or first `# Heading`, or filename
4. **Summary** — from `## Service Description` or `## Description` section, or first 500 chars after title
5. **Structured fields** — `tribe`, `squad`, `domain_name` extracted from `## Architecture` block
6. **Wiki-links** — regex `\[\[([^\]|]+)(?:\|[^\]]+)?\]\]` → resolve to target node IDs
7. **Parent Repo** — regex `\*\*Parent Repo:\*\*\s*\[\[([^\]]+)\]\]`
8. **Related frontmatter** — `related:` YAML field → list of entity references
9. **Owning services** — `owning_services:` YAML field → list of service names
10. **Integration Graph** — parse markdown table after `## Integration Graph` heading:
    - Each row: Direction, Type, Target, Flow Description
    - Creates edge with `type=integration`, `metadata={direction, protocol, flow}`
11. **Related Services** — parse `## Related Services` bullet list of `[[...]]` links
12. **Domain service lists** — for domain files, extract service names from bullet lists under `## Services / Repositories`
13. **Project membership** — files under `Domains/X/Projects/` get `has_project` edge to domain

**Edge extraction priority** (more specific types override generic wiki_link):
- If a `[[link]]` appears in `## Related Services` → `related_service` (not `wiki_link`)
- If a `[[link]]` appears in `## Integration Graph` → `integration` (not `wiki_link`)
- If a `[[link]]` appears in `**Parent Repo:**` → `parent_repo` (not `wiki_link`)
- All other `[[links]]` → `wiki_link`

### 4.3 Build Process (Full Rebuild)

```
Input:  ~/eroad-brain/**/*.md (823 files)
Output: ~/.copilot/brain-graph/eroad.db

Steps:
1. Scan vault: find all .md files, read content + mtime
2. Parse each file → Node dataclass + list of raw edges
3. Build alias map: {basename → full_path → node_id} for wiki-link resolution
4. Resolve all edges: convert wiki-link targets to node IDs (log unresolved links)
5. Begin SQLite transaction
6. DROP + CREATE all tables (full rebuild)
7. INSERT all nodes
8. INSERT all edges
9. Rebuild FTS5 index
10. INSERT sync_meta (timestamp, counts)
11. COMMIT
12. Print summary: nodes, edges by type, unresolved links, elapsed time
```

**Expected output:**
```
[brain-graph] Full rebuild of eroad-brain
  Scanned: 823 files in 0.3s
  Parsed:  823 nodes, 4,170 edges in 0.8s
  Resolved: 3,847 edges (323 unresolved — logged)
  Written: eroad.db (2.1 MB) in 0.4s
  FTS5 index: 823 documents
  Total: 1.5s
```

### 4.4 Incremental Sync

```
1. Read sync_meta.last_incremental_sync timestamp
2. Scan vault: find files with mtime > last_sync
3. For each changed file:
   a. Re-parse → new Node + edges
   b. Compare content_hash with stored hash
   c. If changed: UPDATE node, DELETE old edges, INSERT new edges, UPDATE FTS
4. Scan for deleted files: nodes in DB whose path no longer exists on disk
   a. DELETE node + edges + FTS entry
5. Scan for new files: .md files on disk not in DB
   a. Parse + INSERT
6. Update sync_meta.last_incremental_sync
```

Incremental sync is called by `brain-graph sync` and should complete in <500ms for typical changes (1-10 files).

---

## 5. BFS API Surface (`brain-graph.py` CLI)

The main tool agents call. All commands output JSON to stdout for easy parsing by agents.

### 5.1 Command Reference

```bash
# ── BUILD / SYNC ──────────────────────────────────────────────
brain-graph build [--vault PATH]
# Full rebuild. Default vault: ~/eroad-brain
# Output: {"status":"ok","nodes":823,"edges":4170,"elapsed_ms":1500}

brain-graph sync [--vault PATH]
# Incremental sync (changed files only)
# Output: {"status":"ok","added":2,"updated":5,"deleted":0,"elapsed_ms":200}

# ── SEARCH ────────────────────────────────────────────────────
brain-graph search "media-service security" [--limit 10] [--type service]
# FTS5 full-text search. Returns ranked results.
# Output: [{"id":"services/media-service","type":"service","title":"media-service",
#           "rank":-12.5,"summary":"...first 200 chars...","path":"01 - Services/media-service.md"}]

brain-graph search --exact "media-service"
# Exact node lookup by ID substring or title
# Output: same format as above

# ── BFS TRAVERSAL ─────────────────────────────────────────────
brain-graph bfs --seeds "services/media-service,domains/safety" \
                --depth 1 \
                [--prune "services/common-resources,services/integration-test"] \
                [--session "2025-07-15-security-review"] \
                [--edge-types "related_service,integration,domain_has_service"] \
                [--max-nodes 30]
# BFS expansion from seed nodes.
# Returns: layer-by-layer results with summaries for agent triage.
# Output:
# {
#   "session": "2025-07-15-security-review",
#   "seeds": ["services/media-service", "domains/safety"],
#   "pruned": ["services/common-resources"],
#   "layers": [
#     {
#       "depth": 0,
#       "nodes": [
#         {"id": "services/media-service", "type": "service", "title": "media-service",
#          "summary": "Video upload and transcoding...", "neighbor_count": 12,
#          "content_lines": 87}
#       ]
#     },
#     {
#       "depth": 1,
#       "nodes": [
#         {"id": "domains/safety", "type": "domain", "title": "Safety",
#          "summary": "Owns all driver safety products...", "neighbor_count": 15,
#          "edge_from": "services/media-service", "edge_type": "domain_has_service",
#          "content_lines": 42},
#         {"id": "services/dashcam-video-platform", "type": "service",
#          "title": "dashcam-video-platform",
#          "summary": "Core video processing pipeline...", "neighbor_count": 8,
#          "edge_from": "services/media-service", "edge_type": "related_service",
#          "content_lines": 120},
#         ...
#       ]
#     }
#   ],
#   "total_nodes_returned": 14,
#   "elapsed_ms": 35
# }

# ── PRUNE (session-scoped) ────────────────────────────────────
brain-graph prune --session "2025-07-15-security-review" \
                  --nodes "services/integration-test,services/common-resources,learnings/domain/tax"
# Mark nodes as pruned for this session. Future BFS calls with this session ID skip them.
# Output: {"status":"ok","pruned_count":3,"session":"2025-07-15-security-review"}

brain-graph prune --session "2025-07-15-security-review" --list
# List all pruned nodes for session
# Output: {"session":"...","pruned":["services/integration-test",...]}

brain-graph prune --session "2025-07-15-security-review" --clear
# Clear all prune marks (reset session)

# ── READ NODE CONTENT ─────────────────────────────────────────
brain-graph read "services/media-service" [--compress] [--sections "description,integration,api"]
# Fetch full node content from graph (no filesystem read needed)
# --compress: headings + keyword lines only (for large nodes, same as current compression)
# --sections: extract only named sections
# Output: {"id":"services/media-service","type":"service","content":"# media-service\n...","lines":87}

brain-graph read --ids "services/media-service,domains/safety,learnings/domain/safety"
# Batch read multiple nodes
# Output: [{"id":"...","content":"..."},...]

# ── WRITE (for brain-consolidation) ──────────────────────────
brain-graph upsert --path "Brain/Learnings/Domain_Safety/Learnings - Safety.md" \
                   --vault ~/eroad-brain
# Re-read a specific file from vault and update graph node + edges.
# Used after brain-consolidation writes to the vault.
# Output: {"status":"ok","id":"learnings/domain/safety","edges_updated":3}

brain-graph upsert-content --path "Brain/Learnings/Domain_Safety/Learnings - Safety.md" \
                           --content "# Learnings - Safety\n\n## New Entry\n..."
# Write content to BOTH vault file AND graph node atomically.
# This is the preferred write path for brain-consolidation.
# Output: {"status":"ok","id":"learnings/domain/safety","vault_written":true,"graph_written":true}

# ── STATS / DEBUG ─────────────────────────────────────────────
brain-graph stats [--vault eroad]
# Output: {"nodes":823,"edges":4170,"edge_types":{"wiki_link":3400,...},"node_types":{"service":521,...},"db_size_kb":2100,"last_sync":"..."}

brain-graph neighbors "services/media-service" [--edge-type integration]
# List direct neighbors of a node
# Output: [{"id":"...","type":"...","edge_type":"integration","direction":"outbound","label":"syncs to..."}]

brain-graph path "services/media-service" "models/driver" [--max-depth 5]
# Shortest path between two nodes
# Output: {"path":["services/media-service","services/replay-service","models/driver"],"length":2}
```

### 5.2 Agent-Friendly Output Contract

All commands output **valid JSON** to stdout. Errors go to stderr. Exit code 0 = success, 1 = error.

The `--format` flag supports:
- `json` (default) — machine-parseable
- `summary` — compact text for agent prompts (node titles, summaries, counts)
- `full` — includes full content in output (for `read` commands)

### 5.3 Performance Targets

| Operation | Target | Method |
|-----------|--------|--------|
| `search` (FTS5) | <20ms | SQLite FTS5 MATCH query |
| `bfs --depth 1` | <30ms | Load adjacency → NetworkX BFS |
| `bfs --depth 2` | <50ms | Same, 2 layers |
| `read` (single node) | <5ms | SQLite SELECT by PK |
| `read` (batch 10) | <15ms | SQLite SELECT IN(...) |
| `build` (full) | <2s | Sequential parse + bulk INSERT |
| `sync` (incremental) | <500ms | mtime check + partial UPDATE |
| `upsert` (single file) | <100ms | Parse + UPDATE + FTS rebuild |

---

## 6. The BFS "Prune and Expand" Pattern in Practice

### 6.1 Walkthrough: "Work on media-service security"

```
AGENT receives task: "Work on media-service security"

STEP 1: Identify entry nodes
  $ brain-graph search "media-service" --type service --limit 3
  → [{"id": "services/media-service", "rank": -15.2, ...}]
  $ brain-graph search "security" --type architecture --limit 3
  → [{"id": "architecture/sovereign-v2-spec", "rank": -8.1, ...}]
  
  Entry seeds: ["services/media-service"]

STEP 2: BFS Layer 0 (fetch seed content)
  $ brain-graph read "services/media-service"
  → Full content of media-service.md (87 lines)
  
  Agent reads content, understands: video upload service, Safety domain,
  integrates with dashcam-video-platform, replay-service, S3, SQS.

STEP 3: BFS Layer 1 (expand neighbors)
  $ brain-graph bfs --seeds "services/media-service" --depth 1 --session "task-123"
  → Layer 1: 12 neighbors returned with summaries:
    - domains/safety (domain, "Owns all driver safety products...")
    - services/dashcam-video-platform (service, "Core video processing...")
    - services/replay-service (service, "Historical event replay...")
    - services/notification-service (service, "Alert delivery...")
    - services/myeroad-event-service (service, "Event management...")
    - services/common-resources (service, "Shared Java libraries...")
    - services/integration-test (service, "Integration test harness...")
    - learnings/domain/safety (learning, "dashcam pipeline uses S3...")
    - models/event (domain_model, "Safety/compliance incident...")
    - projects/safety/media-service (project, "Media service project...")
    - outputs/2026-04-23-vehiclecontroller-security (ai_output, "Security review...")
    - services/media-service/media-service-core (service, "Core submodule...")

STEP 4: Agent triages Layer 1 (PRUNE irrelevant nodes)
  Agent decides:
  ✅ KEEP: domains/safety, services/dashcam-video-platform, learnings/domain/safety,
           models/event, outputs/2026-04-23-vehiclecontroller-security
  ❌ PRUNE: services/common-resources (shared lib, not security-relevant),
            services/integration-test (test harness),
            services/notification-service (alerting, not security),
            services/myeroad-event-service (event CRUD, not security)
  ⏸ DEFER: services/replay-service (maybe relevant, keep for now)

  $ brain-graph prune --session "task-123" \
      --nodes "services/common-resources,services/integration-test,services/notification-service,services/myeroad-event-service"

STEP 5: Fetch kept Layer 1 content
  $ brain-graph read --ids "domains/safety,services/dashcam-video-platform,learnings/domain/safety,models/event"
  → Full content of 4 nodes (agent reads and processes)

STEP 6: BFS Layer 2 (expand from unpruned Layer 1 nodes)
  $ brain-graph bfs --seeds "services/dashcam-video-platform,domains/safety" \
                    --depth 1 --session "task-123" --max-nodes 20
  → Layer 2: New nodes not yet seen (deduplicated against Layer 0+1 + pruned):
    - services/fleet-decarbonisation-service
    - services/hours-of-service
    - learnings/domain/safety (already fetched — skipped)
    - architecture/sovereign-v2-spec
    - decisions/adr-007-video-pipeline  (if exists)
    ...

STEP 7: Agent triages Layer 2, prunes more, fetches what's needed.

STEP 8: Agent has sufficient context (typically 2-3 layers). Stops expanding.
```

### 6.2 Prune Mechanics

The `session_prune` table stores pruned nodes per session. When `bfs` is called with `--session`, the BFS engine:

1. Loads the NetworkX graph from SQLite adjacency list
2. Loads `session_prune` entries for the session
3. During BFS traversal, skips any node in the prune set
4. Also skips any node already returned in a previous layer (dedup)
5. Returns only *new* nodes at each depth level

**This means:**
- Pruned nodes are never expanded (their neighbors are not visited)
- Previously returned nodes are not duplicated
- The session prune state accumulates across multiple `bfs` calls in the same session
- Clearing the session (`prune --clear`) resets everything

### 6.3 Max Depth Safety

Default max depth: 3. With 823 nodes and average degree ~10, BFS at depth 3 could touch most of the graph. The `--max-nodes` flag (default 50) caps total nodes returned to prevent context explosion.

---

## 7. Obsidian Vault Sync Strategy

### 7.1 Principle: Vault is Source of Truth

```
Obsidian Vault (.md files)  ──is source of truth──►  Graph DB (derived index)
Human edits vault                                     Agents query graph
brain-consolidation writes vault                      brain-graph rebuild/sync
brain-repo-sync updates vault                         brain-graph upsert
```

The graph is **always rebuildable** from the vault. If the DB corrupts, delete it and run `brain-graph build`.

### 7.2 Sync Triggers

| Trigger | Action | Latency |
|---------|--------|---------|
| Pipeline start (`brain-data-retrieval`) | `brain-graph sync` (incremental) | <500ms |
| After `brain-consolidation` writes | `brain-graph upsert --path <changed-files>` | <100ms per file |
| After `brain-repo-sync` (nightly) | `brain-graph build` (full rebuild) | <2s |
| Manual: user edits vault in Obsidian | Next pipeline start picks up changes | Lazy (on next use) |
| Emergency: DB corrupted | `brain-graph build --force` | <2s |

### 7.3 Write-Through Protocol (brain-consolidation)

When brain-consolidation needs to write a learning:

**Current flow (unchanged):**
1. Write markdown content to vault file (e.g., `Brain/Learnings/Domain_Safety/Learnings - Safety.md`)
2. Git commit + push

**New addition:**
3. Call `brain-graph upsert --path "Brain/Learnings/Domain_Safety/Learnings - Safety.md"` to update graph

This is a **2-line addition** to the brain-consolidation agent's instructions. The vault write remains the primary action; the graph upsert is a cache invalidation.

### 7.4 Consistency Guarantee

If the graph and vault diverge (e.g., upsert fails, agent crashes mid-write):
- Next `brain-graph sync` at pipeline start detects mtime mismatch and re-syncs
- Worst case: `brain-graph build` rebuilds from scratch in <2s
- The vault is always correct; the graph is eventually consistent

---

## 8. Updated Agent Protocols

### 8.1 brain-data-retrieval Agent — Updated Protocol

**What changes:**
- Replaces `find` + `grep` with `brain-graph search` and `brain-graph bfs`
- Adds BFS-based context expansion
- Keeps manifest system (deduplication), STM writing, compression

**New retrieval flow:**

```
1. Run incremental sync:
   $ brain-graph sync --vault $BRAIN_PATH
   
2. Identify entry nodes from task keywords:
   $ brain-graph search "<task keywords>" --limit 5
   
3. BFS Layer 0 — read seed nodes:
   $ brain-graph read --ids "<seed1>,<seed2>"
   → Write to STM Brain Data section
   
4. BFS Layer 1 — expand:
   $ brain-graph bfs --seeds "<seeds>" --depth 1 --session "$TASK_SLUG"
   → Review summaries
   → Prune irrelevant: $ brain-graph prune --session "$TASK_SLUG" --nodes "<irrelevant>"
   → Fetch kept nodes: $ brain-graph read --ids "<kept-nodes>" [--compress]
   → Write to STM Brain Data section
   
5. (Optional) BFS Layer 2 if context insufficient:
   $ brain-graph bfs --seeds "<layer1-kept>" --depth 1 --session "$TASK_SLUG" --max-nodes 20
   → Same triage/prune/fetch cycle
   
6. Write negative context:
   $ brain-graph search "<missing-topic>" --limit 1
   → If no results: record in STM Negative Context
   
7. Update manifest:
   $ brain-manifest.sh add ... (for each fetched node)
```

**Tool budget stays at 10 calls** — but each call now returns richer, more targeted results than grep.

### 8.2 brain-consolidation Agent — Updated Protocol

**What changes:**
- After each vault write, calls `brain-graph upsert` to update graph
- Everything else unchanged (STM reading, knowledge extraction, dedup, git push)

**Addition to write step:**

```
After writing to vault file:
  $ brain-graph upsert --path "<relative-path-just-written>" --vault $BRAIN_PATH
```

**That's it.** One additional bash call per file written. The upsert re-parses the file and updates the node + edges in the graph.

### 8.3 brain-repo-sync Agent — Updated Protocol

**What changes:**
- After nightly sync completes, runs `brain-graph build` to rebuild graph from updated vault

**Addition to end of sync:**
```
$ brain-graph build --vault ~/eroad-brain
```

### 8.4 Orchestrator — Updated Protocol

**What changes:**
- Passes `$TASK_SLUG` as session ID to brain-data-retrieval for BFS session scoping
- No other changes — orchestrator doesn't directly query the graph

---

## 9. Code Structure & Implementation

### 9.1 File Layout

```
~/.copilot/scripts/
├── brain-graph                     # Executable entry point (symlink or wrapper)
├── brain_graph/
│   ├── __init__.py                 # Package init, version
│   ├── cli.py                      # argparse CLI, routes to subcommands
│   ├── builder.py                  # build(), sync(), upsert() — vault → DB
│   ├── parser.py                   # parse_file() → (Node, [Edge]) 
│   │                               #   - YAML frontmatter extraction
│   │                               #   - Wiki-link regex extraction
│   │                               #   - Integration Graph table parsing
│   │                               #   - Section extraction (description, tech stack, etc.)
│   ├── resolver.py                 # Wiki-link → node ID resolution
│   │                               #   - Alias map (basename → path → ID)
│   │                               #   - Unresolved link logging
│   ├── bfs.py                      # BFS engine
│   │                               #   - load_graph() → NetworkX DiGraph from SQLite
│   │                               #   - bfs_expand(seeds, depth, prune_set) → layers
│   │                               #   - Session prune management
│   ├── search.py                   # FTS5 search wrapper
│   │                               #   - search(query, limit, type_filter) → ranked results
│   │                               #   - exact_lookup(id_or_title) → node
│   ├── reader.py                   # Node content retrieval
│   │                               #   - read(id) → full content
│   │                               #   - read_batch(ids) → list of content
│   │                               #   - read_compressed(id, keywords) → compressed content
│   │                               #   - read_sections(id, sections) → extracted sections
│   ├── writer.py                   # Write-through to vault + graph
│   │                               #   - upsert_from_vault(path) — re-read file, update DB
│   │                               #   - upsert_content(path, content) — write file + update DB
│   ├── models.py                   # Dataclasses
│   │                               #   - @dataclass Node: id, path, type, title, content, ...
│   │                               #   - @dataclass Edge: source, target, type, label, metadata
│   │                               #   - @dataclass BFSLayer: depth, nodes: list[BFSNode]
│   │                               #   - @dataclass BFSNode: id, type, title, summary, ...
│   ├── schema.py                   # SQL DDL statements, table creation
│   ├── db.py                       # SQLite connection management
│   │                               #   - get_db(vault_name) → sqlite3.Connection
│   │                               #   - DB path: ~/.copilot/brain-graph/{vault}.db
│   │                               #   - WAL mode for concurrent reads
│   │                               #   - PRAGMA optimizations
│   └── utils.py                    # Shared utilities
│                                   #   - path_to_id(), id_to_path()
│                                   #   - content_hash()
│                                   #   - extract_frontmatter()
│                                   #   - compress_content(content, keywords)
└── tests/
    └── test_brain_graph.py         # Smoke tests (parse, build, search, bfs)
```

### 9.2 Entry Point

```python
#!/usr/bin/env python3
"""brain-graph — Graph-backed brain retrieval for AI agents."""
# ~/.copilot/scripts/brain-graph

import sys
sys.path.insert(0, '/Users/johnlin/.copilot/scripts')
from brain_graph.cli import main
main()
```

Make executable: `chmod +x ~/.copilot/scripts/brain-graph`

### 9.3 SQLite Pragmas

```python
def get_db(vault: str = "eroad") -> sqlite3.Connection:
    db_path = os.path.expanduser(f"~/.copilot/brain-graph/{vault}.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")        # concurrent reads
    conn.execute("PRAGMA synchronous=NORMAL")       # fast writes
    conn.execute("PRAGMA cache_size=-8000")          # 8MB cache
    conn.execute("PRAGMA mmap_size=268435456")       # 256MB mmap
    conn.execute("PRAGMA temp_store=MEMORY")         # temp tables in RAM
    conn.row_factory = sqlite3.Row
    return conn
```

### 9.4 NetworkX Graph Loading

```python
def load_graph(conn: sqlite3.Connection) -> nx.DiGraph:
    """Load the full graph into NetworkX for BFS traversal.
    With 823 nodes and ~4000 edges, this takes <50ms."""
    G = nx.DiGraph()
    
    # Load nodes (just IDs and types for BFS — content loaded on demand)
    for row in conn.execute("SELECT id, type, title, summary, line_count FROM nodes"):
        G.add_node(row['id'], type=row['type'], title=row['title'],
                   summary=row['summary'], line_count=row['line_count'])
    
    # Load edges
    for row in conn.execute("SELECT source_id, target_id, type, label FROM edges"):
        G.add_edge(row['source_id'], row['target_id'],
                   type=row['type'], label=row['label'])
    
    return G
```

---

## 10. Implementation Steps (Ordered)

### Phase 1: Foundation (Day 1-2)

| # | Step | Output | Risk |
|---|------|--------|------|
| 1.1 | `pip3 install networkx` | networkx available | LOW — pure Python |
| 1.2 | Create `~/.copilot/brain-graph/` directory | DB location ready | LOW |
| 1.3 | Implement `models.py` — Node, Edge, BFSNode dataclasses | Type definitions | LOW |
| 1.4 | Implement `utils.py` — path_to_id, content_hash, frontmatter extraction | ID generation working | LOW |
| 1.5 | Implement `schema.py` — all CREATE TABLE statements | Schema defined | LOW |
| 1.6 | Implement `db.py` — connection management with pragmas | DB access layer | LOW |

### Phase 2: Parser + Builder (Day 2-3)

| # | Step | Output | Risk |
|---|------|--------|------|
| 2.1 | Implement `parser.py` — parse_file() for all node types | Node+edge extraction | MEDIUM — regex edge cases |
| 2.2 | Implement `resolver.py` — wiki-link resolution with alias map | Link resolution working | MEDIUM — ambiguous short links |
| 2.3 | Implement `builder.py` — build() full rebuild | Full graph in SQLite | LOW |
| 2.4 | Run first build against ~/eroad-brain, validate counts | 823 nodes, ~4000 edges | LOW |
| 2.5 | Implement builder.sync() — incremental | Fast sync working | LOW |
| 2.6 | Implement builder.upsert() — single file update | Write-through ready | LOW |

### Phase 3: Query Layer (Day 3-4)

| # | Step | Output | Risk |
|---|------|--------|------|
| 3.1 | Implement `search.py` — FTS5 search | Text search working | LOW |
| 3.2 | Implement `bfs.py` — BFS with pruning | Graph traversal working | LOW |
| 3.3 | Implement `reader.py` — node content retrieval + compression | Content reads working | LOW |
| 3.4 | Implement `writer.py` — write-through vault+graph | Bidirectional writes | LOW |
| 3.5 | Implement `cli.py` — all subcommands | CLI tool complete | LOW |
| 3.6 | Create executable entry point, test all commands | Tool ready for agents | LOW |

### Phase 4: Agent Integration (Day 4-5)

| # | Step | Output | Risk |
|---|------|--------|------|
| 4.1 | Update `brain-data-retrieval.agent.md` with new protocol | Agent uses graph | MEDIUM — prompt engineering |
| 4.2 | Update `brain-consolidation.agent.md` with upsert step | Write-through active | LOW |
| 4.3 | Update `brain-repo-sync.agent.md` with post-sync rebuild | Nightly rebuild | LOW |
| 4.4 | Update `brain-sync` skill docs (SKILL.md, GUIDE.md, DETAIL.md) | Skill docs current | LOW |
| 4.5 | Test full pipeline: orchestrator → retrieval → specialist → consolidation | End-to-end working | MEDIUM |

### Phase 5: Polish + Fallback (Day 5-6)

| # | Step | Output | Risk |
|---|------|--------|------|
| 5.1 | Write smoke tests (`test_brain_graph.py`) | Tests passing | LOW |
| 5.2 | Add `--fallback-grep` flag to brain-graph search (falls back to filesystem grep if DB missing) | Graceful degradation | LOW |
| 5.3 | Add `brain-graph stats` with health checks | Monitoring ready | LOW |
| 5.4 | Update `~/.copilot/learnings.md` with migration learnings | Knowledge captured | LOW |
| 5.5 | Brain-consolidation run to persist decision in ADR | Decision recorded | LOW |
| 5.6 | Run benchmark: old grep retrieval vs new graph retrieval on 5 sample tasks | Performance validated | LOW |

---

## 11. Rollback Strategy

### 11.1 Zero-Risk Architecture

The migration is **additive and non-destructive**:
- The Obsidian vault is never modified by the migration
- The graph DB is a new file (`~/.copilot/brain-graph/eroad.db`) that didn't exist before
- Agent instruction changes are in `.agent.md` files tracked in git

### 11.2 Rollback Steps

```bash
# Step 1: Revert agent instructions to pre-graph versions
cd ~/copilot-config && git checkout HEAD~1 -- agents/brain-data-retrieval.agent.md
cd ~/copilot-config && git checkout HEAD~1 -- agents/brain-consolidation.agent.md
cd ~/copilot-config && git checkout HEAD~1 -- agents/brain-repo-sync.agent.md

# Step 2: (Optional) Delete graph database
rm -rf ~/.copilot/brain-graph/

# Step 3: (Optional) Uninstall networkx
pip3 uninstall networkx

# Done. Agents fall back to original grep/find retrieval.
```

### 11.3 Gradual Rollout Option

Instead of switching all at once, the `brain-data-retrieval` agent can be updated to:
1. **Try** `brain-graph search` first
2. **Fall back** to `grep`/`find` if the graph DB doesn't exist or the command fails
3. Log which method was used in the STM retrieval log

This allows A/B comparison and safe rollback without any git reverts.

---

## 12. john-brain Support

The same tool supports both brains:

```bash
brain-graph build --vault ~/john-brain    # creates john.db
brain-graph search "AI agents" --vault john
brain-graph bfs --seeds "clusters/ai-agent-ecosystem-design" --vault john
```

**john-brain differences:**
- 54 files (vs 823) — even faster
- Node types: `cluster`, `learning`, `session`, `research` (vs service-heavy eroad)
- Already has `state.db` — the new `john.db` is separate (different schema, different purpose)
- Parser recognizes john-brain's cluster format (ideas with quotes)

---

## 13. Future Enhancements (Out of Scope for V1)

| Enhancement | Value | Effort |
|-------------|-------|--------|
| **Embedding-based similarity search** | Find semantically related nodes even without explicit links | HIGH — needs embedding model |
| **Edge weight learning** | Agents report which edges were useful → increase weight over time | MEDIUM |
| **Graph visualization** | Generate interactive HTML graph for debugging | LOW — NetworkX + D3.js |
| **Cross-brain links** | Connect eroad-brain nodes to john-brain cluster nodes | LOW |
| **Automatic prune learning** | Track which node types agents consistently prune → pre-filter | MEDIUM |
| **Subgraph export** | Export a subgraph as a standalone context document for LLM prompts | LOW |

---

## 14. Success Criteria

| Metric | Current (grep) | Target (graph) | How to Measure |
|--------|----------------|----------------|----------------|
| Retrieval latency (wall clock) | 3-8s (find+grep+read) | <1s (search+bfs+read) | Time brain-data-retrieval agent |
| Relevance (files fetched vs useful) | ~60% (keyword matching) | >85% (graph-guided) | Agent prune rate at Layer 1 |
| Context completeness | Misses related services | Discovers via BFS expansion | Count of "NEED_DATA" signals |
| Tool calls for retrieval | 5-8 per pipeline | 3-5 per pipeline | Count in STM retrieval log |
| Full rebuild time | N/A | <2s | `brain-graph build` timer |
| Incremental sync time | N/A | <500ms | `brain-graph sync` timer |
| Brain-consolidation overhead | 0 (no graph) | <200ms per file written | `brain-graph upsert` timer |
| Fallback safety | N/A | grep still works if DB missing | `--fallback-grep` flag |

---

## 15. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Wiki-link resolution ambiguity (short names) | MEDIUM | LOW | Log unresolved links; fall back to grep for those nodes |
| Agent prompt too long with BFS output | LOW | MEDIUM | `--max-nodes` cap; summary-only mode |
| SQLite FTS5 not available on macOS Python | LOW | HIGH | FTS5 is compiled into macOS SQLite by default since 3.9 |
| NetworkX import too slow | LOW | LOW | At 823 nodes, graph load is <50ms |
| Brain-consolidation forgets to call upsert | MEDIUM | LOW | Next `sync` at pipeline start catches it |
| Graph diverges from vault (stale data) | LOW | MEDIUM | `sync` runs at every pipeline start; `build` rebuilds from scratch |
| Parser fails on edge-case markdown | MEDIUM | LOW | Log parse errors; node still created with raw content |

---

## Appendix A: Wiki-Link Resolution Strategy

The vault uses both full-path and short-form wiki-links:

| Link Form | Example | Resolution |
|-----------|---------|------------|
| Full path | `[[01 - Services/central-service]]` | Direct: `services/central-service` |
| Full path with alias | `[[01 - Services/central-service\|central-service]]` | Direct: `services/central-service` |
| Short name | `[[central-service]]` | Alias lookup: basename → full path → node ID |
| Cross-section | `[[Brain/Departments/Engineering/Engineering\|Engineering]]` | Direct mapping |
| Missing target | `[[nonexistent-service]]` | Log warning; create "phantom" node with type=`unresolved` |

**Alias map** (built during parse phase):
```python
alias_map = {
    "central-service": "services/central-service",
    "media-service": "services/media-service",
    "Driver": "models/driver",
    "Safety": "domains/safety",
    # ... one entry per node (basename → ID)
}
```

**Conflict resolution:** If two nodes share a basename (e.g., `media-service.md` exists in both `01 - Services/` and `Brain/.../Projects/`), prefer the more specific match. If ambiguous, log and create edges to both.

---

## Appendix B: Integration Graph Table Parser

The `## Integration Graph` section uses a markdown table:

```markdown
| Direction | Type | Target | Flow Description |
|-----------|------|--------|-----------------|
| INBOUND | HTTP | Portal / API | Geofence CRUD from the fleet management UI. |
| OUTBOUND | HTTP | `geofence` | Syncs boundary geometry changes. |
```

**Parser:**
1. Detect `## Integration Graph` heading
2. Skip the header row and separator row
3. For each data row, extract: direction, protocol, target service name, flow description
4. Resolve target to node ID via alias map
5. Create edge: `(current_service, target, type="integration", metadata={direction, protocol, flow})`
6. For INBOUND: reverse the edge direction (target → current_service)

---

*End of plan. Ready for CRITIC review.*
