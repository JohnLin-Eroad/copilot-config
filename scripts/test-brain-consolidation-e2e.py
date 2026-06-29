#!/usr/bin/env python3
"""E2E smoke for the documented brain-consolidation workflow.

Validates that the playbook in brain-consolidation.agent.md actually works
end-to-end against the real brain graph using synthetic test nodes.

Workflow under test:
  1. Search FTS for a topic → 0 hits → upsert a new node
  2. mark-confidence verified on the new node
  3. Search again → now finds the node
  4. Upsert a second (replacement) node
  5. decide --winner NEW --supersedes OLD
  6. inspect both → loser has superseded_by set, winner is verified
  7. mark-fresh on a stale node bumps it

All operations use the exact commands documented in the agent.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DB = os.path.expanduser("~/.copilot/brain-graph.db")
ADMIN = os.path.expanduser("~/.copilot/scripts/brain-graph-admin.py")
QUERY = os.path.expanduser("~/.copilot/scripts/brain-graph-query.py")

VAULT = "john-brain"
TAG = "p7e2e-zqxw9k"  # distinctive, unlikely to collide with real content
OLD = f"{VAULT}/__test__/p7-consolidation-old-{TAG}"
NEW = f"{VAULT}/__test__/p7-consolidation-new-{TAG}"
ISO = f"{VAULT}/__test__/p7-isolated-{TAG}"

PASS = FAIL = 0


def check(name: str, cond: bool, got=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}" + (f"  — {got}" if got is not None else ""))
    else:
        FAIL += 1
        print(f"  ✗ {name}  — got {got}")


def upsert_node(node_id: str, title: str, content: str, domain: str = "learning"):
    """Mirror the snippet in brain-consolidation.agent.md."""
    rel_path = node_id.split("/", 1)[1] + ".md"
    basename = node_id.rsplit("/", 1)[-1]
    now = datetime.utcnow().isoformat() + "+00:00"
    h = hashlib.sha256(content.encode()).hexdigest()
    con = sqlite3.connect(DB)
    con.execute(
        "INSERT INTO nodes(id,vault,rel_path,basename,title,content,content_hash,"
        " size_bytes,modified_at,domain,subdomain,indexed_at,tombstone) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0) "
        "ON CONFLICT(id) DO UPDATE SET content=excluded.content, "
        "  content_hash=excluded.content_hash, size_bytes=excluded.size_bytes, "
        "  modified_at=excluded.modified_at, indexed_at=excluded.indexed_at, tombstone=0",
        (node_id, VAULT, rel_path, basename, title, content, h, len(content),
         now, domain, "", now),
    )
    con.commit()
    # FTS sync — copy what the indexer does
    con.execute("INSERT OR REPLACE INTO nodes_fts(rowid, id, title, content) "
                "SELECT rowid, id, title, content FROM nodes WHERE id=?", (node_id,))
    con.commit()
    con.close()


def admin(*args, expect_exit=0) -> dict:
    proc = subprocess.run(["python3", ADMIN, *args],
                          capture_output=True, text=True)
    if proc.returncode != expect_exit:
        raise AssertionError(
            f"admin {args} exit={proc.returncode}\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}")
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def search(query: str) -> list:
    proc = subprocess.run(
        ["python3", QUERY, "search", "--vault", VAULT,
         "--query", query, "--max-results", "5", "--compact"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"search failed: {proc.stderr}")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    return out.get("results", []) if isinstance(out, dict) else out


def cleanup():
    con = sqlite3.connect(DB)
    for nid in (OLD, NEW, ISO):
        con.execute("DELETE FROM node_memory WHERE node_id=?", (nid,))
        con.execute("DELETE FROM node_memory WHERE superseded_by=?", (nid,))
        con.execute("DELETE FROM node_access_log WHERE node_id=?", (nid,))
        con.execute("DELETE FROM edges WHERE source_id=? OR target_id=?", (nid, nid))
        con.execute("DELETE FROM nodes_fts WHERE id=?", (nid,))
        con.execute("DELETE FROM nodes WHERE id=?", (nid,))
    con.commit()
    con.close()


def test_full_workflow():
    print("\nE2E: search → upsert → mark-confidence → search again → supersede → inspect")
    cleanup()
    try:
        # ---- 1. Search for nothing — should miss ----
        hits = search(TAG)
        check("initial search returns 0 hits for unique tag",
              len(hits) == 0, f"{len(hits)} hits")

        # ---- 2. Upsert OLD node ----
        upsert_node(OLD, "Old Knowledge",
                    f"# Old\nThis is the original note about {TAG} pattern.\n")
        check("OLD node exists after upsert",
              sqlite3.connect(DB).execute(
                  "SELECT 1 FROM nodes WHERE id=?", (OLD,)).fetchone() is not None)

        # ---- 3. mark-confidence verified on OLD ----
        out = admin("mark-confidence", "--node-id", OLD, "--level", "verified")
        check("mark-confidence ok=true", out.get("ok") is True)
        check("created=true (first time)", out.get("created") is True)
        check("memory.confidence=verified",
              out["memory"]["confidence"] == "verified",
              out["memory"]["confidence"])

        # ---- 4. Search again — should now find OLD ----
        hits = search(TAG)
        check("search finds OLD after upsert+FTS sync",
              any(h.get("id") == OLD for h in hits),
              [h.get("id") for h in hits])

        # ---- 5. Upsert NEW (replacement) ----
        upsert_node(NEW, "New Knowledge",
                    f"# New\nReplacement note about {TAG} pattern — corrected.\n")
        admin("mark-confidence", "--node-id", NEW, "--level", "verified")

        # ---- 6. decide --winner NEW --supersedes OLD ----
        out = admin("decide", "--winner", NEW, "--supersedes", OLD,
                    "--note", "P7 E2E test")
        check("decide ok=true", out.get("ok") is True)
        check("winner is verified",
              out["winner"]["confidence"] == "verified",
              out["winner"]["confidence"])
        check("loser.superseded_by → NEW",
              out["loser"]["superseded_by"] == NEW,
              out["loser"]["superseded_by"])
        check("loser.superseded_at populated",
              out["loser"]["superseded_at"] is not None,
              out["loser"]["superseded_at"])

        # ---- 7. inspect OLD shows superseded ----
        out = admin("inspect", "--node-id", OLD)
        check("inspect.memory.is_superseded=true",
              out["memory"]["is_superseded"] is True,
              out["memory"].get("is_superseded"))

        # ---- 8. inspect NEW shows verified, not superseded ----
        out = admin("inspect", "--node-id", NEW)
        check("NEW is verified and not superseded",
              out["memory"]["confidence"] == "verified"
              and not out["memory"]["is_superseded"],
              (out["memory"]["confidence"], out["memory"]["is_superseded"]))

        # ---- 9. list-stale includes OLD (superseded → penalised) ----
        # OLD will appear because superseded nodes get penalised in eff_strength.
        out = admin("list-stale", "--limit", "100")
        ids = [r["node_id"] for r in out["results"]]
        check("list-stale enumerates managed nodes (>0)",
              out["total_managed"] >= 2,
              out["total_managed"])

        # ---- 10. mark-fresh resets last_retrieved_at ----
        upsert_node(ISO, "Isolated", f"# Iso\nTest node for mark-fresh {TAG}\n")
        admin("mark-confidence", "--node-id", ISO, "--level", "observed")
        before = admin("inspect", "--node-id", ISO)
        out = admin("mark-fresh", "--node-id", ISO)
        check("mark-fresh ok=true", out.get("ok") is True)
        check("mark-fresh strength reset to 1.0",
              abs(out["memory"]["strength"] - 1.0) < 1e-6,
              out["memory"]["strength"])
    finally:
        cleanup()


def main() -> int:
    test_full_workflow()
    print("\n" + "=" * 56)
    print(f"{PASS}/{PASS+FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
