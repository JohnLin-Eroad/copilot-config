-- Brain Graph Schema
-- Derived index of Obsidian brain vaults. Rebuildable from vault files.
-- SQLite with FTS5 + WAL mode for concurrent reads.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- Nodes: one row per .md file in a vault
-- ============================================================
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,              -- vault + '/' + rel_path_without_ext (e.g. 'eroad/01 - Services/media-service')
    vault TEXT NOT NULL,              -- 'eroad' or 'john'
    rel_path TEXT NOT NULL,           -- relative path from vault root, with .md
    basename TEXT NOT NULL,           -- filename without extension (for wiki-link resolution)
    title TEXT,                       -- first H1 or basename
    content TEXT NOT NULL DEFAULT '', -- full markdown content (backs FTS + Tier 2 fallback)
    content_hash TEXT NOT NULL,       -- SHA-256 of file content
    size_bytes INTEGER,
    modified_at TEXT,                 -- ISO 8601 mtime from filesystem
    domain TEXT,                      -- classified from path prefix (service, domain_model, architecture, etc.)
    subdomain TEXT,                   -- extracted sub-domain for Brain/Departments paths
    indexed_at TEXT NOT NULL,         -- ISO 8601 when this node was last synced
    tombstone INTEGER DEFAULT 0       -- 1 = deleted from vault, retained for rename detection
);

-- ============================================================
-- FTS5 full-text search index (replaces grep)
-- ============================================================
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    id, basename, title, content,
    content='nodes',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync with nodes table
CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, id, basename, title, content)
    VALUES (new.rowid, new.id, new.basename, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, id, basename, title, content)
    VALUES ('delete', old.rowid, old.id, old.basename, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, id, basename, title, content)
    VALUES ('delete', old.rowid, old.id, old.basename, old.title, old.content);
    INSERT INTO nodes_fts(rowid, id, basename, title, content)
    VALUES (new.rowid, new.id, new.basename, new.title, new.content);
END;

-- ============================================================
-- Edges: directed relationships between nodes
-- ============================================================
CREATE TABLE IF NOT EXISTS edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'wiki_link',  -- wiki_link | yaml_dep | folder_sibling
    weight REAL DEFAULT 1.0,                       -- wiki_link=1.0, yaml_dep=1.5, folder_sibling=0.3
    PRIMARY KEY (source_id, target_id, edge_type),
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

-- ============================================================
-- Aliases: tracks renames/moves for wiki-link resolution
-- ============================================================
CREATE TABLE IF NOT EXISTS aliases (
    vault TEXT NOT NULL,
    rel_path TEXT NOT NULL,              -- old relative path
    content_hash TEXT,                   -- hash at time of aliasing (for move detection)
    canonical_id TEXT NOT NULL,          -- current node ID
    alias_basename TEXT NOT NULL,        -- old basename (secondary hint)
    created_at TEXT NOT NULL,
    PRIMARY KEY (vault, rel_path),
    FOREIGN KEY (canonical_id) REFERENCES nodes(id)
);

-- ============================================================
-- Sync metadata: key-value store for sync state
-- ============================================================
CREATE TABLE IF NOT EXISTS sync_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ============================================================
-- Sync log: audit trail for sync operations
-- ============================================================
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault TEXT NOT NULL,
    sync_type TEXT NOT NULL,        -- 'incremental' or 'full'
    started_at TEXT NOT NULL,
    completed_at TEXT,
    files_added INTEGER DEFAULT 0,
    files_updated INTEGER DEFAULT 0,
    files_deleted INTEGER DEFAULT 0,
    files_moved INTEGER DEFAULT 0,
    edges_rebuilt INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running'   -- running | completed | failed
);

-- ============================================================
-- Indexes
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_nodes_vault ON nodes(vault);
CREATE INDEX IF NOT EXISTS idx_nodes_basename ON nodes(basename);
CREATE INDEX IF NOT EXISTS idx_nodes_domain ON nodes(domain);
CREATE INDEX IF NOT EXISTS idx_nodes_tombstone ON nodes(tombstone);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_aliases_basename ON aliases(alias_basename);
CREATE INDEX IF NOT EXISTS idx_aliases_canonical ON aliases(canonical_id);
