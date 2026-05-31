#!/usr/bin/env python3
"""brain-sleep.py — scheduled background decay/cleanup for the brain graph.

Runs periodically (cron / launchd). Two housekeeping jobs:

  mark-stale            Flip confidence='stale' for managed rows whose
                        effective_strength has fallen below --threshold.
                        Preserves all other columns. Idempotent.

  prune-access-log      Delete node_access_log entries older than
                        --older-than-days.

  run-all               Convenience wrapper that performs both with
                        sensible defaults.

All commands emit a JSON summary and support --dry-run.

Works regardless of BRAIN_DECAY_ENABLED — housekeeping is always safe.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_graph_memory as bgm  # noqa: E402

DB_DEFAULT = str(Path.home() / ".copilot" / "brain-graph.db")

# Conservative defaults
DEFAULT_STALE_THRESHOLD = 0.10
DEFAULT_ACCESS_LOG_KEEP_DAYS = 90


# ---------------------------------------------------------------------------
# Jobs (each returns a dict summary)
# ---------------------------------------------------------------------------

def job_mark_stale(conn: sqlite3.Connection, *, threshold: float,
                   dry_run: bool) -> dict:
    """Flip confidence='stale' for rows whose effective_strength <= threshold.

    Skips rows that are already 'stale' (idempotent).
    Preserves strength, half_life_days, retrieval_count.
    """
    rows = conn.execute(
        "SELECT node_id, strength, half_life_days, last_retrieved_at, "
        "       confidence "
        "FROM node_memory "
        "WHERE confidence IS NULL OR confidence != 'stale'"
    ).fetchall()

    candidates = []
    for nid, strength, hl, last, conf in rows:
        eff = bgm.effective_strength(strength, hl, last)
        if eff <= threshold:
            candidates.append((nid, round(eff, 4), conf))

    summary = {
        "ok": True,
        "job": "mark-stale",
        "threshold": threshold,
        "scanned": len(rows),
        "dry_run": dry_run,
    }
    if dry_run:
        summary["would_mark_stale"] = len(candidates)
        summary["sample"] = [
            {"node_id": n, "effective_strength": e, "previous_confidence": c}
            for n, e, c in candidates[:10]
        ]
        return summary

    marked = 0
    for nid, _, _ in candidates:
        cur = conn.execute(
            "UPDATE node_memory SET confidence='stale', "
            "updated_at=datetime('now') WHERE node_id=?", (nid,))
        marked += cur.rowcount
    conn.commit()
    summary["marked_stale"] = marked
    return summary


def job_prune_access_log(conn: sqlite3.Connection, *, older_than_days: int,
                         dry_run: bool) -> dict:
    cutoff_expr = f"datetime('now', '-{int(older_than_days)} days')"
    count = conn.execute(
        f"SELECT COUNT(*) FROM node_access_log WHERE accessed_at < {cutoff_expr}"
    ).fetchone()[0]

    summary = {
        "ok": True,
        "job": "prune-access-log",
        "older_than_days": older_than_days,
        "dry_run": dry_run,
    }
    if dry_run:
        summary["would_delete"] = count
        return summary

    conn.execute(f"DELETE FROM node_access_log WHERE accessed_at < {cutoff_expr}")
    conn.commit()
    summary["deleted"] = count
    return summary


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_mark_stale(args, conn):
    out = job_mark_stale(conn, threshold=args.threshold, dry_run=args.dry_run)
    print(json.dumps(out, indent=2, sort_keys=True))


def cmd_prune_access_log(args, conn):
    out = job_prune_access_log(
        conn, older_than_days=args.older_than_days, dry_run=args.dry_run)
    print(json.dumps(out, indent=2, sort_keys=True))


def cmd_run_all(args, conn):
    out = {
        "ok": True,
        "job": "run-all",
        "dry_run": args.dry_run,
        "mark_stale": job_mark_stale(
            conn, threshold=args.stale_threshold, dry_run=args.dry_run),
        "prune_access_log": job_prune_access_log(
            conn, older_than_days=args.access_log_keep_days,
            dry_run=args.dry_run),
    }
    print(json.dumps(out, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Brain graph background housekeeping")
    p.add_argument("--db-path", default=DB_DEFAULT)
    sub = p.add_subparsers(dest="command", required=True)

    ms = sub.add_parser("mark-stale",
                        help="Flip confidence='stale' for low-eff-strength rows")
    ms.add_argument("--threshold", type=float, default=DEFAULT_STALE_THRESHOLD,
                    help=f"Effective strength threshold (default {DEFAULT_STALE_THRESHOLD})")
    ms.add_argument("--dry-run", action="store_true")

    pal = sub.add_parser("prune-access-log",
                         help="Delete node_access_log entries older than N days")
    pal.add_argument("--older-than-days", type=int,
                     default=DEFAULT_ACCESS_LOG_KEEP_DAYS)
    pal.add_argument("--dry-run", action="store_true")

    ra = sub.add_parser("run-all", help="mark-stale + prune-access-log")
    ra.add_argument("--stale-threshold", type=float,
                    default=DEFAULT_STALE_THRESHOLD)
    ra.add_argument("--access-log-keep-days", type=int,
                    default=DEFAULT_ACCESS_LOG_KEEP_DAYS)
    ra.add_argument("--dry-run", action="store_true")

    return p


def main() -> int:
    args = build_parser().parse_args()
    conn = sqlite3.connect(args.db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        dispatch = {
            "mark-stale":       cmd_mark_stale,
            "prune-access-log": cmd_prune_access_log,
            "run-all":          cmd_run_all,
        }
        dispatch[args.command](args, conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
