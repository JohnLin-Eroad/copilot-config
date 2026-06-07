#!/usr/bin/env python3
"""
migrate-brain-decay.py — Phase 1 of the Hippo-style decay/confidence/supersedes work.

Additive schema migration for ~/.copilot/brain-graph.db:
  - new table node_memory  (1:1 with managed nodes; opt-in memory state)
  - new table node_access_log  (append-only access trail)
  - supporting indexes

Idempotent. Default = dry-run. Pass --apply to execute.

NOTE: This script does NOT touch the existing `nodes` table — by design, so the
FTS5 triggers (nodes_ai/nodes_au/nodes_ad) never fire on retrieval-time memory
state updates.

Usage:
  ./migrate-brain-decay.py                     # dry-run
  ./migrate-brain-decay.py --apply             # apply
  ./migrate-brain-decay.py --db PATH --apply   # custom DB
  ./migrate-brain-decay.py --rollback          # drop the two new tables
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

DEFAULT_DB = Path.home() / ".copilot" / "brain-graph.db"

# ── DDL ──────────────────────────────────────────────────────────────────────
# Each entry: (object_name, kind, sql). kind ∈ {'table','index'} for introspection.
MIGRATION_OBJECTS: list[tuple[str, str, str]] = [
    (
        "node_memory",
        "table",
        """
        CREATE TABLE IF NOT EXISTS node_memory (
            node_id           TEXT PRIMARY KEY
                              REFERENCES nodes(id) ON UPDATE CASCADE ON DELETE CASCADE,
            strength          REAL    NOT NULL DEFAULT 1.0
                              CHECK (strength BETWEEN 0 AND 1),
            half_life_days    REAL    NOT NULL DEFAULT 7.0
                              CHECK (half_life_days > 0),
            last_retrieved_at TEXT,
            retrieval_count   INTEGER NOT NULL DEFAULT 0,
            confidence        TEXT
                              CHECK (confidence IS NULL OR confidence IN
                                     ('verified','observed','inferred','stale')),
            valence           TEXT    NOT NULL DEFAULT 'neutral'
                              CHECK (valence IN ('neutral','positive','negative')),
            superseded_by     TEXT    REFERENCES nodes(id) ON UPDATE CASCADE,
            superseded_at     TEXT,
            created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ),
    (
        "idx_memory_strength",
        "index",
        "CREATE INDEX IF NOT EXISTS idx_memory_strength ON node_memory(strength)",
    ),
    (
        "idx_memory_last_retrieved",
        "index",
        "CREATE INDEX IF NOT EXISTS idx_memory_last_retrieved "
        "ON node_memory(last_retrieved_at)",
    ),
    (
        "idx_memory_superseded",
        "index",
        "CREATE INDEX IF NOT EXISTS idx_memory_superseded "
        "ON node_memory(superseded_by) WHERE superseded_by IS NOT NULL",
    ),
    (
        "idx_memory_confidence",
        "index",
        "CREATE INDEX IF NOT EXISTS idx_memory_confidence "
        "ON node_memory(confidence) WHERE confidence IS NOT NULL",
    ),
    (
        "node_access_log",
        "table",
        """
        CREATE TABLE IF NOT EXISTS node_access_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id     TEXT    NOT NULL,
            accessed_at TEXT    NOT NULL DEFAULT (datetime('now')),
            source      TEXT    CHECK (source IN ('search','traverse','fetch')),
            query_hash  TEXT
        )
        """,
    ),
    (
        "idx_access_node",
        "index",
        "CREATE INDEX IF NOT EXISTS idx_access_node "
        "ON node_access_log(node_id, accessed_at)",
    ),
    (
        "idx_access_time",
        "index",
        "CREATE INDEX IF NOT EXISTS idx_access_time "
        "ON node_access_log(accessed_at)",
    ),
]

ROLLBACK_OBJECTS = ["node_access_log", "node_memory"]  # drop tables (drops their indexes too)


def existing_objects(con: sqlite3.Connection) -> set[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
    ).fetchall()
    return {r[0] for r in rows}


def fmt_status(label: str, ok: bool) -> str:
    icon = "✓" if ok else "•"
    return f"  {icon} {label}"


def run_migration(con: sqlite3.Connection, apply: bool) -> int:
    existing = existing_objects(con)
    print(f"Existing objects: {len(existing)} found")
    print()

    creates_needed: list[tuple[str, str, str]] = []
    for name, kind, sql in MIGRATION_OBJECTS:
        already = name in existing
        print(fmt_status(f"{kind:5s} {name}  {'(exists)' if already else '(NEW)'}", already))
        if not already:
            creates_needed.append((name, kind, sql))

    print()
    if not creates_needed:
        print("Nothing to do — schema already up to date.")
        return 0

    if not apply:
        print(f"DRY-RUN: would create {len(creates_needed)} object(s). "
              "Re-run with --apply to execute.")
        print()
        print("--- SQL ---")
        for _, _, sql in creates_needed:
            print(sql.strip())
            print()
        return 0

    print(f"Applying {len(creates_needed)} CREATE statement(s)…")
    with con:
        for name, _, sql in creates_needed:
            con.execute(sql)
            print(f"  ✓ created {name}")
    print("Done.")
    return 0


def run_rollback(con: sqlite3.Connection, apply: bool) -> int:
    existing = existing_objects(con)
    drops_needed = [n for n in ROLLBACK_OBJECTS if n in existing]

    if not drops_needed:
        print("Nothing to roll back — none of the decay tables exist.")
        return 0

    print("Will drop:", ", ".join(drops_needed))
    if not apply:
        print("DRY-RUN: re-run with --apply to actually drop.")
        return 0

    with con:
        for name in drops_needed:
            con.execute(f"DROP TABLE IF EXISTS {name}")
            print(f"  ✓ dropped {name}")
    return 0


def verify(con: sqlite3.Connection) -> int:
    print("── Verification ──")
    # 1. Integrity check
    rows = con.execute("PRAGMA integrity_check").fetchall()
    integrity = rows[0][0] if rows else "unknown"
    print(f"  integrity_check: {integrity}")

    # 2. Foreign keys enabled?
    fk = con.execute("PRAGMA foreign_keys").fetchone()[0]
    print(f"  foreign_keys pragma: {fk} (1 = enforced for this connection)")

    # 3. nodes table untouched
    nodes_count = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edges_count = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    print(f"  nodes: {nodes_count}, edges: {edges_count}")

    # 4. New tables present
    for tbl in ("node_memory", "node_access_log"):
        cols = con.execute(f"PRAGMA table_info({tbl})").fetchall()
        if not cols:
            print(f"  ✗ {tbl} MISSING")
            return 1
        print(f"  ✓ {tbl}: {len(cols)} columns")

    # 5. No memory rows yet (per-node opt-in)
    mem = con.execute("SELECT COUNT(*) FROM node_memory").fetchone()[0]
    log = con.execute("SELECT COUNT(*) FROM node_access_log").fetchone()[0]
    print(f"  node_memory rows: {mem}  (expected 0 — opt-in)")
    print(f"  node_access_log rows: {log}  (expected 0)")

    ok = integrity == "ok" and nodes_count > 0
    print()
    print("✓ verification passed" if ok else "✗ verification FAILED")
    return 0 if ok else 1


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"DB path (default: {DEFAULT_DB})")
    p.add_argument("--apply", action="store_true", help="Actually execute (default = dry-run)")
    p.add_argument("--rollback", action="store_true", help="Drop the two new tables")
    p.add_argument("--verify-only", action="store_true", help="Run verification checks only")
    args = p.parse_args(argv)

    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2

    print(f"DB: {args.db}")
    print(f"Mode: {'ROLLBACK' if args.rollback else ('VERIFY' if args.verify_only else 'MIGRATE')}"
          f" {'(APPLY)' if args.apply else '(dry-run)'}")
    print()

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA foreign_keys = ON")  # we declared FKs; ensure they're enforced
    try:
        if args.verify_only:
            return verify(con)
        if args.rollback:
            return run_rollback(con, args.apply)
        rc = run_migration(con, args.apply)
        if args.apply and rc == 0:
            print()
            verify(con)
        return rc
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
