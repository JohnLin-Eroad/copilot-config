#!/usr/bin/env python3
"""Phase 4 tests: JSON output surfacing of memory fields.

Design contract:
  * Unmanaged nodes (no node_memory row) get NO memory fields attached.
    Output stays clean for the majority case.
  * Managed nodes get: effective_strength, confidence, retrieval_count,
    superseded_by. (error_note stays admin-only.)
  * apply_memory(resort=False) keeps caller's ordering (used by traverse,
    which sorts by edge weight) while still enriching + reinforcing.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/Users/johnlin/.copilot/scripts")

os.environ["BRAIN_DECAY_ENABLED"] = "1"

import brain_graph_memory as bgm  # noqa: E402

DB = "/Users/johnlin/.copilot/brain-graph.db"

# synthetic node ids
TA = "__test__/p4-a"
TB = "__test__/p4-b"
TC = "__test__/p4-c"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def _seed_nodes(c: sqlite3.Connection) -> None:
    for nid in (TA, TB, TC):
        c.execute(
            "INSERT OR REPLACE INTO nodes "
            "(id, vault, rel_path, basename, title, content, content_hash, "
            " size_bytes, modified_at, indexed_at, tombstone) "
            "VALUES (?, 'john-brain', ?, ?, ?, '', '', 0, "
            " datetime('now'), datetime('now'), 0)",
            (nid, nid, nid.rsplit("/", 1)[-1], nid),
        )
    c.commit()


def _cleanup(c: sqlite3.Connection) -> None:
    for nid in (TA, TB, TC):
        c.execute("DELETE FROM node_memory WHERE node_id=?", (nid,))
        c.execute("DELETE FROM node_access_log WHERE node_id=?", (nid,))
        c.execute("DELETE FROM nodes WHERE id=?", (nid,))
    c.commit()


PASS = 0
FAIL = 0


def check(label: str, cond: bool, got=None) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        suffix = f"  — got {got}" if got is not None else ""
        print(f"  ✓ {label}{suffix}")
    else:
        FAIL += 1
        suffix = f"  — got {got}" if got is not None else ""
        print(f"  ✗ {label}{suffix}")


# ---------------------------------------------------------------------------

def test_unmanaged_has_no_memory_fields():
    print("\nUnmanaged nodes get NO memory fields attached")
    c = _conn()
    try:
        _cleanup(c); _seed_nodes(c)
        hits = [
            {"id": TA, "bm25_score": 10.0, "graph_bonus": 0.0, "combined_score": 10.0},
            {"id": TB, "bm25_score": 5.0,  "graph_bonus": 0.0, "combined_score": 5.0},
        ]
        bgm.apply_memory(c, hits, source="search")
        check("TA has no effective_strength key", "effective_strength" not in hits[0])
        check("TA has no confidence key", "confidence" not in hits[0])
        check("TA has no superseded_by key", "superseded_by" not in hits[0])
        check("TA has no retrieval_count key", "retrieval_count" not in hits[0])
        check("TB has no memory fields", "effective_strength" not in hits[1])
        # combined_score must remain (used for sort)
        check("TA still has combined_score", "combined_score" in hits[0])
    finally:
        _cleanup(c); c.close()


def test_managed_gets_memory_fields():
    print("\nManaged nodes get effective_strength, confidence, retrieval_count, superseded_by")
    c = _conn()
    try:
        _cleanup(c); _seed_nodes(c)
        c.execute(
            "INSERT INTO node_memory "
            "(node_id, strength, half_life_days, confidence, retrieval_count, "
            " last_retrieved_at) "
            "VALUES (?, 0.8, 7.0, 'verified', 3, datetime('now'))",
            (TA,),
        )
        c.commit()

        hits = [{"id": TA, "bm25_score": 10.0, "graph_bonus": 0.0, "combined_score": 10.0}]
        bgm.apply_memory(c, hits, source="search")

        h = hits[0]
        check("effective_strength surfaced", "effective_strength" in h, h.get("effective_strength"))
        check("confidence surfaced", h.get("confidence") == "verified", h.get("confidence"))
        # retrieval_count is the PRE-reinforce value (what user sees reflects state before this hit)
        check("retrieval_count surfaced (pre-reinforce)", h.get("retrieval_count") == 3, h.get("retrieval_count"))
        check("superseded_by surfaced (null)", h.get("superseded_by") is None)
    finally:
        _cleanup(c); c.close()


def test_superseded_managed_gets_field():
    print("\nSuperseded managed node surfaces superseded_by id")
    c = _conn()
    try:
        _cleanup(c); _seed_nodes(c)
        # TC supersedes TA
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, confidence) "
            "VALUES (?, 0.7, 7.0, 'observed')", (TC,))
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, confidence, "
            " superseded_by) VALUES (?, 0.7, 7.0, 'observed', ?)", (TA, TC))
        c.commit()

        hits = [{"id": TA, "bm25_score": 10.0, "graph_bonus": 0.0, "combined_score": 10.0}]
        bgm.apply_memory(c, hits, source="search")
        h = hits[0]
        check("superseded_by populated", h.get("superseded_by") == TC, h.get("superseded_by"))
    finally:
        _cleanup(c); c.close()


def test_resort_false_preserves_order():
    print("\napply_memory(resort=False) preserves caller's ordering")
    c = _conn()
    try:
        _cleanup(c); _seed_nodes(c)
        # TA has high bm25 but is decayed/superseded; TB has lower bm25 but fresh
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, confidence) "
            "VALUES (?, 0.05, 7.0, 'observed')", (TA,))
        c.commit()

        # Caller has ordered by edge_weight: TA first, TB second
        hits = [
            {"id": TA, "bm25_score": 20.0, "graph_bonus": 0.0, "combined_score": 20.0,
             "edge_weight": 0.9},
            {"id": TB, "bm25_score": 5.0,  "graph_bonus": 0.0, "combined_score": 5.0,
             "edge_weight": 0.5},
        ]
        bgm.apply_memory(c, hits, source="traverse", resort=False)

        check("TA still first (caller order preserved)", hits[0]["id"] == TA, hits[0]["id"])
        check("TB still second", hits[1]["id"] == TB, hits[1]["id"])
        check("TA still got enriched", "effective_strength" in hits[0])
    finally:
        _cleanup(c); c.close()


def test_resort_true_blends_and_reorders():
    print("\napply_memory(resort=True, default) re-sorts by blended score")
    c = _conn()
    try:
        _cleanup(c); _seed_nodes(c)
        # TA: huge bm25, but heavily decayed → blend kills it
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, "
            " last_retrieved_at, confidence) "
            "VALUES (?, 1.0, 1.0, datetime('now','-365 days'), 'observed')", (TA,))
        c.commit()

        hits = [
            {"id": TA, "bm25_score": 12.0, "graph_bonus": 0.0, "combined_score": 12.0},
            {"id": TB, "bm25_score": 10.0, "graph_bonus": 0.0, "combined_score": 10.0},
        ]
        bgm.apply_memory(c, hits, source="search")  # resort defaults True

        # TA blended: 12 * (0.5 + 0.5*0.05) = 12 * 0.525 = 6.3
        # TB unmanaged: stays at 10.0
        check("TB now ranks above decayed TA", hits[0]["id"] == TB, hits[0]["id"])
        check("TA demoted to second", hits[1]["id"] == TA, hits[1]["id"])
    finally:
        _cleanup(c); c.close()


def test_reinforce_still_runs_when_resort_false():
    print("\napply_memory(resort=False) still reinforces managed nodes")
    c = _conn()
    try:
        _cleanup(c); _seed_nodes(c)
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, "
            " retrieval_count, confidence) "
            "VALUES (?, 0.5, 7.0, 0, 'observed')", (TA,))
        c.commit()

        hits = [{"id": TA, "bm25_score": 10.0, "graph_bonus": 0.0, "combined_score": 10.0}]
        bgm.apply_memory(c, hits, source="traverse", resort=False)

        rc, s = c.execute(
            "SELECT retrieval_count, strength FROM node_memory WHERE node_id=?",
            (TA,),
        ).fetchone()
        check("retrieval_count incremented", rc == 1, rc)
        check("strength bumped 0.5 + 0.05 = 0.55", abs(s - 0.55) < 1e-9, s)
    finally:
        _cleanup(c); c.close()


def test_flag_off_no_fields_added():
    print("\nflag OFF: no memory fields added even for managed nodes")
    c = _conn()
    try:
        _cleanup(c); _seed_nodes(c)
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, confidence) "
            "VALUES (?, 0.8, 7.0, 'verified')", (TA,))
        c.commit()

        os.environ["BRAIN_DECAY_ENABLED"] = "0"
        try:
            hits = [{"id": TA, "bm25_score": 10.0, "graph_bonus": 0.0, "combined_score": 10.0}]
            bgm.apply_memory(c, hits, source="search")
            check("no effective_strength when flag off", "effective_strength" not in hits[0])
            check("no confidence when flag off", "confidence" not in hits[0])
            check("combined_score unchanged", hits[0]["combined_score"] == 10.0)
        finally:
            os.environ["BRAIN_DECAY_ENABLED"] = "1"
    finally:
        _cleanup(c); c.close()


# ---------------------------------------------------------------------------

def main() -> int:
    test_unmanaged_has_no_memory_fields()
    test_managed_gets_memory_fields()
    test_superseded_managed_gets_field()
    test_resort_false_preserves_order()
    test_resort_true_blends_and_reorders()
    test_reinforce_still_runs_when_resort_false()
    test_flag_off_no_fields_added()

    print("\n" + "=" * 48)
    print(f"{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
