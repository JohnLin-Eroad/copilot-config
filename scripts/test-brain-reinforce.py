#!/usr/bin/env python3
"""Tests for Phase 3 reinforcement-on-retrieval."""
from __future__ import annotations
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".copilot" / "scripts"))
import brain_graph_memory as bgm

DB = Path.home() / ".copilot" / "brain-graph.db"
TA = "__test__/reinforce-a"
TB = "__test__/reinforce-b"
TC = "__test__/reinforce-c"

results: list[tuple[str, bool, str]] = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail else ""))


def approx(a, b, eps=1e-3):
    return abs(a - b) < eps


def _setup(conn):
    for nid in (TA, TB, TC):
        conn.execute(
            "INSERT OR REPLACE INTO nodes "
            "(id, vault, rel_path, basename, title, content, content_hash, "
            "modified_at, indexed_at) "
            "VALUES (?, 'john-brain', ?, ?, ?, '', 'beef', "
            "datetime('now'), datetime('now'))",
            (nid, f"{nid}.md", f"{nid.rsplit('/', 1)[1]}.md", nid),
        )
    conn.commit()


def _cleanup(conn):
    for nid in (TA, TB, TC):
        conn.execute("DELETE FROM node_access_log WHERE node_id=?", (nid,))
        conn.execute("DELETE FROM node_memory WHERE node_id=?", (nid,))
        conn.execute("DELETE FROM nodes WHERE id=?", (nid,))
    conn.commit()


def _get_mem(conn, nid):
    row = conn.execute(
        "SELECT strength, half_life_days, last_retrieved_at, retrieval_count "
        "FROM node_memory WHERE node_id=?", (nid,)
    ).fetchone()
    return row


def test_unmanaged_not_created():
    print("\nUnmanaged nodes are NOT auto-created by reinforce")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup(conn); _setup(conn)
        bgm.reinforce(conn, [TA, TB], source="search")
        check("no row created for TA", _get_mem(conn, TA) is None)
        check("no row created for TB", _get_mem(conn, TB) is None)
    finally:
        _cleanup(conn); conn.close()


def test_search_bump():
    print("\nsearch bump = 0.05, half-life × 1.05")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup(conn); _setup(conn)
        # Existing row: strength 0.50, half_life 7.0, never retrieved
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days) "
            "VALUES (?, 0.50, 7.0)", (TA,))
        conn.commit()
        bgm.reinforce(conn, [TA], source="search")
        row = _get_mem(conn, TA)
        check("strength 0.50 + 0.05 = 0.55", approx(row[0], 0.55), f"got {row[0]}")
        check("half_life 7.0 × 1.05 = 7.35", approx(row[1], 7.35), f"got {row[1]}")
        check("last_retrieved_at populated", row[2] is not None)
        check("retrieval_count = 1", row[3] == 1, f"got {row[3]}")
    finally:
        _cleanup(conn); conn.close()


def test_fetch_bump():
    print("\nfetch bump = 0.20")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup(conn); _setup(conn)
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days) "
            "VALUES (?, 0.30, 7.0)", (TA,))
        conn.commit()
        bgm.reinforce(conn, [TA], source="fetch")
        row = _get_mem(conn, TA)
        check("strength 0.30 + 0.20 = 0.50", approx(row[0], 0.50), f"got {row[0]}")
    finally:
        _cleanup(conn); conn.close()


def test_strength_cap():
    print("\nstrength caps at 1.0")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup(conn); _setup(conn)
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days) "
            "VALUES (?, 0.95, 7.0)", (TA,))
        conn.commit()
        bgm.reinforce(conn, [TA], source="fetch")
        row = _get_mem(conn, TA)
        check("strength 0.95 + 0.20 → capped 1.0", approx(row[0], 1.0), f"got {row[0]}")
    finally:
        _cleanup(conn); conn.close()


def test_half_life_cap():
    print("\nhalf_life caps at MAX_HALF_LIFE (180)")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup(conn); _setup(conn)
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days) "
            "VALUES (?, 0.5, 175.0)", (TA,))
        conn.commit()
        bgm.reinforce(conn, [TA], source="search")
        row = _get_mem(conn, TA)
        # 175 * 1.05 = 183.75 → capped 180
        check("half_life 175 × 1.05 → capped 180.0",
              approx(row[1], 180.0), f"got {row[1]}")
    finally:
        _cleanup(conn); conn.close()


def test_uses_decayed_base():
    print("\nreinforcement uses CURRENT DECAYED strength, not raw")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup(conn); _setup(conn)
        # Stale: strength 1.0, last 365 days ago → effective ≈ DECAY_FLOOR 0.05
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, last_retrieved_at) "
            "VALUES (?, 1.0, 7.0, datetime('now', '-365 days'))",
            (TA,))
        conn.commit()
        bgm.reinforce(conn, [TA], source="fetch")
        row = _get_mem(conn, TA)
        # Should be DECAY_FLOOR (0.05) + 0.20 = 0.25 — NOT 1.0
        check("stale node: decayed (0.05) + 0.20 = 0.25",
              approx(row[0], 0.25), f"got {row[0]}")
    finally:
        _cleanup(conn); conn.close()


def test_retrieval_count_increments():
    print("\nretrieval_count increments per reinforcement")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup(conn); _setup(conn)
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, retrieval_count) "
            "VALUES (?, 0.5, 7.0, 5)", (TA,))
        conn.commit()
        bgm.reinforce(conn, [TA], source="search")
        bgm.reinforce(conn, [TA], source="search")
        bgm.reinforce(conn, [TA], source="fetch")
        row = _get_mem(conn, TA)
        check("retrieval_count 5 + 3 = 8", row[3] == 8, f"got {row[3]}")
    finally:
        _cleanup(conn); conn.close()


def test_flag_off_no_reinforce():
    print("\nflag OFF: reinforce is a no-op")
    os.environ[bgm.FEATURE_FLAG_ENV] = "0"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup(conn); _setup(conn)
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days) "
            "VALUES (?, 0.50, 7.0)", (TA,))
        conn.commit()
        bgm.reinforce(conn, [TA], source="search")
        row = _get_mem(conn, TA)
        check("strength unchanged", approx(row[0], 0.50), f"got {row[0]}")
        check("retrieval_count unchanged", row[3] == 0, f"got {row[3]}")
    finally:
        _cleanup(conn); conn.close()


def test_apply_memory_reinforces():
    print("\napply_memory triggers reinforcement (integration)")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup(conn); _setup(conn)
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days) "
            "VALUES (?, 0.50, 7.0)", (TA,))
        conn.commit()
        hits = [
            {"id": TA, "bm25_score": 10.0, "combined_score": 10.0,
             "graph_bonus": 0.0, "source": "fts"},
            {"id": TB, "bm25_score": 5.0, "combined_score": 5.0,
             "graph_bonus": 0.0, "source": "fts"},
        ]
        bgm.apply_memory(conn, hits, source="search", query_hash="q1")
        row_a = _get_mem(conn, TA)
        row_b = _get_mem(conn, TB)
        check("managed TA reinforced", approx(row_a[0], 0.55), f"got {row_a[0]}")
        check("unmanaged TB NOT created", row_b is None)
        check("retrieval_count = 1", row_a[3] == 1, f"got {row_a[3]}")
    finally:
        _cleanup(conn); conn.close()


def main():
    if not DB.exists():
        print(f"DB not found: {DB}", file=sys.stderr)
        return 1
    test_unmanaged_not_created()
    test_search_bump()
    test_fetch_bump()
    test_strength_cap()
    test_half_life_cap()
    test_uses_decayed_base()
    test_retrieval_count_increments()
    test_flag_off_no_reinforce()
    test_apply_memory_reinforces()
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*48}\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
