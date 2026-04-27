#!/usr/bin/env python3
"""
brain-graph-sync.py — Sync Obsidian vault → SQLite graph index.

Modes:
  full        — Rebuild entire DB from vault
  incremental — Sync only changed/new/deleted files
  touched     — Sync only files listed in touched-paths file

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

# Import edge parser (sibling module)
sys.path.insert(0, str(Path(__file__).parent))
from brain_edge_parser import (
    extract_wiki_links,
    resolve_wiki_link,
    extract_yaml_deps,
    compute_folder_siblings,
    EDGE_WEIGHTS,
)

# ---------------------------------------------------------------------------
# Domain classification
# ---------------------------------------------------------------------------

DOMAIN_MAP = {
    "01 - Services": "service",
    "02 - Domain Models": "domain_model",
    "03 - Architecture": "architecture",
    "04 - Decisions": "decision",
    "06 - AI Agent Outputs": "ai_output",
    "Brain/Departments": "department",
    "Brain/Learnings": "learning",
}

_SUBDOMAIN_RE = re.compile(r"Brain/Departments/.+?/Domains/([^/]+)")


def classify_domain(rel_path: str) -> tuple[str, str | None]:
    """Return (domain, subdomain) from relative path."""
    for prefix, domain in DOMAIN_MAP.items():
        if rel_path.startswith(prefix):
            subdomain = None
            m = _SUBDOMAIN_RE.search(rel_path)
            if m:
                subdomain = m.group(1)
            return domain, subdomain
    return "unclassified", None


# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_title(content: str, basename: str) -> str:
    """First H1 heading, or basename."""
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else basename


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Vault walker
# ---------------------------------------------------------------------------

def walk_vault(vault_path: Path) -> list[dict]:
    """Walk vault, return list of file info dicts for all .md files."""
    files = []
    for root, _dirs, filenames in os.walk(vault_path):
        for fn in filenames:
            if not fn.endswith(".md") or fn.endswith(".bak.md") or fn.endswith(".bak"):
                continue
            fp = Path(root) / fn
            rel = str(fp.relative_to(vault_path))
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError) as e:
                print(f"  WARN: skip unreadable {rel}: {e}", file=sys.stderr)
                continue
            bn = fn[:-3]  # strip .md
            files.append({
                "path": fp,
                "rel_path": rel,
                "basename": bn,
                "content": text,
                "content_hash": content_hash(text),
                "size_bytes": len(text.encode("utf-8")),
                "mtime": iso_mtime(fp),
            })
    return files


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

SCHEMA_PATH = Path(__file__).parent / "brain-graph-schema.sql"


def ensure_db(db_path: Path) -> sqlite3.Connection:
    """Open DB, apply schema if tables don't exist."""
    existed = db_path.exists()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    if not existed:
        schema_sql = SCHEMA_PATH.read_text()
        conn.executescript(schema_sql)
        print(f"  Created new database at {db_path}")
    return conn


# ---------------------------------------------------------------------------
# Build basename lookup for edge resolution
# ---------------------------------------------------------------------------

def build_basename_lookup(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Return {basename_lower: [node_id, ...]}."""
    lookup: dict[str, list[str]] = defaultdict(list)
    for row in conn.execute("SELECT id, basename FROM nodes WHERE tombstone = 0"):
        lookup[row[1].lower()].append(row[0])
    return lookup


# ---------------------------------------------------------------------------
# Edge rebuilding
# ---------------------------------------------------------------------------

def rebuild_all_edges(conn: sqlite3.Connection, vault_name: str) -> int:
    """Delete and rebuild ALL edges for vault. Returns edge count."""
    # Clear edges for this vault's nodes
    conn.execute("""
        DELETE FROM edges WHERE source_id IN (
            SELECT id FROM nodes WHERE vault = ? AND tombstone = 0
        )
    """, (vault_name,))

    lookup = build_basename_lookup(conn)

    # Fetch all non-tombstone nodes for this vault
    rows = conn.execute(
        "SELECT id, rel_path, content FROM nodes WHERE vault = ? AND tombstone = 0",
        (vault_name,)
    ).fetchall()

    edge_count = 0
    unresolved_count = 0

    # Build set of valid node IDs for FK safety
    valid_ids = set(r[0] for r in rows)

    # Wiki-link + yaml_dep edges
    for node_id, rel_path, node_content in rows:
        links = extract_wiki_links(node_content)
        seen = set()
        for raw_target, _bn in links:
            resolved = resolve_wiki_link(raw_target, lookup)
            if resolved.startswith("_unresolved/"):
                unresolved_count += 1
                continue
            key = ("wiki_link", resolved)
            if resolved != node_id and key not in seen and resolved in valid_ids:
                seen.add(key)
                conn.execute(
                    "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight) VALUES (?, ?, ?, ?)",
                    (node_id, resolved, "wiki_link", EDGE_WEIGHTS["wiki_link"])
                )
                edge_count += 1

        for dep in extract_yaml_deps(node_content):
            resolved = resolve_wiki_link(dep, lookup)
            if resolved.startswith("_unresolved/"):
                unresolved_count += 1
                continue
            key = ("yaml_dep", resolved)
            if resolved != node_id and key not in seen and resolved in valid_ids:
                seen.add(key)
                conn.execute(
                    "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight) VALUES (?, ?, ?, ?)",
                    (node_id, resolved, "yaml_dep", EDGE_WEIGHTS["yaml_dep"])
                )
                edge_count += 1

    if unresolved_count:
        print(f"  Skipped {unresolved_count} unresolved link targets")

    # Folder sibling edges
    all_nodes = [(r[0], r[1]) for r in rows]
    siblings = compute_folder_siblings(all_nodes, max_dir_size=20)
    for a, b in siblings:
        conn.execute(
            "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight) VALUES (?, ?, ?, ?)",
            (a, b, "folder_sibling", EDGE_WEIGHTS["folder_sibling"])
        )
        conn.execute(
            "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight) VALUES (?, ?, ?, ?)",
            (b, a, "folder_sibling", EDGE_WEIGHTS["folder_sibling"])
        )
        edge_count += 2

    return edge_count


def rebuild_node_edges(conn: sqlite3.Connection, node_id: str, node_content: str) -> int:
    """Rebuild edges for a single node. Returns edge count."""
    conn.execute("DELETE FROM edges WHERE source_id = ?", (node_id,))

    lookup = build_basename_lookup(conn)
    edge_count = 0
    seen = set()

    for raw_target, _bn in extract_wiki_links(node_content):
        resolved = resolve_wiki_link(raw_target, lookup)
        key = ("wiki_link", resolved)
        if resolved != node_id and key not in seen:
            seen.add(key)
            conn.execute(
                "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight) VALUES (?, ?, ?, ?)",
                (node_id, resolved, "wiki_link", EDGE_WEIGHTS["wiki_link"])
            )
            edge_count += 1

    for dep in extract_yaml_deps(node_content):
        resolved = resolve_wiki_link(dep, lookup)
        key = ("yaml_dep", resolved)
        if resolved != node_id and key not in seen:
            seen.add(key)
            conn.execute(
                "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight) VALUES (?, ?, ?, ?)",
                (node_id, resolved, "yaml_dep", EDGE_WEIGHTS["yaml_dep"])
            )
            edge_count += 1

    return edge_count


# ---------------------------------------------------------------------------
# Hub threshold computation
# ---------------------------------------------------------------------------

def compute_hub_threshold(conn: sqlite3.Connection) -> int:
    """98th percentile of in-degree, floor of 10."""
    degrees = [r[0] for r in conn.execute(
        "SELECT COUNT(*) FROM edges GROUP BY target_id ORDER BY COUNT(*)"
    ).fetchall()]
    if not degrees:
        return 10
    idx = int(len(degrees) * 0.98)
    p98 = degrees[min(idx, len(degrees) - 1)]
    return max(p98, 10)


# ---------------------------------------------------------------------------
# Full sync
# ---------------------------------------------------------------------------

def full_sync(conn: sqlite3.Connection, vault_path: Path, vault_name: str) -> dict:
    """Full sync: rebuild all nodes and edges."""
    stats = {"added": 0, "updated": 0, "deleted": 0, "moved": 0, "edges": 0}
    now = iso_now()

    log_id = conn.execute(
        "INSERT INTO sync_log (vault, sync_type, started_at) VALUES (?, 'full', ?)",
        (vault_name, now)
    ).lastrowid

    print(f"  Walking vault {vault_path}...")
    files = walk_vault(vault_path)
    print(f"  Found {len(files)} .md files")

    # Get existing node IDs for this vault
    existing = {r[0]: r[1] for r in conn.execute(
        "SELECT id, content_hash FROM nodes WHERE vault = ?", (vault_name,)
    ).fetchall()}

    seen_ids = set()

    for f in files:
        node_id = f"{vault_name}/{f['rel_path'][:-3]}"  # strip .md
        seen_ids.add(node_id)
        domain, subdomain = classify_domain(f["rel_path"])
        title = extract_title(f["content"], f["basename"])

        if node_id in existing:
            if existing[node_id] != f["content_hash"]:
                stats["updated"] += 1
            # Always upsert to ensure data consistency
        else:
            stats["added"] += 1

        conn.execute("""
            INSERT INTO nodes (id, vault, rel_path, basename, title, content, content_hash,
                             size_bytes, modified_at, domain, subdomain, indexed_at, tombstone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(id) DO UPDATE SET
                rel_path = excluded.rel_path,
                basename = excluded.basename,
                title = excluded.title,
                content = excluded.content,
                content_hash = excluded.content_hash,
                size_bytes = excluded.size_bytes,
                modified_at = excluded.modified_at,
                domain = excluded.domain,
                subdomain = excluded.subdomain,
                indexed_at = excluded.indexed_at,
                tombstone = 0
        """, (node_id, vault_name, f["rel_path"], f["basename"], title,
              f["content"], f["content_hash"], f["size_bytes"], f["mtime"],
              domain, subdomain, now))

    # Tombstone nodes not seen
    for old_id in existing:
        if old_id not in seen_ids:
            conn.execute("UPDATE nodes SET tombstone = 1 WHERE id = ?", (old_id,))
            # Add alias for the tombstoned node
            row = conn.execute("SELECT rel_path, basename, content_hash FROM nodes WHERE id = ?", (old_id,)).fetchone()
            if row:
                conn.execute("""
                    INSERT OR IGNORE INTO aliases (vault, rel_path, content_hash, canonical_id, alias_basename, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (vault_name, row[0], row[2], old_id, row[1], now))
            stats["deleted"] += 1

    conn.commit()

    # Rebuild all edges
    print("  Rebuilding edges...")
    stats["edges"] = rebuild_all_edges(conn, vault_name)
    conn.commit()

    # Compute hub threshold
    hub_threshold = compute_hub_threshold(conn)
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('hub_threshold', ?)",
        (str(hub_threshold),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('last_full_sync', ?)",
        (now,)
    )

    # Update sync log
    conn.execute("""
        UPDATE sync_log SET completed_at = ?, files_added = ?, files_updated = ?,
               files_deleted = ?, files_moved = ?, edges_rebuilt = ?, status = 'completed'
        WHERE id = ?
    """, (iso_now(), stats["added"], stats["updated"], stats["deleted"],
          stats["moved"], stats["edges"], log_id))

    conn.commit()
    conn.execute("ANALYZE")

    return stats


# ---------------------------------------------------------------------------
# Incremental sync
# ---------------------------------------------------------------------------

def incremental_sync(conn: sqlite3.Connection, vault_path: Path, vault_name: str) -> dict:
    """Incremental sync: only changed/new/deleted files."""
    stats = {"added": 0, "updated": 0, "deleted": 0, "moved": 0, "edges": 0}
    now = iso_now()

    log_id = conn.execute(
        "INSERT INTO sync_log (vault, sync_type, started_at) VALUES (?, 'incremental', ?)",
        (vault_name, now)
    ).lastrowid

    files = walk_vault(vault_path)
    file_by_id: dict[str, dict] = {}
    for f in files:
        node_id = f"{vault_name}/{f['rel_path'][:-3]}"
        file_by_id[node_id] = f

    # Get existing nodes
    existing = {}
    for row in conn.execute(
        "SELECT id, content_hash, tombstone FROM nodes WHERE vault = ?", (vault_name,)
    ).fetchall():
        existing[row[0]] = {"hash": row[1], "tombstone": row[2]}

    changes = 0

    # New + updated files
    changed_ids = []
    for node_id, f in file_by_id.items():
        domain, subdomain = classify_domain(f["rel_path"])
        title = extract_title(f["content"], f["basename"])

        if node_id not in existing:
            stats["added"] += 1
            changes += 1
            conn.execute("""
                INSERT INTO nodes (id, vault, rel_path, basename, title, content, content_hash,
                                 size_bytes, modified_at, domain, subdomain, indexed_at, tombstone)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (node_id, vault_name, f["rel_path"], f["basename"], title,
                  f["content"], f["content_hash"], f["size_bytes"], f["mtime"],
                  domain, subdomain, now))
            changed_ids.append(node_id)

        elif existing[node_id]["hash"] != f["content_hash"]:
            stats["updated"] += 1
            changes += 1
            conn.execute("""
                UPDATE nodes SET rel_path = ?, basename = ?, title = ?, content = ?,
                    content_hash = ?, size_bytes = ?, modified_at = ?, domain = ?,
                    subdomain = ?, indexed_at = ?, tombstone = 0
                WHERE id = ?
            """, (f["rel_path"], f["basename"], title, f["content"],
                  f["content_hash"], f["size_bytes"], f["mtime"],
                  domain, subdomain, now, node_id))
            changed_ids.append(node_id)

        elif existing[node_id]["tombstone"]:
            # Was tombstoned but file is back
            conn.execute("UPDATE nodes SET tombstone = 0, indexed_at = ? WHERE id = ?", (now, node_id))

    # Deleted files — check for moves first
    new_hashes = {f["content_hash"]: nid for nid, f in file_by_id.items()}
    for old_id, info in existing.items():
        if old_id not in file_by_id and not info["tombstone"]:
            # Check move detection: same content hash in a new file?
            if info["hash"] in new_hashes:
                new_id = new_hashes[info["hash"]]
                if new_id != old_id:
                    # This is a move/rename
                    old_row = conn.execute(
                        "SELECT rel_path, basename FROM nodes WHERE id = ?", (old_id,)
                    ).fetchone()
                    if old_row:
                        conn.execute("""
                            INSERT OR IGNORE INTO aliases (vault, rel_path, content_hash, canonical_id, alias_basename, created_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (vault_name, old_row[0], info["hash"], new_id, old_row[1], now))
                    conn.execute("UPDATE nodes SET tombstone = 1 WHERE id = ?", (old_id,))
                    stats["moved"] += 1
                    changes += 1
                    continue

            # Truly deleted
            conn.execute("UPDATE nodes SET tombstone = 1 WHERE id = ?", (old_id,))
            old_row = conn.execute(
                "SELECT rel_path, basename, content_hash FROM nodes WHERE id = ?", (old_id,)
            ).fetchone()
            if old_row:
                conn.execute("""
                    INSERT OR IGNORE INTO aliases (vault, rel_path, content_hash, canonical_id, alias_basename, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (vault_name, old_row[0], old_row[2], old_id, old_row[1], now))
            stats["deleted"] += 1
            changes += 1

    conn.commit()

    # Auto-escalate to full sync if ≥20 changes
    if changes >= 20:
        print(f"  {changes} changes detected — escalating to full sync")
        conn.execute("UPDATE sync_log SET status = 'escalated' WHERE id = ?", (log_id,))
        conn.commit()
        return full_sync(conn, vault_path, vault_name)

    # Rebuild edges for changed nodes only
    for node_id in changed_ids:
        row = conn.execute("SELECT content FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row:
            stats["edges"] += rebuild_node_edges(conn, node_id, row[0])

    # Update hub threshold
    hub_threshold = compute_hub_threshold(conn)
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('hub_threshold', ?)",
        (str(hub_threshold),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('last_incremental_sync', ?)",
        (now,)
    )

    conn.execute("""
        UPDATE sync_log SET completed_at = ?, files_added = ?, files_updated = ?,
               files_deleted = ?, files_moved = ?, edges_rebuilt = ?, status = 'completed'
        WHERE id = ?
    """, (iso_now(), stats["added"], stats["updated"], stats["deleted"],
          stats["moved"], stats["edges"], log_id))

    conn.commit()
    return stats


# ---------------------------------------------------------------------------
# Touched-path sync
# ---------------------------------------------------------------------------

TOUCHED_PATH = Path.home() / ".copilot" / "brain-graph-touched.txt"


def touched_sync(conn: sqlite3.Connection, vault_path: Path, vault_name: str) -> dict:
    """Sync only files listed in touched-paths file."""
    stats = {"added": 0, "updated": 0, "deleted": 0, "moved": 0, "edges": 0}

    if not TOUCHED_PATH.exists():
        print("  No touched-paths file found — nothing to sync")
        return stats

    # Atomic read + delete
    paths = [p.strip() for p in TOUCHED_PATH.read_text().splitlines() if p.strip()]
    TOUCHED_PATH.unlink()

    if not paths:
        print("  Touched-paths file was empty")
        return stats

    now = iso_now()
    print(f"  Processing {len(paths)} touched paths...")

    for rel_path in paths:
        fp = vault_path / rel_path
        node_id = f"{vault_name}/{rel_path[:-3]}" if rel_path.endswith(".md") else f"{vault_name}/{rel_path}"

        if fp.exists() and fp.suffix == ".md":
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError) as e:
                print(f"  WARN: skip {rel_path}: {e}", file=sys.stderr)
                continue

            bn = fp.stem
            domain, subdomain = classify_domain(rel_path)
            title = extract_title(text, bn)
            h = content_hash(text)

            existing = conn.execute("SELECT content_hash FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if existing:
                if existing[0] != h:
                    conn.execute("""
                        UPDATE nodes SET rel_path = ?, basename = ?, title = ?, content = ?,
                            content_hash = ?, size_bytes = ?, modified_at = ?, domain = ?,
                            subdomain = ?, indexed_at = ?, tombstone = 0
                        WHERE id = ?
                    """, (rel_path, bn, title, text, h, len(text.encode("utf-8")),
                          iso_mtime(fp), domain, subdomain, now, node_id))
                    stats["updated"] += 1
            else:
                conn.execute("""
                    INSERT INTO nodes (id, vault, rel_path, basename, title, content, content_hash,
                                     size_bytes, modified_at, domain, subdomain, indexed_at, tombstone)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (node_id, vault_name, rel_path, bn, title, text, h,
                      len(text.encode("utf-8")), iso_mtime(fp), domain, subdomain, now))
                stats["added"] += 1

            stats["edges"] += rebuild_node_edges(conn, node_id, text)
        else:
            # File deleted — tombstone
            existing = conn.execute("SELECT id FROM nodes WHERE id = ? AND tombstone = 0", (node_id,)).fetchone()
            if existing:
                conn.execute("UPDATE nodes SET tombstone = 1 WHERE id = ?", (node_id,))
                stats["deleted"] += 1

    conn.commit()
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sync Obsidian vault to SQLite graph index")
    parser.add_argument("--vault-path", required=True, type=Path, help="Path to Obsidian vault")
    parser.add_argument("--vault-name", required=True, help="Vault name (eroad or john)")
    parser.add_argument("--mode", choices=["full", "incremental", "touched"], default="full")
    parser.add_argument("--db-path", type=Path, default=Path.home() / ".copilot" / "brain-graph.db")
    parser.add_argument("--force-full", action="store_true", help="Force full sync regardless of mode")
    args = parser.parse_args()

    if not args.vault_path.is_dir():
        print(f"ERROR: Vault path does not exist: {args.vault_path}", file=sys.stderr)
        sys.exit(1)

    mode = "full" if args.force_full else args.mode
    print(f"Brain Graph Sync — {mode} mode")
    print(f"  Vault: {args.vault_path} ({args.vault_name})")
    print(f"  DB:    {args.db_path}")

    t0 = time.monotonic()
    conn = ensure_db(args.db_path)

    try:
        if mode == "full":
            stats = full_sync(conn, args.vault_path, args.vault_name)
        elif mode == "incremental":
            stats = incremental_sync(conn, args.vault_path, args.vault_name)
        elif mode == "touched":
            stats = touched_sync(conn, args.vault_path, args.vault_name)
        else:
            print(f"Unknown mode: {mode}", file=sys.stderr)
            sys.exit(1)

        elapsed = time.monotonic() - t0
        print(f"\n  Summary:")
        print(f"    Added:   {stats['added']}")
        print(f"    Updated: {stats['updated']}")
        print(f"    Deleted: {stats['deleted']}")
        print(f"    Moved:   {stats['moved']}")
        print(f"    Edges:   {stats['edges']}")
        print(f"    Time:    {elapsed:.2f}s")

        # Print DB stats
        node_count = conn.execute("SELECT COUNT(*) FROM nodes WHERE tombstone = 0").fetchone()[0]
        edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        print(f"\n  Database: {node_count} nodes, {edge_count} edges")

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
