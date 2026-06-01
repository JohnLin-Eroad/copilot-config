#!/usr/bin/env python3
"""brain-graph-admin.py — manage node_memory state.

First place memory rows get CREATED. Works regardless of BRAIN_DECAY_ENABLED
(that flag gates the read path; admin writes must always work).

Subcommands:
  mark-confidence  Set confidence on a node (creates row if missing)
  decide           Mark one node as superseded by another (winner + loser)
  inspect          Show full memory state + recent accesses for a node
  list-stale       List managed nodes with the lowest effective_strength
  mark-fresh       Reset last_retrieved_at to now (manual reinforcement)

All commands print JSON to stdout. Exit codes:
  0  success
  2  user error (validation, missing node, invalid args)
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse the same constants + decay function as the read path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_graph_memory as bgm  # noqa: E402

DB_DEFAULT = str(Path.home() / ".copilot" / "brain-graph.db")

# Default strength applied when CREATING a row via mark-confidence.
# Higher confidence → higher initial strength.
DEFAULT_STRENGTH_BY_LEVEL = {
    "verified": 1.0,
    "observed": 0.7,
    "inferred": 0.4,
    "stale":    bgm.DECAY_FLOOR,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def emit(payload: dict, exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
    sys.exit(exit_code)


def emit_error(msg: str, **extra) -> None:
    emit({"ok": False, "error": msg, **extra}, exit_code=2)


def node_exists(conn: sqlite3.Connection, node_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM nodes WHERE id=? AND tombstone=0", (node_id,)
    ).fetchone()
    return row is not None


def fetch_memory(conn: sqlite3.Connection, node_id: str) -> dict | None:
    row = conn.execute(
        "SELECT node_id, strength, half_life_days, last_retrieved_at, "
        "       retrieval_count, confidence, valence, superseded_by, "
        "       superseded_at, created_at, updated_at "
        "FROM node_memory WHERE node_id=?", (node_id,)
    ).fetchone()
    if not row:
        return None
    return {
        "node_id":           row[0],
        "strength":          row[1],
        "half_life_days":    row[2],
        "last_retrieved_at": row[3],
        "retrieval_count":   row[4],
        "confidence":        row[5],
        "valence":           row[6],
        "superseded_by":     row[7],
        "superseded_at":     row[8],
        "created_at":        row[9],
        "updated_at":        row[10],
    }


def fetch_node(conn: sqlite3.Connection, node_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, vault, rel_path, basename, title, domain, subdomain, tombstone "
        "FROM nodes WHERE id=?", (node_id,)
    ).fetchone()
    if not row:
        return None
    return {
        "id":        row[0],
        "vault":     row[1],
        "rel_path":  row[2],
        "basename":  row[3],
        "title":     row[4],
        "domain":    row[5],
        "subdomain": row[6],
        "tombstone": bool(row[7]),
    }


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_mark_confidence(args, conn: sqlite3.Connection) -> None:
    if not node_exists(conn, args.node_id):
        emit_error(f"node not found: {args.node_id}", node_id=args.node_id)

    existing = fetch_memory(conn, args.node_id)
    created = existing is None

    if created:
        # Establish a fresh row with sensible defaults.
        strength = args.strength if args.strength is not None \
            else DEFAULT_STRENGTH_BY_LEVEL[args.level]
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, "
            " confidence, valence, last_retrieved_at) "
            "VALUES (?, ?, ?, ?, 'neutral', datetime('now'))",
            (args.node_id, strength, bgm.DEFAULT_HALF_LIFE, args.level),
        )
    else:
        # Update confidence only; preserve strength / count / half-life
        # unless --strength was explicitly given.
        if args.strength is not None:
            conn.execute(
                "UPDATE node_memory SET confidence=?, strength=?, "
                "updated_at=datetime('now') WHERE node_id=?",
                (args.level, args.strength, args.node_id),
            )
        else:
            conn.execute(
                "UPDATE node_memory SET confidence=?, updated_at=datetime('now') "
                "WHERE node_id=?",
                (args.level, args.node_id),
            )
    conn.commit()
    emit({
        "ok": True,
        "created": created,
        "node_id": args.node_id,
        "level": args.level,
        "memory": fetch_memory(conn, args.node_id),
    })


def _upsert_min(conn: sqlite3.Connection, node_id: str) -> None:
    """Create a minimal node_memory row if none exists (no-op if exists)."""
    conn.execute(
        "INSERT OR IGNORE INTO node_memory "
        "(node_id, strength, half_life_days, valence) "
        "VALUES (?, 1.0, ?, 'neutral')",
        (node_id, bgm.DEFAULT_HALF_LIFE),
    )


def cmd_decide(args, conn: sqlite3.Connection) -> None:
    winner = args.winner
    loser = args.supersedes
    if winner == loser:
        emit_error("winner cannot supersede itself (same node id)",
                   winner=winner, loser=loser)
    if not node_exists(conn, winner):
        emit_error(f"winner not found: {winner}", node_id=winner)
    if not node_exists(conn, loser):
        emit_error(f"loser not found: {loser}", node_id=loser)

    # Ensure both have rows
    _upsert_min(conn, winner)
    _upsert_min(conn, loser)

    # Winner becomes verified
    conn.execute(
        "UPDATE node_memory SET confidence='verified', "
        "updated_at=datetime('now') WHERE node_id=?", (winner,))

    # Loser gets superseded link
    conn.execute(
        "UPDATE node_memory SET superseded_by=?, "
        "superseded_at=datetime('now'), updated_at=datetime('now') "
        "WHERE node_id=?", (winner, loser))

    if args.note:
        # Stash note in valence column? No — use a comment in updated_at log.
        # We don't have a free-text column; for now, just record via access_log
        # source='admin:decide' (best-effort, swallow errors).
        try:
            conn.execute(
                "INSERT INTO node_access_log (node_id, accessed_at, source, query_hash) "
                "VALUES (?, datetime('now'), 'search', ?)",
                (loser, ("note:" + args.note)[:32]),
            )
        except sqlite3.Error:
            pass

    conn.commit()
    emit({
        "ok": True,
        "winner": fetch_memory(conn, winner),
        "loser": fetch_memory(conn, loser),
    })


def cmd_inspect(args, conn: sqlite3.Connection) -> None:
    node = fetch_node(conn, args.node_id)
    if not node:
        emit_error(f"node not found: {args.node_id}", node_id=args.node_id)

    mem = fetch_memory(conn, args.node_id)
    if mem:
        eff = bgm.effective_strength(
            mem["strength"], mem["half_life_days"], mem["last_retrieved_at"],
        )
        mem["effective_strength"] = round(eff, 4)
        mem["is_superseded"] = mem["superseded_by"] is not None

    recent = conn.execute(
        "SELECT accessed_at, source, query_hash FROM node_access_log "
        "WHERE node_id=? ORDER BY accessed_at DESC LIMIT ?",
        (args.node_id, args.access_limit),
    ).fetchall()
    recent_list = [
        {"accessed_at": r[0], "source": r[1], "query_hash": r[2]} for r in recent
    ]

    emit({
        "ok": True,
        "node": node,
        "memory": mem,
        "recent_accesses": recent_list,
    })


def cmd_list_stale(args, conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT nm.node_id, nm.strength, nm.half_life_days, nm.last_retrieved_at, "
        "       nm.retrieval_count, nm.confidence, nm.superseded_by, n.title "
        "FROM node_memory nm "
        "LEFT JOIN nodes n ON n.id = nm.node_id "
        "WHERE n.tombstone = 0 OR n.tombstone IS NULL"
    ).fetchall()

    enriched = []
    for r in rows:
        eff = bgm.effective_strength(r[1], r[2], r[3])
        enriched.append({
            "node_id":           r[0],
            "strength":          r[1],
            "half_life_days":    r[2],
            "last_retrieved_at": r[3],
            "retrieval_count":   r[4],
            "confidence":        r[5],
            "superseded_by":     r[6],
            "title":             r[7],
            "effective_strength": round(eff, 4),
        })
    enriched.sort(key=lambda x: x["effective_strength"])
    emit({
        "ok": True,
        "total_managed": len(enriched),
        "results": enriched[: args.limit],
    })


def cmd_mark_fresh(args, conn: sqlite3.Connection) -> None:
    """Reset last_retrieved_at to now (manual reinforcement). Creates row if missing."""
    if not node_exists(conn, args.node_id):
        emit_error(f"node not found: {args.node_id}", node_id=args.node_id)
    existing = fetch_memory(conn, args.node_id)
    if existing is None:
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, "
            " confidence, valence, last_retrieved_at) "
            "VALUES (?, 1.0, ?, 'observed', 'neutral', datetime('now'))",
            (args.node_id, bgm.DEFAULT_HALF_LIFE),
        )
        created = True
    else:
        conn.execute(
            "UPDATE node_memory SET strength=1.0, last_retrieved_at=datetime('now'), "
            "updated_at=datetime('now') WHERE node_id=?", (args.node_id,))
        created = False
    conn.commit()
    emit({"ok": True, "created": created, "memory": fetch_memory(conn, args.node_id)})


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Brain graph memory admin")
    p.add_argument("--db-path", default=DB_DEFAULT)
    sub = p.add_subparsers(dest="command", required=True)

    mc = sub.add_parser("mark-confidence",
                        help="Set confidence on a node (creates row if missing)")
    mc.add_argument("--node-id", required=True)
    mc.add_argument("--level", required=True,
                    choices=["verified", "observed", "inferred", "stale"])
    mc.add_argument("--strength", type=float, default=None,
                    help="Override default strength for the chosen level")

    dc = sub.add_parser("decide",
                        help="Mark one node as superseded by another")
    dc.add_argument("--winner", required=True, help="Node that wins (becomes verified)")
    dc.add_argument("--supersedes", required=True, dest="supersedes",
                    help="Node that loses (gets superseded_by=winner)")
    dc.add_argument("--note", default=None, help="Optional decision rationale")

    ins = sub.add_parser("inspect", help="Show node + memory + recent accesses")
    ins.add_argument("--node-id", required=True)
    ins.add_argument("--access-limit", type=int, default=10)

    ls = sub.add_parser("list-stale",
                        help="List managed nodes with lowest effective_strength")
    ls.add_argument("--limit", type=int, default=20)

    mf = sub.add_parser("mark-fresh",
                        help="Reset last_retrieved_at to now (manual reinforcement)")
    mf.add_argument("--node-id", required=True)

    return p


def main() -> int:
    args = build_parser().parse_args()
    conn = sqlite3.connect(args.db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        dispatch = {
            "mark-confidence": cmd_mark_confidence,
            "decide":          cmd_decide,
            "inspect":         cmd_inspect,
            "list-stale":      cmd_list_stale,
            "mark-fresh":      cmd_mark_fresh,
        }
        dispatch[args.command](args, conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
