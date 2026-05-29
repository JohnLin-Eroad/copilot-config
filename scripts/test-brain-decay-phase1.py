#!/usr/bin/env python3
"""Tests for Phase 1 brain-decay schema migration.

Runs against the live DB but only inserts into node_memory / node_access_log
with a synthetic test node id, then cleans up. Pure-additive — never touches
existing nodes/edges rows.

Usage:  python3 ~/.copilot/scripts/test-brain-decay-phase1.py
Exit:   0 on all-pass, 1 on any failure.
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

DB = Path.home() / ".copilot" / "brain-graph.db"
TEST_NODE_ID = "__test__/brain-decay-phase1"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    if not DB.exists():
        print(f"DB not found: {DB}", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()

    print(f"DB: {DB}\n")

    # ── 1. Schema presence ─────────────────────────────────────────
    print("Schema presence")
    tables = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    check("node_memory table exists", "node_memory" in tables)
    check("node_access_log table exists", "node_access_log" in tables)

    indexes = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()}
    for ix in ("idx_memory_strength", "idx_memory_last_retrieved",
               "idx_memory_superseded", "idx_memory_confidence",
               "idx_access_node", "idx_access_time"):
        check(f"index {ix}", ix in indexes)

    # ── 2. Baseline counts unchanged ───────────────────────────────
    print("\nBaseline data integrity")
    n_nodes = cur.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    n_edges = cur.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    check("nodes ≥ 918", n_nodes >= 918, f"actual={n_nodes}")
    check("edges ≥ 9691", n_edges >= 9691, f"actual={n_edges}")

    ic = cur.execute("PRAGMA integrity_check").fetchone()[0]
    check("integrity_check ok", ic == "ok", ic)

    # ── 3. FK enforcement ──────────────────────────────────────────
    print("\nForeign-key enforcement")
    try:
        cur.execute(
            "INSERT INTO node_memory (node_id) VALUES (?)",
            ("does/not/exist",),
        )
        check("FK rejects unknown node_id", False, "insert succeeded!")
        con.rollback()
    except sqlite3.IntegrityError:
        check("FK rejects unknown node_id", True)

    # ── 4. CHECK constraints ───────────────────────────────────────
    print("\nCHECK constraints")
    real_id = cur.execute("SELECT id FROM nodes LIMIT 1").fetchone()[0]

    cases = [
        ("strength > 1 rejected",
         "INSERT INTO node_memory (node_id, strength) VALUES (?, 1.5)", (real_id,)),
        ("strength < 0 rejected",
         "INSERT INTO node_memory (node_id, strength) VALUES (?, -0.1)", (real_id,)),
        ("half_life ≤ 0 rejected",
         "INSERT INTO node_memory (node_id, half_life_days) VALUES (?, 0)", (real_id,)),
        ("bad confidence rejected",
         "INSERT INTO node_memory (node_id, confidence) VALUES (?, 'bogus')", (real_id,)),
        ("bad valence rejected",
         "INSERT INTO node_memory (node_id, valence) VALUES (?, 'angry')", (real_id,)),
        ("bad access source rejected",
         "INSERT INTO node_access_log (node_id, source) VALUES (?, 'telepathy')", (real_id,)),
    ]
    for name, sql, params in cases:
        try:
            cur.execute(sql, params)
            check(name, False, "insert succeeded!")
            con.rollback()
        except sqlite3.IntegrityError:
            check(name, True)

    # ── 5. Round-trip insert + cascade delete ──────────────────────
    print("\nRound-trip + cascade")
    try:
        cur.execute(
            "INSERT OR IGNORE INTO nodes (id, vault, path, basename, title, content, frontmatter, mtime) "
            "VALUES (?, 'john-brain', ?, 'phase1-test.md', 'phase1-test', '', '{}', strftime('%s','now'))",
            (TEST_NODE_ID, f"{TEST_NODE_ID}.md"),
        )
        cur.execute(
            "INSERT INTO node_memory (node_id, strength, half_life_days, confidence, valence) "
            "VALUES (?, 0.75, 14.0, 'observed', 'positive')",
            (TEST_NODE_ID,),
        )
        cur.execute(
            "INSERT INTO node_access_log (node_id, source, query_hash) VALUES (?, 'search', 'h1')",
            (TEST_NODE_ID,),
        )
        cur.execute(
            "INSERT INTO node_access_log (node_id, source, query_hash) VALUES (?, 'fetch', 'h2')",
            (TEST_NODE_ID,),
        )

        mem = cur.execute(
            "SELECT strength, half_life_days, confidence, valence FROM node_memory WHERE node_id=?",
            (TEST_NODE_ID,),
        ).fetchone()
        check("node_memory round-trip", mem == (0.75, 14.0, "observed", "positive"), str(mem))

        n_acc = cur.execute(
            "SELECT COUNT(*) FROM node_access_log WHERE node_id=?", (TEST_NODE_ID,)
        ).fetchone()[0]
        check("access_log inserts (2 rows)", n_acc == 2, f"actual={n_acc}")

        # Cascade: deleting the node should drop the memory row
        cur.execute("DELETE FROM nodes WHERE id=?", (TEST_NODE_ID,))
        mem_after = cur.execute(
            "SELECT 1 FROM node_memory WHERE node_id=?", (TEST_NODE_ID,)
        ).fetchone()
        check("ON DELETE CASCADE drops node_memory", mem_after is None)

        con.commit()
    except Exception as e:
        con.rollback()
        check("round-trip + cascade", False, repr(e))
    finally:
        # Belt-and-braces cleanup
        cur.execute("DELETE FROM node_access_log WHERE node_id=?", (TEST_NODE_ID,))
        cur.execute("DELETE FROM node_memory WHERE node_id=?", (TEST_NODE_ID,))
        cur.execute("DELETE FROM nodes WHERE id=?", (TEST_NODE_ID,))
        con.commit()

    # ── 6. Confirm opt-in: no existing nodes have memory rows ──────
    print("\nOpt-in invariant")
    n_mem = cur.execute("SELECT COUNT(*) FROM node_memory").fetchone()[0]
    check("node_memory empty (per-node opt-in)", n_mem == 0, f"actual={n_mem}")

    con.close()

    # ── Summary ─────────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*48}\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
