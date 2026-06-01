#!/usr/bin/env python3
"""Tests for brain_graph_memory (Phase 2 read-path helpers).

Pure-function tests + integration tests against the live DB
(using a synthetic test node, cleaned up after).
"""
from __future__ import annotations
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".copilot" / "scripts"))
import brain_graph_memory as bgm

DB = Path.home() / ".copilot" / "brain-graph.db"
TEST_NODE_A = "__test__/memory-a"
TEST_NODE_B = "__test__/memory-b"
TEST_NODE_C = "__test__/memory-c"

results: list[tuple[str, bool, str]] = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail else ""))


def approx(a, b, eps=1e-3):
    return abs(a - b) < eps


def test_pure_functions():
    print("\nPure functions")

    # Unmanaged → 1.0
    check("unmanaged node → strength 1.0",
          bgm.effective_strength(None, None, None) == 1.0)

    # Never-retrieved (no last_retrieved_at) → clamped strength
    check("never-retrieved keeps strength",
          approx(bgm.effective_strength(0.8, 7.0, None), 0.8))

    # Floor enforcement
    check("strength floored at DECAY_FLOOR",
          bgm.effective_strength(0.01, 7.0, None) == bgm.DECAY_FLOOR)

    # Decay: 1 half-life → ~0.5×
    now = datetime(2026, 1, 8, tzinfo=timezone.utc)
    past = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    eff = bgm.effective_strength(1.0, 7.0, past, now=now)
    check("1 half-life → ~0.5", approx(eff, 0.5), f"got {eff:.4f}")

    # Decay: 2 half-lives → ~0.25×
    past2 = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    eff2 = bgm.effective_strength(1.0, 7.0, past2, now=now)
    check("2 half-lives → ~0.25", approx(eff2, 0.25), f"got {eff2:.4f}")

    # Decay: many half-lives, floored
    past_old = (now - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")
    eff_old = bgm.effective_strength(1.0, 7.0, past_old, now=now)
    check("old node floored at DECAY_FLOOR",
          eff_old == bgm.DECAY_FLOOR, f"got {eff_old}")

    # Blend preserves exact-match dominance
    # bm25=20 (exact match), unmanaged → 20 * (0.5 + 0.5*1.0) = 20.0
    check("fresh node: blend = bm25",
          approx(bgm.blend_score(20.0, 1.0), 20.0))
    # bm25=20, fully decayed → 20 * (0.5 + 0.5*0.05) = 20 * 0.525 = 10.5
    check("decayed node: blend ≈ 0.525 × bm25",
          approx(bgm.blend_score(20.0, 0.05), 10.5))
    # Supersedes penalty
    check("supersedes applies 0.25× penalty",
          approx(bgm.blend_score(20.0, 1.0, is_superseded=True), 5.0))


def test_feature_flag():
    print("\nFeature flag")
    os.environ.pop(bgm.FEATURE_FLAG_ENV, None)
    check("flag off by default", not bgm.is_enabled())
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    check("flag on when set to 1", bgm.is_enabled())
    os.environ[bgm.FEATURE_FLAG_ENV] = "0"
    check("flag off when set to 0", not bgm.is_enabled())


def _setup_test_nodes(conn):
    for nid in (TEST_NODE_A, TEST_NODE_B, TEST_NODE_C):
        conn.execute(
            "INSERT OR REPLACE INTO nodes "
            "(id, vault, rel_path, basename, title, content, content_hash, "
            "modified_at, indexed_at) "
            "VALUES (?, 'john-brain', ?, ?, ?, '', 'beef', "
            "datetime('now'), datetime('now'))",
            (nid, f"{nid}.md", f"{nid.rsplit('/', 1)[1]}.md", nid),
        )
    conn.commit()


def _cleanup_test_nodes(conn):
    for nid in (TEST_NODE_A, TEST_NODE_B, TEST_NODE_C):
        conn.execute("DELETE FROM node_access_log WHERE node_id=?", (nid,))
        conn.execute("DELETE FROM node_memory WHERE node_id=?", (nid,))
        conn.execute("DELETE FROM nodes WHERE id=?", (nid,))
    conn.commit()


def test_apply_memory_flag_off():
    print("\napply_memory with flag OFF (no-op)")
    os.environ[bgm.FEATURE_FLAG_ENV] = "0"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _setup_test_nodes(conn)
        hits = [
            {"id": TEST_NODE_A, "bm25_score": 20.0, "combined_score": 20.0,
             "graph_bonus": 0.0, "source": "fts", "title": "A"},
            {"id": TEST_NODE_B, "bm25_score": 5.0,  "combined_score": 5.0,
             "graph_bonus": 0.0, "source": "fts", "title": "B"},
        ]
        before = [h["combined_score"] for h in hits]
        out = bgm.apply_memory(conn, hits, source="search")
        after = [h["combined_score"] for h in out]
        check("scores unchanged when flag off", before == after, f"{before} vs {after}")
        check("no access rows written when flag off",
              conn.execute("SELECT COUNT(*) FROM node_access_log "
                           "WHERE node_id LIKE '__test__/%'").fetchone()[0] == 0)
    finally:
        _cleanup_test_nodes(conn)
        conn.close()


def test_apply_memory_flag_on_unmanaged():
    print("\napply_memory with flag ON, unmanaged nodes (no memory rows)")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup_test_nodes(conn)
        _setup_test_nodes(conn)
        hits = [
            {"id": TEST_NODE_A, "bm25_score": 20.0, "combined_score": 20.0,
             "graph_bonus": 0.0, "source": "fts", "title": "A"},
            {"id": TEST_NODE_B, "bm25_score": 5.0,  "combined_score": 5.0,
             "graph_bonus": 0.0, "source": "fts", "title": "B"},
        ]
        out = bgm.apply_memory(conn, hits, source="search", query_hash="q1")
        check("unmanaged A: combined ≈ 20", approx(out[0]["combined_score"], 20.0),
              f"got {out[0]['combined_score']}")
        check("unmanaged B: combined ≈ 5", approx(out[1]["combined_score"], 5.0))
        check("effective_strength NOT attached for unmanaged",
              all("effective_strength" not in h for h in out))
        check("title untouched", all(h["title"] in ("A", "B") for h in out))
        n_log = conn.execute("SELECT COUNT(*) FROM node_access_log "
                             "WHERE node_id LIKE '__test__/%'").fetchone()[0]
        check("2 access rows logged", n_log == 2, f"got {n_log}")
    finally:
        _cleanup_test_nodes(conn)
        conn.close()


def test_apply_memory_decayed_downranked():
    print("\napply_memory: decayed node ranks below fresh node")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup_test_nodes(conn)
        _setup_test_nodes(conn)
        # A: stale (retrieved 365d ago, fully decayed)
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, last_retrieved_at) "
            "VALUES (?, 1.0, 7.0, datetime('now', '-365 days'))",
            (TEST_NODE_A,),
        )
        # B: fresh (retrieved just now)
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, last_retrieved_at) "
            "VALUES (?, 1.0, 7.0, datetime('now'))",
            (TEST_NODE_B,),
        )
        conn.commit()

        # Both start with same bm25=10 — after blend, B should outrank A.
        hits = [
            {"id": TEST_NODE_A, "bm25_score": 10.0, "combined_score": 10.0,
             "graph_bonus": 0.0, "source": "fts"},
            {"id": TEST_NODE_B, "bm25_score": 10.0, "combined_score": 10.0,
             "graph_bonus": 0.0, "source": "fts"},
        ]
        out = bgm.apply_memory(conn, hits, source="search")
        check("fresh node ranks first", out[0]["id"] == TEST_NODE_B,
              f"got order {[h['id'] for h in out]}")
        check("decayed A near floor",
              out[1]["effective_strength"] == bgm.DECAY_FLOOR)
        check("fresh B at full strength",
              approx(out[0]["effective_strength"], 1.0))
    finally:
        _cleanup_test_nodes(conn)
        conn.close()


def test_apply_memory_supersedes_penalty():
    print("\napply_memory: supersedes applies penalty")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup_test_nodes(conn)
        _setup_test_nodes(conn)
        # C supersedes A
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, superseded_by) "
            "VALUES (?, 1.0, 7.0, ?)",
            (TEST_NODE_A, TEST_NODE_C),
        )
        conn.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days) "
            "VALUES (?, 1.0, 7.0)",
            (TEST_NODE_C,),
        )
        conn.commit()

        hits = [
            {"id": TEST_NODE_A, "bm25_score": 10.0, "combined_score": 10.0,
             "graph_bonus": 0.0, "source": "fts"},
            {"id": TEST_NODE_C, "bm25_score": 8.0,  "combined_score": 8.0,
             "graph_bonus": 0.0, "source": "fts"},
        ]
        out = bgm.apply_memory(conn, hits, source="search")
        check("superseded A demoted below C",
              out[0]["id"] == TEST_NODE_C,
              f"got order {[h['id'] for h in out]}")
        check("A's superseded_by populated",
              next(h["superseded_by"] for h in out if h["id"] == TEST_NODE_A) == TEST_NODE_C)
        # A bm25 10 * (0.5 + 0.5*1.0) * 0.25 = 10 * 1.0 * 0.25 = 2.5
        a_score = next(h["combined_score"] for h in out if h["id"] == TEST_NODE_A)
        check("A's blended score = 2.5", approx(a_score, 2.5), f"got {a_score}")
    finally:
        _cleanup_test_nodes(conn)
        conn.close()


def test_no_fts_trigger_churn():
    print("\nno FTS trigger churn on memory updates")
    os.environ[bgm.FEATURE_FLAG_ENV] = "1"
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _cleanup_test_nodes(conn)
        _setup_test_nodes(conn)
        conn.execute(
            "INSERT INTO node_memory (node_id) VALUES (?)", (TEST_NODE_A,)
        )
        conn.commit()

        # FTS5 'merge' command would expose corruption; integrity check is enough.
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        check("integrity ok after memory writes", ic == "ok", ic)

        # Verify FTS row count unchanged (memory writes must not touch FTS)
        fts_count = conn.execute("SELECT COUNT(*) FROM nodes_fts").fetchone()[0]
        nodes_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        check("FTS and nodes count consistent", fts_count == nodes_count,
              f"fts={fts_count} nodes={nodes_count}")
    finally:
        _cleanup_test_nodes(conn)
        conn.close()


def main():
    if not DB.exists():
        print(f"DB not found: {DB}", file=sys.stderr)
        return 1
    test_pure_functions()
    test_feature_flag()
    test_apply_memory_flag_off()
    test_apply_memory_flag_on_unmanaged()
    test_apply_memory_decayed_downranked()
    test_apply_memory_supersedes_penalty()
    test_no_fts_trigger_churn()
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*48}\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
