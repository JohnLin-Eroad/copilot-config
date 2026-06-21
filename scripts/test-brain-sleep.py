#!/usr/bin/env python3
"""Tests for brain-sleep.py — scheduled background decay/cleanup."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

DB = os.path.expanduser("~/.copilot/brain-graph.db")
SLEEP = os.path.expanduser("~/.copilot/scripts/brain-sleep.py")

TA = "__test__/p6-a"  # very stale (should be marked stale)
TB = "__test__/p6-b"  # fresh (should NOT be marked stale)
TC = "__test__/p6-c"  # already stale (idempotent — no change)

OLD_LOG = "__test__/p6-old-log"  # node for old access-log entries
NEW_LOG = "__test__/p6-new-log"  # node for fresh access-log entries

ALL_TEST_NODES = (TA, TB, TC, OLD_LOG, NEW_LOG)

PASS = FAIL = 0


def check(name: str, cond: bool, got=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}" + (f"  — got {got}" if got is not None else ""))
    else:
        FAIL += 1
        print(f"  ✗ {name}  — got {got}")


def _cleanup(c: sqlite3.Connection):
    for nid in ALL_TEST_NODES:
        c.execute("DELETE FROM node_memory WHERE node_id=?", (nid,))
        c.execute("DELETE FROM node_memory WHERE superseded_by=?", (nid,))
        c.execute("DELETE FROM node_access_log WHERE node_id=?", (nid,))
    for nid in ALL_TEST_NODES:
        c.execute("DELETE FROM nodes WHERE id=?", (nid,))
    c.commit()


def _seed_nodes(c: sqlite3.Connection):
    for nid in ALL_TEST_NODES:
        c.execute(
            "INSERT OR REPLACE INTO nodes "
            "(id, vault, rel_path, basename, title, content_hash, size_bytes,"
            " modified_at, indexed_at, tombstone) "
            "VALUES (?, 'john-brain', ?, ?, ?, 'x', 0,"
            " datetime('now'), datetime('now'), 0)",
            (nid, nid, nid.rsplit("/", 1)[-1], nid),
        )
    c.commit()


def _seed_memory(c: sqlite3.Connection, nid: str, *, strength: float,
                 half_life: float, last_retrieved_days_ago: float,
                 confidence: str = "observed", retrieval_count: int = 5):
    ts = (datetime.utcnow() - timedelta(days=last_retrieved_days_ago)) \
        .strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT OR REPLACE INTO node_memory "
        "(node_id, strength, half_life_days, last_retrieved_at, "
        " retrieval_count, confidence, valence) "
        "VALUES (?, ?, ?, ?, ?, ?, 'neutral')",
        (nid, strength, half_life, ts, retrieval_count, confidence),
    )
    c.commit()


def _seed_access_log(c: sqlite3.Connection, nid: str, *, days_ago: float):
    ts = (datetime.utcnow() - timedelta(days=days_ago)) \
        .strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO node_access_log (node_id, accessed_at, source, query_hash) "
        "VALUES (?, ?, 'search', 'test')",
        (nid, ts),
    )
    c.commit()


def run_sleep(*args, expect_exit=0) -> dict:
    env = dict(os.environ)
    env["BRAIN_DECAY_ENABLED"] = "0"  # sleep must work with flag off too
    proc = subprocess.run(
        ["python3", SLEEP, *args],
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != expect_exit:
        print(f"   STDERR: {proc.stderr}")
        print(f"   STDOUT: {proc.stdout}")
        raise AssertionError(f"sleep exit={proc.returncode}, expected {expect_exit}")
    if proc.stdout.strip():
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            print(f"   raw stdout: {proc.stdout!r}")
            raise
    return {}


# ---------- TESTS ----------

def test_mark_stale_flips_low_strength():
    print("\nmark-stale flips confidence to 'stale' for low-effective-strength rows")
    c = sqlite3.connect(DB)
    _cleanup(c); _seed_nodes(c)
    # TA: very decayed (60d since last retrieve, half-life 7d → eff ≈ 0.0044*0.5 floor → 0.05)
    _seed_memory(c, TA, strength=0.5, half_life=7.0,
                 last_retrieved_days_ago=60, confidence="observed")
    # TB: fresh (1d ago, half-life 14d → eff ≈ 0.95)
    _seed_memory(c, TB, strength=1.0, half_life=14.0,
                 last_retrieved_days_ago=1, confidence="observed")
    c.close()

    out = run_sleep("mark-stale", "--threshold", "0.10")
    check("ok=true", out.get("ok") is True, out.get("ok"))
    check("marked_stale count includes TA",
          out.get("marked_stale", 0) >= 1, out.get("marked_stale"))

    c = sqlite3.connect(DB)
    ta_conf = c.execute("SELECT confidence FROM node_memory WHERE node_id=?",
                        (TA,)).fetchone()[0]
    tb_conf = c.execute("SELECT confidence FROM node_memory WHERE node_id=?",
                        (TB,)).fetchone()[0]
    check("TA flipped to stale", ta_conf == "stale", ta_conf)
    check("TB NOT flipped (still fresh)", tb_conf == "observed", tb_conf)
    _cleanup(c); c.close()


def test_mark_stale_preserves_other_fields():
    print("\nmark-stale preserves strength, half_life, retrieval_count")
    c = sqlite3.connect(DB)
    _cleanup(c); _seed_nodes(c)
    _seed_memory(c, TA, strength=0.42, half_life=21.5,
                 last_retrieved_days_ago=90, confidence="observed",
                 retrieval_count=17)
    c.close()

    run_sleep("mark-stale", "--threshold", "0.10")

    c = sqlite3.connect(DB)
    row = c.execute(
        "SELECT strength, half_life_days, retrieval_count, confidence "
        "FROM node_memory WHERE node_id=?", (TA,)).fetchone()
    check("strength preserved (0.42)", abs(row[0] - 0.42) < 1e-6, row[0])
    check("half_life preserved (21.5)", abs(row[1] - 21.5) < 1e-6, row[1])
    check("retrieval_count preserved (17)", row[2] == 17, row[2])
    check("confidence flipped to stale", row[3] == "stale", row[3])
    _cleanup(c); c.close()


def test_mark_stale_idempotent():
    print("\nmark-stale is idempotent (already-stale rows not re-touched)")
    c = sqlite3.connect(DB)
    _cleanup(c); _seed_nodes(c)
    _seed_memory(c, TC, strength=0.5, half_life=7.0,
                 last_retrieved_days_ago=60, confidence="stale")
    c.close()

    out = run_sleep("mark-stale", "--threshold", "0.10")
    # TC already stale — should NOT be counted as newly marked
    check("already-stale rows not counted as marked_stale",
          out.get("marked_stale", 99) == 0, out.get("marked_stale"))

    # Second run also yields 0
    out2 = run_sleep("mark-stale", "--threshold", "0.10")
    check("second run also marks 0", out2.get("marked_stale", 99) == 0,
          out2.get("marked_stale"))

    c = sqlite3.connect(DB); _cleanup(c); c.close()


def test_mark_stale_dry_run():
    print("\nmark-stale --dry-run reports candidates but does not modify")
    c = sqlite3.connect(DB)
    _cleanup(c); _seed_nodes(c)
    _seed_memory(c, TA, strength=0.5, half_life=7.0,
                 last_retrieved_days_ago=60, confidence="observed")
    c.close()

    out = run_sleep("mark-stale", "--threshold", "0.10", "--dry-run")
    check("ok=true (dry-run)", out.get("ok") is True)
    check("dry_run=true in output", out.get("dry_run") is True, out.get("dry_run"))
    check("would_mark_stale includes TA",
          out.get("would_mark_stale", 0) >= 1, out.get("would_mark_stale"))

    c = sqlite3.connect(DB)
    conf = c.execute("SELECT confidence FROM node_memory WHERE node_id=?",
                     (TA,)).fetchone()[0]
    check("TA confidence NOT changed (still observed)", conf == "observed", conf)
    _cleanup(c); c.close()


def test_prune_access_log():
    print("\nprune-access-log deletes entries older than --older-than-days")
    c = sqlite3.connect(DB)
    _cleanup(c); _seed_nodes(c)
    _seed_access_log(c, OLD_LOG, days_ago=120)
    _seed_access_log(c, OLD_LOG, days_ago=95)
    _seed_access_log(c, NEW_LOG, days_ago=5)
    _seed_access_log(c, NEW_LOG, days_ago=1)
    c.close()

    out = run_sleep("prune-access-log", "--older-than-days", "90")
    check("ok=true", out.get("ok") is True)
    check("deleted count >= 2", out.get("deleted", 0) >= 2, out.get("deleted"))

    c = sqlite3.connect(DB)
    old_remaining = c.execute(
        "SELECT COUNT(*) FROM node_access_log WHERE node_id=?",
        (OLD_LOG,)).fetchone()[0]
    new_remaining = c.execute(
        "SELECT COUNT(*) FROM node_access_log WHERE node_id=?",
        (NEW_LOG,)).fetchone()[0]
    check("old entries deleted", old_remaining == 0, old_remaining)
    check("new entries kept", new_remaining == 2, new_remaining)
    _cleanup(c); c.close()


def test_prune_access_log_dry_run():
    print("\nprune-access-log --dry-run reports but does not delete")
    c = sqlite3.connect(DB)
    _cleanup(c); _seed_nodes(c)
    _seed_access_log(c, OLD_LOG, days_ago=120)
    c.close()

    out = run_sleep("prune-access-log", "--older-than-days", "90", "--dry-run")
    check("dry_run=true", out.get("dry_run") is True)
    check("would_delete >= 1", out.get("would_delete", 0) >= 1,
          out.get("would_delete"))

    c = sqlite3.connect(DB)
    remaining = c.execute(
        "SELECT COUNT(*) FROM node_access_log WHERE node_id=?",
        (OLD_LOG,)).fetchone()[0]
    check("old entry still present (dry-run)", remaining == 1, remaining)
    _cleanup(c); c.close()


def test_run_all_does_both():
    print("\nrun-all performs mark-stale + prune-access-log in one go")
    c = sqlite3.connect(DB)
    _cleanup(c); _seed_nodes(c)
    _seed_memory(c, TA, strength=0.5, half_life=7.0,
                 last_retrieved_days_ago=60, confidence="observed")
    _seed_access_log(c, OLD_LOG, days_ago=200)
    c.close()

    out = run_sleep("run-all",
                    "--stale-threshold", "0.10",
                    "--access-log-keep-days", "90")
    check("ok=true", out.get("ok") is True)
    check("summary has mark_stale block",
          "mark_stale" in out, list(out.keys()))
    check("summary has prune_access_log block",
          "prune_access_log" in out, list(out.keys()))
    check("mark_stale ran (>=1)",
          out["mark_stale"].get("marked_stale", 0) >= 1,
          out["mark_stale"].get("marked_stale"))
    check("prune ran (>=1)",
          out["prune_access_log"].get("deleted", 0) >= 1,
          out["prune_access_log"].get("deleted"))

    c = sqlite3.connect(DB); _cleanup(c); c.close()


def test_works_with_flag_off():
    print("\nbrain-sleep works with BRAIN_DECAY_ENABLED=0 (housekeeping always runs)")
    # run_sleep already forces flag=0 — just verify a basic run succeeds
    out = run_sleep("mark-stale", "--threshold", "0.10")
    check("exit 0 with flag off", out.get("ok") is True, out.get("ok"))


def main() -> int:
    test_mark_stale_flips_low_strength()
    test_mark_stale_preserves_other_fields()
    test_mark_stale_idempotent()
    test_mark_stale_dry_run()
    test_prune_access_log()
    test_prune_access_log_dry_run()
    test_run_all_does_both()
    test_works_with_flag_off()

    print("\n" + "=" * 48)
    print(f"{PASS}/{PASS+FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
