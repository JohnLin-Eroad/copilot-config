#!/usr/bin/env python3
"""
Brain Graph Sync Engine
Indexes Obsidian vault .md files into a SQLite graph database.

Usage:
    python3 brain-graph-sync.py --vault-path ~/eroad-brain --vault-name eroad --mode full
    python3 brain-graph-sync.py --vault-path ~/eroad-brain --vault-name eroad --mode incremental
    python3 brain-graph-sync.py --vault-path ~/eroad-brain --vault-name eroad --mode touched
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Sibling module: edge extraction + wiki-link resolution
sys.path.insert(0, str(Path(__file__).parent))
from brain_edge_parser import (
    extract_wiki_links,
    resolve_wiki_link,
    extract_yaml_deps,
    compute_folder_siblings,
    EDGE_WEIGHTS,
)

# ────────────────────────────────────────────────────────────────────────────
# Domain classification
# ────────────────────────────────────────────────────────────────────────────

DOMAIN_MAP: dict[str, str] = {
    "01 - Services": "service",
    "02 - Domain Models": "domain_model",
    "03 - Architecture": "architecture",
    "04 - Decisions": "decision",
    "06 - AI Agent Outputs": "ai_output",
    "Brain/Departments": "department",
    "Brain/Learnings": "learning",
}

_SUBDOMAIN_RE = re.compile(r"Brain/Departments/.+?/Domains/([^/]+)")

_SCHEMA_PATH = Path(__file__).parent / "brain-graph-schema.sql"
_DEFAULT_DB = Path("~/.copilot/brain-graph.db").expanduser()
_TOUCHED_FILE = Path("~/.copilot/brain-graph-touched.txt").expanduser()


def classify_domain(rel_path: str) -> tuple[str, Optional[str]]:
    """Return (domain, subdomain) from relative vault path."""
    for prefix, domain in DOMAIN_MAP.items():
        if rel_path.startswith(prefix + "/") or rel_path == prefix:
            subdomain: Optional[str] = None
            m = _SUBDOMAIN_RE.search(rel_path)
            if m:
                subdomain = m.group(1)
            return domain, subdomain
    return "unclassified", None


# ────────────────────────────────────────────────────────────────────────────
# File utilities
# ────────────────────────────────────────────────────────────────────────────

def sha256_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def extract_title(content: str, basename: str) -> str:
    """First H1 heading, or basename if none found."""
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else basename


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def folder_of(rel_path: str) -> str:
    """Parent directory component. Root-level files return '.'."""
    return str(Path(rel_path).parent)


# ────────────────────────────────────────────────────────────────────────────
# Database bootstrap
# ────────────────────────────────────────────────────────────────────────────

def open_db(db_path: Path) -> sqlite3.Connection:
    """Open or create the SQLite database, applying schema DDL if new."""
    needs_init = not db_path.exists()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA cache_size = -65536")   # 64 MB
    con.execute("PRAGMA temp_store = MEMORY")
    con.commit()

    if needs_init:
        if not _SCHEMA_PATH.exists():
            sys.exit(f"ERROR: Schema file not found: {_SCHEMA_PATH}")
        con.executescript(_SCHEMA_PATH.read_text())
        con.commit()
        print(f"Initialised database: {db_path}")

    return con


# ────────────────────────────────────────────────────────────────────────────
# Vault walking
# ────────────────────────────────────────────────────────────────────────────

def walk_vault(vault_path: Path) -> list[Path]:
    """Return all .md files in vault, skipping hidden dirs and .bak files."""
    result: list[Path] = []
    for root, dirs, files in os.walk(vault_path):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fname in files:
            if fname.endswith(".md") and not fname.endswith(".bak"):
                result.append(Path(root) / fname)
    return result


def nid(vault_name: str, rel_path: str) -> str:
    """Canonical node ID: vault/path/without/extension"""
    stem = rel_path[:-3] if rel_path.endswith(".md") else rel_path
    return f"{vault_name}/{stem}"


# ────────────────────────────────────────────────────────────────────────────
# Placeholder nodes for unresolved wiki-links
# ────────────────────────────────────────────────────────────────────────────

def ensure_placeholder_nodes(
    con: sqlite3.Connection,
    vault_name: str,
    placeholder_ids: set[str],
    now: str,
) -> None:
    """Insert stub nodes for unresolved wiki-link targets (gap analysis)."""
    for pid in placeholder_ids:
        link_text = pid[len("_unresolved/"):]
        bname = link_text.split("/")[-1]
        con.execute(
            """INSERT OR IGNORE INTO nodes
               (id, vault, rel_path, basename, title, content, content_hash,
                size_bytes, modified_at, domain, subdomain, indexed_at, tombstone)
               VALUES (?,?,?,?,?,'','placeholder',0,?,'unclassified',NULL,?,0)""",
            (pid, vault_name, f"_unresolved/{link_text}.md", bname, link_text, now, now),
        )


# ────────────────────────────────────────────────────────────────────────────
# Edge rebuilding (per-node)
# ────────────────────────────────────────────────────────────────────────────

def rebuild_node_edges(
    con: sqlite3.Connection,
    node_id: str,
    content: str,
    vault_name: str,
    basename_lookup: dict[str, list[str]],
    sibling_ids: list[str],
    now: str,
) -> int:
    """Delete and rebuild all outgoing edges for one node. Returns edge count."""
    con.execute("DELETE FROM edges WHERE source_id=?", (node_id,))

    edges: list[tuple[str, str, str, float]] = []
    seen: set[tuple[str, str]] = set()
    placeholders: set[str] = set()

    # Wiki-link edges
    for raw_target, _bn in extract_wiki_links(content):
        resolved = resolve_wiki_link(raw_target, basename_lookup)
        key = ("wiki_link", resolved)
        if resolved != node_id and key not in seen:
            seen.add(key)
            if resolved.startswith("_unresolved/"):
                placeholders.add(resolved)
            edges.append((node_id, resolved, "wiki_link", EDGE_WEIGHTS["wiki_link"]))

    # YAML dependency edges
    for dep in extract_yaml_deps(content):
        resolved = resolve_wiki_link(dep, basename_lookup)
        key = ("yaml_dep", resolved)
        if resolved != node_id and key not in seen:
            seen.add(key)
            if resolved.startswith("_unresolved/"):
                placeholders.add(resolved)
            edges.append((node_id, resolved, "yaml_dep", EDGE_WEIGHTS["yaml_dep"]))

    # Folder sibling edges
    for sib in sibling_ids:
        if sib != node_id:
            key = ("folder_sibling", sib)
            if key not in seen:
                seen.add(key)
                edges.append((node_id, sib, "folder_sibling", EDGE_WEIGHTS["folder_sibling"]))

    if placeholders:
        ensure_placeholder_nodes(con, vault_name, placeholders, now)

    if edges:
        con.executemany(
            "INSERT OR REPLACE INTO edges (source_id,target_id,edge_type,weight) VALUES (?,?,?,?)",
            edges,
        )

    return len(edges)


# ────────────────────────────────────────────────────────────────────────────
# Bulk edge rebuild (full sync)
# ────────────────────────────────────────────────────────────────────────────

def rebuild_all_edges(
    con: sqlite3.Connection,
    vault_name: str,
    file_records: list[tuple[str, str, str]],   # (node_id, rel_path, content)
    basename_lookup: dict[str, list[str]],
    now: str,
) -> int:
    """Delete and rebuild ALL edges for vault nodes. Returns total edge count."""
    # Clear all edges originating from this vault's live nodes
    con.execute(
        """DELETE FROM edges WHERE source_id IN
           (SELECT id FROM nodes WHERE vault=? AND tombstone=0)""",
        (vault_name,),
    )

    # Build folder → [node_id] map for sibling computation
    folder_map: dict[str, list[str]] = defaultdict(list)
    for node_id, rel_path, _ in file_records:
        folder_map[folder_of(rel_path)].append(node_id)

    total = 0
    # max_dir_size=50 allows larger dirs; very large dirs (e.g. 100+ files) are
    # skipped to avoid O(n²) edge explosion in flat vaults.
    sibling_pairs = compute_folder_siblings(
        [(nid, rp) for nid, rp, _ in file_records], max_dir_size=50
    )
    # Pre-build bidirectional sibling map
    sib_map: dict[str, list[str]] = defaultdict(list)
    for a, b in sibling_pairs:
        sib_map[a].append(b)
        sib_map[b].append(a)

    for node_id, rel_path, content in file_records:
        total += rebuild_node_edges(
            con, node_id, content, vault_name,
            basename_lookup, sib_map.get(node_id, []), now,
        )

    return total


# ────────────────────────────────────────────────────────────────────────────
# Hub threshold computation
# ────────────────────────────────────────────────────────────────────────────

def compute_hub_threshold(con: sqlite3.Connection) -> int:
    """98th percentile of wiki_link in-degree, floor 10."""
    rows = con.execute(
        "SELECT COUNT(*) AS deg FROM edges WHERE edge_type='wiki_link' GROUP BY target_id ORDER BY deg"
    ).fetchall()
    if not rows:
        return 10
    p98_idx = min(int(len(rows) * 0.98), len(rows) - 1)
    return max(10, rows[p98_idx]["deg"])


# ────────────────────────────────────────────────────────────────────────────
# Sync log helpers
# ────────────────────────────────────────────────────────────────────────────

def log_start(con: sqlite3.Connection, vault_name: str, sync_type: str) -> int:
    cur = con.execute(
        "INSERT INTO sync_log (vault,sync_type,started_at,status) VALUES (?,?,?,'running')",
        (vault_name, sync_type, iso_now()),
    )
    con.commit()
    return cur.lastrowid  # type: ignore[return-value]


def log_finish(
    con: sqlite3.Connection,
    log_id: int,
    stats: dict,
    status: str = "completed",
) -> None:
    con.execute(
        """UPDATE sync_log
           SET completed_at=?, status=?,
               files_added=?, files_updated=?, files_deleted=?,
               files_moved=?, edges_rebuilt=?
           WHERE id=?""",
        (
            iso_now(), status,
            stats["added"], stats["updated"], stats["deleted"],
            stats["moved"], stats["edges"],
            log_id,
        ),
    )
    con.commit()


# ────────────────────────────────────────────────────────────────────────────
# Full sync
# ────────────────────────────────────────────────────────────────────────────

def full_sync(con: sqlite3.Connection, vault_path: Path, vault_name: str) -> dict:
    """Rebuild entire DB from vault. Walk all .md files, upsert nodes, rebuild edges."""
    stats = {"added": 0, "updated": 0, "deleted": 0, "moved": 0, "edges": 0}
    now = iso_now()
    log_id = log_start(con, vault_name, "full")

    print(f"  Walking {vault_path} …")
    md_files = walk_vault(vault_path)
    print(f"  {len(md_files)} .md files found")

    # Snapshot existing live node hashes for add/update counting
    existing_hashes: dict[str, str] = {
        row["id"]: row["content_hash"]
        for row in con.execute(
            "SELECT id, content_hash FROM nodes WHERE vault=? AND tombstone=0",
            (vault_name,),
        )
    }

    # ── Pass 1: read files, batch-upsert nodes ────────────────────────────
    print("  Pass 1: upserting nodes …")
    node_batch: list[tuple] = []
    file_records: list[tuple[str, str, str]] = []   # (node_id, rel_path, content)
    seen_ids: set[str] = set()

    for abs_path in md_files:
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            print(f"  WARN: skip unreadable {abs_path}: {exc}", file=sys.stderr)
            continue

        rel_path = str(abs_path.relative_to(vault_path))
        node_id = nid(vault_name, rel_path)
        seen_ids.add(node_id)

        try:
            stat = abs_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            size = stat.st_size
        except OSError as exc:
            print(f"  WARN: stat failed {abs_path}: {exc}", file=sys.stderr)
            continue

        domain, subdomain = classify_domain(rel_path)
        node_batch.append((
            node_id, vault_name, rel_path, abs_path.stem,
            extract_title(content, abs_path.stem),
            content, sha256_content(content), size, mtime,
            domain, subdomain, now,
        ))
        file_records.append((node_id, rel_path, content))

        if node_id in existing_hashes:
            stats["updated"] += 1
        else:
            stats["added"] += 1

    with con:
        con.executemany(
            """INSERT INTO nodes
               (id, vault, rel_path, basename, title, content, content_hash,
                size_bytes, modified_at, domain, subdomain, indexed_at, tombstone)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)
               ON CONFLICT(id) DO UPDATE SET
                   rel_path=excluded.rel_path, basename=excluded.basename,
                   title=excluded.title, content=excluded.content,
                   content_hash=excluded.content_hash, size_bytes=excluded.size_bytes,
                   modified_at=excluded.modified_at, domain=excluded.domain,
                   subdomain=excluded.subdomain, indexed_at=excluded.indexed_at,
                   tombstone=0""",
            node_batch,
        )

    # ── Pass 2: rebuild all edges ─────────────────────────────────────────
    print("  Pass 2: rebuilding edges …")
    basename_lookup: dict[str, list[str]] = defaultdict(list)
    for row in con.execute(
        "SELECT id, basename FROM nodes WHERE vault=? AND tombstone=0", (vault_name,)
    ):
        basename_lookup[row["basename"].lower()].append(row["id"])

    with con:
        stats["edges"] = rebuild_all_edges(con, vault_name, file_records, basename_lookup, now)

    # ── Pass 3: tombstone absent nodes ────────────────────────────────────
    print("  Pass 3: tombstoning deleted nodes …")
    with con:
        for row in con.execute(
            "SELECT id, rel_path, content_hash, basename FROM nodes WHERE vault=? AND tombstone=0",
            (vault_name,),
        ).fetchall():
            if row["id"] not in seen_ids and not row["id"].startswith("_unresolved/"):
                con.execute("UPDATE nodes SET tombstone=1 WHERE id=?", (row["id"],))
                con.execute(
                    """INSERT OR REPLACE INTO aliases
                       (vault, rel_path, content_hash, canonical_id, alias_basename, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (vault_name, row["rel_path"], row["content_hash"],
                     row["id"], row["basename"], now),
                )
                stats["deleted"] += 1

    # ── Metadata ──────────────────────────────────────────────────────────
    threshold = compute_hub_threshold(con)
    with con:
        for k, v in [
            (f"{vault_name}.hub_threshold", str(threshold)),
            (f"{vault_name}.last_full_sync", now),
        ]:
            con.execute("INSERT OR REPLACE INTO sync_meta (key,value) VALUES (?,?)", (k, v))

    log_finish(con, log_id, stats)

    print("  Running VACUUM and ANALYZE …")
    con.execute("VACUUM")
    con.execute("ANALYZE")
    con.commit()

    return stats


# ────────────────────────────────────────────────────────────────────────────
# Incremental sync
# ────────────────────────────────────────────────────────────────────────────

def incremental_sync(con: sqlite3.Connection, vault_path: Path, vault_name: str) -> dict:
    """Sync only changed/new/deleted files. Auto-escalates to full if ≥20 changes."""
    stats = {"added": 0, "updated": 0, "deleted": 0, "moved": 0, "edges": 0}
    now = iso_now()
    log_id = log_start(con, vault_name, "incremental")

    # Load DB state (live nodes only)
    db_state: dict[str, sqlite3.Row] = {
        row["rel_path"]: row
        for row in con.execute(
            """SELECT id, rel_path, content_hash, modified_at, basename, size_bytes
               FROM nodes WHERE vault=? AND tombstone=0""",
            (vault_name,),
        )
    }

    md_files = walk_vault(vault_path)
    disk_paths: set[str] = set()

    # First pass: identify changes using mtime shortcut (avoid reading unchanged files)
    changed_files: list[tuple[Path, str]] = []   # (abs_path, rel_path)
    new_file_hashes: dict[str, tuple[Path, str]] = {}   # hash → (path, rel_path) for new files only

    for abs_path in md_files:
        rel_path = str(abs_path.relative_to(vault_path))
        disk_paths.add(rel_path)

        existing = db_state.get(rel_path)
        if existing is None:
            # Brand-new file: read now for hash-based move detection
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                h = sha256_content(content)
                new_file_hashes[h] = (abs_path, rel_path)
                changed_files.append((abs_path, rel_path))
            except Exception as exc:
                print(f"  WARN: skip unreadable {abs_path}: {exc}", file=sys.stderr)
            continue

        # mtime shortcut: skip if filesystem mtime matches DB
        try:
            mtime = datetime.fromtimestamp(abs_path.stat().st_mtime, timezone.utc).isoformat()
            if mtime == existing["modified_at"]:
                continue
        except OSError:
            pass

        # mtime changed — verify with content hash
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            if sha256_content(content) != existing["content_hash"]:
                changed_files.append((abs_path, rel_path))
        except Exception as exc:
            print(f"  WARN: skip unreadable {abs_path}: {exc}", file=sys.stderr)

    deleted_rels = set(db_state) - disk_paths
    total_changes = len(changed_files) + len(deleted_rels)

    print(f"  {len(changed_files)} changed/new, {len(deleted_rels)} deleted")

    if total_changes >= 20:
        print(f"  ≥20 changes ({total_changes}) — escalating to full sync")
        log_finish(con, log_id, stats, "escalated")
        return full_sync(con, vault_path, vault_name)

    if total_changes == 0:
        print("  No changes detected")
        log_finish(con, log_id, stats)
        return stats

    # ── Move detection ─────────────────────────────────────────────────────
    # Primary: exact content_hash match
    deleted_by_hash: dict[str, str] = {
        db_state[r]["content_hash"]: r
        for r in deleted_rels
        if db_state[r]["content_hash"]
    }

    moves: dict[str, str] = {}   # old_rel → new_rel
    for h, (_, new_rel) in new_file_hashes.items():
        if h in deleted_by_hash:
            moves[deleted_by_hash[h]] = new_rel

    # Secondary: same basename + file size within ±10%
    matched_new_rels = set(moves.values())
    for old_rel in list(deleted_rels - set(moves)):
        old_row = db_state[old_rel]
        old_size = old_row["size_bytes"] or 0
        old_basename = old_row["basename"] or ""
        if not old_basename or old_size == 0:
            continue
        for h, (new_abs, new_rel) in new_file_hashes.items():
            if new_rel in matched_new_rels:
                continue
            if new_abs.stem != old_basename:
                continue
            try:
                new_size = new_abs.stat().st_size
            except OSError:
                continue
            if abs(new_size - old_size) / old_size <= 0.10:
                moves[old_rel] = new_rel
                matched_new_rels.add(new_rel)
                break

    # Apply moves: update node ID + path, add alias, update edge refs
    with con:
        for old_rel, new_rel in moves.items():
            old_row = db_state[old_rel]
            old_nid = old_row["id"]
            new_nid = nid(vault_name, new_rel)
            con.execute(
                "UPDATE nodes SET id=?,rel_path=?,basename=?,indexed_at=?,tombstone=0 WHERE id=?",
                (new_nid, new_rel, Path(new_rel).stem, now, old_nid),
            )
            con.execute("UPDATE edges SET source_id=? WHERE source_id=?", (new_nid, old_nid))
            con.execute("UPDATE edges SET target_id=? WHERE target_id=?", (new_nid, old_nid))
            con.execute(
                """INSERT OR REPLACE INTO aliases
                   (vault, rel_path, content_hash, canonical_id, alias_basename, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (vault_name, old_rel, old_row["content_hash"], new_nid, old_row["basename"], now),
            )
            deleted_rels.discard(old_rel)
            stats["moved"] += 1

    moved_new_rels = set(moves.values())

    # ── Upsert changed/new nodes ───────────────────────────────────────────
    files_to_process: list[tuple[Path, str, str, str]] = []   # path, rel, content, hash

    with con:
        for abs_path, rel_path in changed_files:
            if rel_path in moved_new_rels:
                continue
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                print(f"  WARN: skip unreadable {abs_path}: {exc}", file=sys.stderr)
                continue

            h = sha256_content(content)
            node_id = nid(vault_name, rel_path)
            is_new = db_state.get(rel_path) is None
            domain, subdomain = classify_domain(rel_path)

            try:
                stat = abs_path.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                size = stat.st_size
            except OSError as exc:
                print(f"  WARN: stat failed {abs_path}: {exc}", file=sys.stderr)
                continue

            con.execute(
                """INSERT INTO nodes
                   (id, vault, rel_path, basename, title, content, content_hash,
                    size_bytes, modified_at, domain, subdomain, indexed_at, tombstone)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)
                   ON CONFLICT(id) DO UPDATE SET
                       rel_path=excluded.rel_path, basename=excluded.basename,
                       title=excluded.title, content=excluded.content,
                       content_hash=excluded.content_hash, size_bytes=excluded.size_bytes,
                       modified_at=excluded.modified_at, domain=excluded.domain,
                       subdomain=excluded.subdomain, indexed_at=excluded.indexed_at,
                       tombstone=0""",
                (node_id, vault_name, rel_path, abs_path.stem,
                 extract_title(content, abs_path.stem),
                 content, h, size, mtime, domain, subdomain, now),
            )
            if is_new:
                stats["added"] += 1
            else:
                stats["updated"] += 1

            files_to_process.append((abs_path, rel_path, content, h))

    # Rebuild basename lookup after all upserts (new nodes now in DB)
    basename_lookup: dict[str, list[str]] = defaultdict(list)
    for row in con.execute(
        "SELECT id, basename FROM nodes WHERE vault=? AND tombstone=0", (vault_name,)
    ):
        basename_lookup[row["basename"].lower()].append(row["id"])

    # Build folder-peer map from DB for sibling edges
    folder_map: dict[str, list[str]] = defaultdict(list)
    for row in con.execute(
        "SELECT id, rel_path FROM nodes WHERE vault=? AND tombstone=0", (vault_name,)
    ):
        folder_map[folder_of(row["rel_path"])].append(row["id"])

    # Rebuild edges for changed/new nodes
    with con:
        for abs_path, rel_path, content, _ in files_to_process:
            node_id = nid(vault_name, rel_path)
            siblings = folder_map.get(folder_of(rel_path), [])
            stats["edges"] += rebuild_node_edges(
                con, node_id, content, vault_name, basename_lookup, siblings, now
            )

    # Tombstone truly deleted nodes
    with con:
        for rel_path in deleted_rels:
            row = db_state[rel_path]
            con.execute("UPDATE nodes SET tombstone=1 WHERE id=?", (row["id"],))
            con.execute(
                """INSERT OR REPLACE INTO aliases
                   (vault, rel_path, content_hash, canonical_id, alias_basename, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (vault_name, rel_path, row["content_hash"], row["id"], row["basename"], now),
            )
            stats["deleted"] += 1

    # Update hub threshold
    threshold = compute_hub_threshold(con)
    with con:
        con.execute(
            "INSERT OR REPLACE INTO sync_meta (key,value) VALUES (?,?)",
            (f"{vault_name}.hub_threshold", str(threshold)),
        )

    log_finish(con, log_id, stats)
    con.execute("ANALYZE")
    con.commit()

    return stats


# ────────────────────────────────────────────────────────────────────────────
# Touched-path sync
# ────────────────────────────────────────────────────────────────────────────

def touched_sync(con: sqlite3.Connection, vault_path: Path, vault_name: str) -> dict:
    """Sync only files listed in the touched-paths file (absolute paths, one per line)."""
    stats = {"added": 0, "updated": 0, "deleted": 0, "moved": 0, "edges": 0}

    if not _TOUCHED_FILE.exists():
        print("  No touched-paths file found — nothing to sync")
        return stats

    # Atomic read-then-delete
    try:
        raw = _TOUCHED_FILE.read_text()
        _TOUCHED_FILE.unlink()
    except Exception as exc:
        print(f"  WARN: Cannot process touched file: {exc}", file=sys.stderr)
        return stats

    raw_paths = [p.strip() for p in raw.splitlines() if p.strip()]
    if not raw_paths:
        print("  Touched-paths file was empty")
        return stats

    print(f"  Processing {len(raw_paths)} touched paths …")
    now = iso_now()
    log_id = log_start(con, vault_name, "touched")

    valid_files: list[tuple[Path, str]] = []   # (abs_path, rel_path) for existing .md files

    for path_str in raw_paths:
        abs_path = Path(path_str).expanduser().resolve()
        if abs_path.suffix != ".md":
            continue

        # Paths in the touched file are absolute; derive rel_path from vault root
        try:
            rel_path = str(abs_path.relative_to(vault_path))
        except ValueError:
            print(f"  WARN: {abs_path} is not inside vault {vault_path}", file=sys.stderr)
            continue

        if abs_path.exists():
            valid_files.append((abs_path, rel_path))
        else:
            # File deleted — tombstone it
            existing = con.execute(
                "SELECT id, content_hash, basename FROM nodes WHERE vault=? AND rel_path=? AND tombstone=0",
                (vault_name, rel_path),
            ).fetchone()
            if existing:
                with con:
                    con.execute("UPDATE nodes SET tombstone=1 WHERE id=?", (existing["id"],))
                    con.execute(
                        """INSERT OR REPLACE INTO aliases
                           (vault, rel_path, content_hash, canonical_id, alias_basename, created_at)
                           VALUES (?,?,?,?,?,?)""",
                        (vault_name, rel_path, existing["content_hash"],
                         existing["id"], existing["basename"], now),
                    )
                stats["deleted"] += 1

    # Upsert existing touched files
    with con:
        for abs_path, rel_path in valid_files:
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                print(f"  WARN: skip unreadable {abs_path}: {exc}", file=sys.stderr)
                continue

            h = sha256_content(content)
            node_id = nid(vault_name, rel_path)
            is_new = con.execute(
                "SELECT id FROM nodes WHERE id=?", (node_id,)
            ).fetchone() is None
            domain, subdomain = classify_domain(rel_path)

            try:
                stat = abs_path.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                size = stat.st_size
            except OSError as exc:
                print(f"  WARN: stat failed {abs_path}: {exc}", file=sys.stderr)
                continue

            con.execute(
                """INSERT INTO nodes
                   (id, vault, rel_path, basename, title, content, content_hash,
                    size_bytes, modified_at, domain, subdomain, indexed_at, tombstone)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)
                   ON CONFLICT(id) DO UPDATE SET
                       rel_path=excluded.rel_path, basename=excluded.basename,
                       title=excluded.title, content=excluded.content,
                       content_hash=excluded.content_hash, size_bytes=excluded.size_bytes,
                       modified_at=excluded.modified_at, domain=excluded.domain,
                       subdomain=excluded.subdomain, indexed_at=excluded.indexed_at,
                       tombstone=0""",
                (node_id, vault_name, rel_path, abs_path.stem,
                 extract_title(content, abs_path.stem),
                 content, h, size, mtime, domain, subdomain, now),
            )
            if is_new:
                stats["added"] += 1
            else:
                stats["updated"] += 1

    # Rebuild basename lookup and folder map after all upserts
    basename_lookup: dict[str, list[str]] = defaultdict(list)
    for row in con.execute(
        "SELECT id, basename FROM nodes WHERE vault=? AND tombstone=0", (vault_name,)
    ):
        basename_lookup[row["basename"].lower()].append(row["id"])

    folder_map: dict[str, list[str]] = defaultdict(list)
    for row in con.execute(
        "SELECT id, rel_path FROM nodes WHERE vault=? AND tombstone=0", (vault_name,)
    ):
        folder_map[folder_of(row["rel_path"])].append(row["id"])

    with con:
        for abs_path, rel_path in valid_files:
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            node_id = nid(vault_name, rel_path)
            siblings = folder_map.get(folder_of(rel_path), [])
            stats["edges"] += rebuild_node_edges(
                con, node_id, content, vault_name, basename_lookup, siblings, now
            )

    log_finish(con, log_id, stats)
    con.execute("ANALYZE")
    con.commit()

    return stats


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Brain Graph Sync — indexes Obsidian vaults into SQLite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--vault-path", required=True, type=Path,
                        help="Path to Obsidian vault root")
    parser.add_argument("--vault-name", required=True,
                        help="Short vault identifier (e.g. eroad, john)")
    parser.add_argument("--mode", required=True,
                        choices=["full", "incremental", "touched"],
                        help="Sync mode")
    parser.add_argument("--db-path", type=Path, default=_DEFAULT_DB,
                        help=f"SQLite database path (default: {_DEFAULT_DB})")
    parser.add_argument("--force-full", action="store_true",
                        help="Force full sync regardless of --mode")
    args = parser.parse_args()

    vault_path = args.vault_path.expanduser().resolve()
    if not vault_path.is_dir():
        sys.exit(f"ERROR: Vault path does not exist: {vault_path}")

    db_path = args.db_path.expanduser()
    con = open_db(db_path)

    mode = "full" if args.force_full else args.mode
    print(f"Brain Graph Sync — {mode} mode")
    print(f"  Vault : {vault_path} ({args.vault_name})")
    print(f"  DB    : {db_path}")
    print()

    t0 = time.monotonic()

    try:
        if mode == "full":
            stats = full_sync(con, vault_path, args.vault_name)
        elif mode == "incremental":
            stats = incremental_sync(con, vault_path, args.vault_name)
        elif mode == "touched":
            stats = touched_sync(con, vault_path, args.vault_name)
        else:
            sys.exit(f"Unknown mode: {mode}")
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        import traceback
        print(f"\nFATAL: {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    finally:
        con.close()

    elapsed = time.monotonic() - t0

    node_count = 0
    edge_count = 0
    try:
        tmp = open_db(db_path)
        node_count = tmp.execute(
            "SELECT COUNT(*) FROM nodes WHERE tombstone=0"
        ).fetchone()[0]
        edge_count = tmp.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        tmp.close()
    except Exception:
        pass

    print(
        f"\n  ┌─ Sync summary ──────────────────────────────┐\n"
        f"  │  Added:          {stats['added']:>6}\n"
        f"  │  Updated:        {stats['updated']:>6}\n"
        f"  │  Deleted:        {stats['deleted']:>6}\n"
        f"  │  Moved:          {stats['moved']:>6}\n"
        f"  │  Edges rebuilt:  {stats['edges']:>6}\n"
        f"  │  Time:           {elapsed:>5.1f}s\n"
        f"  ├─────────────────────────────────────────────┤\n"
        f"  │  DB nodes (live): {node_count:>5}\n"
        f"  │  DB edges:        {edge_count:>5}\n"
        f"  └─────────────────────────────────────────────┘"
    )


if __name__ == "__main__":
    main()
