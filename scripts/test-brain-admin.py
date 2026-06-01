#!/usr/bin/env python3
"""Phase 5 tests: brain-graph-admin.py subcommands.

Contract:
  * Admin commands work REGARDLESS of BRAIN_DECAY_ENABLED (read path flag).
  * mark-confidence creates a node_memory row when missing, else updates.
  * mark-confidence validates node exists in `nodes` table.
  * decide --winner X --supersedes Y validates both exist; sets winner
    confidence=verified, loser.superseded_by=winner + superseded_at=now.
  * inspect prints JSON with node info + memory row (or null) + recent accesses.
  * list-stale lists managed nodes with lowest effective_strength.
  * All commands print JSON to stdout for scripting.
  * All operations idempotent — re-running yields same DB state.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

DB = "/Users/johnlin/.copilot/brain-graph.db"
ADMIN = "/Users/johnlin/.copilot/scripts/brain-graph-admin.py"

TA = "__test__/p5-a"
TB = "__test__/p5-b"
TC = "__test__/p5-c"  # nonexistent — never seeded


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def _seed(c: sqlite3.Connection) -> None:
    for nid in (TA, TB):
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
    # Delete memory + access rows for ALL test nodes first (FK: node_memory.superseded_by)
    for nid in (TA, TB, TC):
        c.execute("DELETE FROM node_memory WHERE node_id=?", (nid,))
        c.execute("DELETE FROM node_memory WHERE superseded_by=?", (nid,))
        c.execute("DELETE FROM node_access_log WHERE node_id=?", (nid,))
    for nid in (TA, TB, TC):
        c.execute("DELETE FROM nodes WHERE id=?", (nid,))
    c.commit()


def run_admin(*args, expect_exit=0) -> dict:
    """Run admin CLI, return parsed JSON stdout. Always uses flag OFF."""
    env = dict(os.environ)
    env["BRAIN_DECAY_ENABLED"] = "0"  # admin must work with read flag off
    proc = subprocess.run(
        ["python3", ADMIN, *args],
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != expect_exit:
        print(f"   STDERR: {proc.stderr}")
        print(f"   STDOUT: {proc.stdout}")
        raise AssertionError(f"admin exit={proc.returncode}, expected {expect_exit}")
    if proc.stdout.strip():
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            print(f"   raw stdout: {proc.stdout!r}")
            raise
    return {}


PASS = 0; FAIL = 0


def check(label, cond, got=None):
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

def test_mark_confidence_creates_row():
    print("\nmark-confidence creates a node_memory row when missing")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        out = run_admin("mark-confidence", "--node-id", TA, "--level", "verified")
        check("returns JSON with ok=true", out.get("ok") is True)
        check("returns created=true", out.get("created") is True)

        row = c.execute(
            "SELECT confidence, strength FROM node_memory WHERE node_id=?", (TA,)
        ).fetchone()
        check("row exists", row is not None)
        check("confidence=verified", row[0] == "verified", row[0])
        check("strength defaulted to 1.0 for verified", row[1] == 1.0, row[1])
    finally:
        _cleanup(c); c.close()


def test_mark_confidence_updates_existing():
    print("\nmark-confidence updates existing row without resetting strength")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, confidence, retrieval_count) "
            "VALUES (?, 0.42, 14.0, 'observed', 7)", (TA,))
        c.commit()

        out = run_admin("mark-confidence", "--node-id", TA, "--level", "inferred")
        check("created=false (updated)", out.get("created") is False)

        row = c.execute(
            "SELECT confidence, strength, half_life_days, retrieval_count "
            "FROM node_memory WHERE node_id=?", (TA,)
        ).fetchone()
        check("confidence updated", row[0] == "inferred", row[0])
        check("strength preserved (0.42)", row[1] == 0.42, row[1])
        check("half_life preserved (14.0)", row[2] == 14.0, row[2])
        check("retrieval_count preserved (7)", row[3] == 7, row[3])
    finally:
        _cleanup(c); c.close()


def test_mark_confidence_rejects_unknown_node():
    print("\nmark-confidence rejects nonexistent node")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        out = run_admin("mark-confidence", "--node-id", TC, "--level", "verified",
                        expect_exit=2)
        check("ok=false", out.get("ok") is False)
        check("error mentions not found", "not found" in (out.get("error") or "").lower())
        row = c.execute("SELECT 1 FROM node_memory WHERE node_id=?", (TC,)).fetchone()
        check("no row created for nonexistent node", row is None)
    finally:
        _cleanup(c); c.close()


def test_mark_confidence_rejects_invalid_level():
    print("\nmark-confidence rejects invalid level (argparse choices)")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        env = dict(os.environ); env["BRAIN_DECAY_ENABLED"] = "0"
        proc = subprocess.run(
            ["python3", ADMIN, "mark-confidence", "--node-id", TA, "--level", "bogus"],
            capture_output=True, text=True, env=env,
        )
        check("nonzero exit", proc.returncode != 0, proc.returncode)
        check("argparse complains about invalid choice",
              "invalid choice" in proc.stderr or "bogus" in proc.stderr)
    finally:
        _cleanup(c); c.close()


def test_decide_supersedes():
    print("\ndecide --winner X --supersedes Y links the pair")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        out = run_admin("decide", "--winner", TA, "--supersedes", TB)
        check("ok=true", out.get("ok") is True)

        winner_row = c.execute(
            "SELECT confidence FROM node_memory WHERE node_id=?", (TA,)
        ).fetchone()
        loser_row = c.execute(
            "SELECT superseded_by, superseded_at FROM node_memory WHERE node_id=?", (TB,)
        ).fetchone()
        check("winner row created with confidence=verified",
              winner_row is not None and winner_row[0] == "verified",
              winner_row)
        check("loser superseded_by → winner",
              loser_row is not None and loser_row[0] == TA, loser_row)
        check("loser superseded_at populated",
              loser_row is not None and loser_row[1] is not None)
    finally:
        _cleanup(c); c.close()


def test_decide_idempotent():
    print("\ndecide is idempotent (running twice yields same state)")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        run_admin("decide", "--winner", TA, "--supersedes", TB)
        first = c.execute(
            "SELECT superseded_by, superseded_at FROM node_memory WHERE node_id=?", (TB,)
        ).fetchone()
        # second run
        run_admin("decide", "--winner", TA, "--supersedes", TB)
        second = c.execute(
            "SELECT superseded_by, superseded_at FROM node_memory WHERE node_id=?", (TB,)
        ).fetchone()
        check("superseded_by unchanged", second[0] == first[0] == TA)
        # superseded_at may be re-written to new timestamp; that's OK; just one row
        count = c.execute(
            "SELECT COUNT(*) FROM node_memory WHERE node_id=?", (TB,)
        ).fetchone()[0]
        check("still exactly one row for loser", count == 1, count)
    finally:
        _cleanup(c); c.close()


def test_decide_rejects_self_supersede():
    print("\ndecide rejects X --supersedes X (would create cycle)")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        out = run_admin("decide", "--winner", TA, "--supersedes", TA, expect_exit=2)
        check("ok=false", out.get("ok") is False)
        check("error mentions self/cycle",
              any(k in (out.get("error") or "").lower() for k in ("self", "cycle", "same")))
    finally:
        _cleanup(c); c.close()


def test_inspect_returns_full_state():
    print("\ninspect returns node info, memory row, recent accesses")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, confidence, retrieval_count) "
            "VALUES (?, 0.65, 7.0, 'verified', 4)", (TA,))
        c.execute(
            "INSERT INTO node_access_log (node_id, accessed_at, source) "
            "VALUES (?, datetime('now'), 'search')", (TA,))
        c.commit()

        out = run_admin("inspect", "--node-id", TA)
        check("node block present", out.get("node", {}).get("id") == TA, out.get("node"))
        check("memory block present", out.get("memory") is not None)
        mem = out.get("memory") or {}
        check("confidence=verified", mem.get("confidence") == "verified")
        check("retrieval_count=4", mem.get("retrieval_count") == 4)
        check("effective_strength computed", "effective_strength" in mem)
        check("recent_accesses present", isinstance(out.get("recent_accesses"), list))
        check("recent_accesses has 1 entry", len(out.get("recent_accesses", [])) >= 1)
    finally:
        _cleanup(c); c.close()


def test_inspect_unmanaged_returns_null_memory():
    print("\ninspect on unmanaged node returns memory=null")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        out = run_admin("inspect", "--node-id", TA)
        check("node block present", out.get("node", {}).get("id") == TA)
        check("memory is null", out.get("memory") is None, out.get("memory"))
    finally:
        _cleanup(c); c.close()


def test_inspect_missing_node():
    print("\ninspect on nonexistent node returns error")
    out = run_admin("inspect", "--node-id", TC, expect_exit=2)
    check("ok=false", out.get("ok") is False)
    check("error message", "not found" in (out.get("error") or "").lower())


def test_list_stale():
    print("\nlist-stale returns lowest effective_strength managed nodes")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        # TA fully decayed (365d ago), TB fresh
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, last_retrieved_at) "
            "VALUES (?, 1.0, 7.0, datetime('now','-365 days'))", (TA,))
        c.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, last_retrieved_at) "
            "VALUES (?, 1.0, 7.0, datetime('now'))", (TB,))
        c.commit()

        out = run_admin("list-stale", "--limit", "5")
        rows = out.get("results", [])
        check("returns list", isinstance(rows, list), type(rows).__name__)
        ids = [r["node_id"] for r in rows]
        check(f"TA (stale) in results", TA in ids)
        # TA must appear BEFORE TB (more stale = listed first)
        if TA in ids and TB in ids:
            check("TA listed before TB", ids.index(TA) < ids.index(TB))
        elif TA in ids:
            check("TA listed (TB filtered, fresh enough)", True)
    finally:
        _cleanup(c); c.close()


def test_admin_works_with_read_flag_off():
    print("\nadmin commands work with BRAIN_DECAY_ENABLED=0 (already covered, sanity check)")
    c = _conn()
    try:
        _cleanup(c); _seed(c)
        # explicit flag-off run
        env = dict(os.environ); env["BRAIN_DECAY_ENABLED"] = "0"
        proc = subprocess.run(
            ["python3", ADMIN, "mark-confidence", "--node-id", TA, "--level", "observed"],
            capture_output=True, text=True, env=env,
        )
        check("exit 0 with flag off", proc.returncode == 0, proc.returncode)
        row = c.execute(
            "SELECT confidence FROM node_memory WHERE node_id=?", (TA,)
        ).fetchone()
        check("row created with flag off", row is not None and row[0] == "observed")
    finally:
        _cleanup(c); c.close()


# ---------------------------------------------------------------------------

def main() -> int:
    test_mark_confidence_creates_row()
    test_mark_confidence_updates_existing()
    test_mark_confidence_rejects_unknown_node()
    test_mark_confidence_rejects_invalid_level()
    test_decide_supersedes()
    test_decide_idempotent()
    test_decide_rejects_self_supersede()
    test_inspect_returns_full_state()
    test_inspect_unmanaged_returns_null_memory()
    test_inspect_missing_node()
    test_list_stale()
    test_admin_works_with_read_flag_off()

    print("\n" + "=" * 48)
    print(f"{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
