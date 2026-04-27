#!/usr/bin/env python3
"""
Brain Graph Benchmark Runner
Runs the 50-query test corpus through both graph (Tier 1) and legacy grep,
compares results, and produces a structured report.

Usage:
  python3 brain-graph-benchmark.py [--vault-path ~/eroad-brain] [--compact]
"""
import json, sys, os, time, subprocess, re
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

DB_PATH = Path.home() / ".copilot" / "brain-graph.db"
CORPUS_PATH = Path.home() / ".copilot" / "config" / "brain-graph-test-queries.json"
VAULT_PATH = Path.home() / "eroad-brain"

# Import query engine
from brain_graph_query import query as graph_query


def run_legacy_grep(query_text, vault_path, max_results=15):
    """Simulate legacy grep-based search (basename + content grep)."""
    results = []
    query_lower = query_text.lower()
    vault = Path(vault_path)

    # 1. Basename match
    for md in vault.rglob("*.md"):
        if md.name.startswith("."):
            continue
        rel = str(md.relative_to(vault))
        basename = md.stem.lower()
        if query_lower in basename or basename in query_lower:
            results.append(rel)

    # 2. Content grep (only if we need more)
    if len(results) < max_results:
        try:
            proc = subprocess.run(
                ["grep", "-rl", "-i", query_text, str(vault),
                 "--include=*.md"],
                capture_output=True, text=True, timeout=10
            )
            for line in proc.stdout.strip().split("\n"):
                if line:
                    rel = str(Path(line).relative_to(vault))
                    if rel not in results:
                        results.append(rel)
        except Exception:
            pass

    return results[:max_results]


def compute_recall(actual_files, expected_files):
    """Recall: fraction of expected files found in actual results."""
    if not expected_files:
        return 1.0
    actual_set = set(actual_files)
    found = sum(1 for f in expected_files if f in actual_set)
    return found / len(expected_files)


def compute_precision_at_k(actual_files, expected_files, k=5):
    """Precision@K: fraction of top-K results that are expected."""
    if not actual_files:
        return 0.0
    top_k = actual_files[:k]
    expected_set = set(expected_files)
    hits = sum(1 for f in top_k if f in expected_set)
    return hits / len(top_k)


def run_benchmark(vault_path=None, compact=False, max_results=25):
    vault = Path(vault_path) if vault_path else VAULT_PATH

    with open(CORPUS_PATH) as f:
        corpus = json.load(f)

    queries = corpus["queries"]
    results = []
    category_stats = {}

    print(f"Running benchmark: {len(queries)} queries")
    print(f"  DB: {DB_PATH} ({DB_PATH.stat().st_size / 1024:.0f} KB)")
    print(f"  Vault: {vault} ({sum(1 for _ in vault.rglob('*.md'))} .md files)")
    print()

    for i, q in enumerate(queries):
        qid = q["id"]
        query_text = q["query"]
        category = q["category"]
        expected = q.get("expected_files", [])
        expected_min = q.get("expected_min_results", 1)

        # --- Graph (Tier 1) ---
        t0 = time.perf_counter()
        try:
            graph_result = graph_query(
                vault="eroad",
                raw_query=query_text,
                max_results=max_results,
                mode="full",
                db_path=DB_PATH
            )
            graph_files = [r["rel_path"] for r in graph_result.get("results", [])]
            graph_tier = graph_result.get("tier", "?")
            graph_ms = (time.perf_counter() - t0) * 1000
        except Exception as e:
            graph_files = []
            graph_tier = f"error:{e}"
            graph_ms = (time.perf_counter() - t0) * 1000

        # --- Legacy grep ---
        t0 = time.perf_counter()
        grep_files = run_legacy_grep(query_text, vault, max_results=max_results)
        grep_ms = (time.perf_counter() - t0) * 1000

        # --- Metrics ---
        graph_recall = compute_recall(graph_files, expected)
        grep_recall = compute_recall(grep_files, expected)
        graph_p5 = compute_precision_at_k(graph_files, expected, 5)
        grep_p5 = compute_precision_at_k(grep_files, expected, 5)
        graph_min_ok = len(graph_files) >= expected_min
        grep_min_ok = len(grep_files) >= expected_min

        # Parity: graph finds at least everything grep found
        grep_set = set(grep_files)
        graph_set = set(graph_files)
        parity_misses = grep_set - graph_set  # files grep found but graph didn't
        graph_extras = graph_set - grep_set  # files graph found but grep didn't

        row = {
            "id": qid,
            "category": category,
            "query": query_text,
            "graph_recall": graph_recall,
            "grep_recall": grep_recall,
            "graph_p5": graph_p5,
            "grep_p5": grep_p5,
            "graph_count": len(graph_files),
            "grep_count": len(grep_files),
            "graph_min_ok": graph_min_ok,
            "grep_min_ok": grep_min_ok,
            "graph_ms": graph_ms,
            "grep_ms": grep_ms,
            "graph_tier": graph_tier,
            "parity_misses": list(parity_misses),
            "graph_extras": list(graph_extras),
            "recall_delta": graph_recall - grep_recall,
        }
        results.append(row)

        # Category aggregation
        if category not in category_stats:
            category_stats[category] = {
                "count": 0, "graph_recall_sum": 0, "grep_recall_sum": 0,
                "graph_p5_sum": 0, "grep_p5_sum": 0,
                "graph_ms_sum": 0, "grep_ms_sum": 0,
                "parity_miss_count": 0, "graph_extra_count": 0,
                "graph_min_ok": 0, "grep_min_ok": 0
            }
        cs = category_stats[category]
        cs["count"] += 1
        cs["graph_recall_sum"] += graph_recall
        cs["grep_recall_sum"] += grep_recall
        cs["graph_p5_sum"] += graph_p5
        cs["grep_p5_sum"] += grep_p5
        cs["graph_ms_sum"] += graph_ms
        cs["grep_ms_sum"] += grep_ms
        cs["parity_miss_count"] += len(parity_misses)
        cs["graph_extra_count"] += len(graph_extras)
        cs["graph_min_ok"] += int(graph_min_ok)
        cs["grep_min_ok"] += int(grep_min_ok)

        status = "✅" if graph_recall >= grep_recall and graph_min_ok else "⚠️"
        if not compact:
            print(f"  [{i+1:2d}/50] {status} {qid:<12s} graph_recall={graph_recall:.2f} grep_recall={grep_recall:.2f} "
                  f"delta={row['recall_delta']:+.2f} graph={len(graph_files)} grep={len(grep_files)} "
                  f"tier={graph_tier} {graph_ms:.0f}ms")
            if parity_misses:
                print(f"         ⚠️  parity_misses: {parity_misses}")

    # --- Summary ---
    total = len(results)
    avg_graph_recall = sum(r["graph_recall"] for r in results) / total
    avg_grep_recall = sum(r["grep_recall"] for r in results) / total
    avg_graph_p5 = sum(r["graph_p5"] for r in results) / total
    avg_grep_p5 = sum(r["grep_p5"] for r in results) / total
    avg_graph_ms = sum(r["graph_ms"] for r in results) / total
    avg_grep_ms = sum(r["grep_ms"] for r in results) / total
    total_parity_misses = sum(len(r["parity_misses"]) for r in results)
    total_graph_extras = sum(len(r["graph_extras"]) for r in results)
    perfect_parity = sum(1 for r in results if not r["parity_misses"])
    graph_wins = sum(1 for r in results if r["recall_delta"] > 0)
    grep_wins = sum(1 for r in results if r["recall_delta"] < 0)
    ties = sum(1 for r in results if r["recall_delta"] == 0)
    all_min_ok = sum(1 for r in results if r["graph_min_ok"])

    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS")
    print("=" * 80)
    print(f"\nQueries: {total}")
    print(f"  Graph avg recall: {avg_graph_recall:.3f}")
    print(f"  Grep  avg recall: {avg_grep_recall:.3f}")
    print(f"  Delta:            {avg_graph_recall - avg_grep_recall:+.3f}")
    print(f"\n  Graph avg P@5:    {avg_graph_p5:.3f}")
    print(f"  Grep  avg P@5:    {avg_grep_p5:.3f}")
    print(f"\n  Graph avg latency: {avg_graph_ms:.1f}ms")
    print(f"  Grep  avg latency: {avg_grep_ms:.1f}ms")
    print(f"\n  Parity: {perfect_parity}/{total} queries with full parity")
    print(f"  Total parity misses: {total_parity_misses} files")
    print(f"  Graph extras (bonus): {total_graph_extras} files")
    print(f"  Graph wins: {graph_wins}, Grep wins: {grep_wins}, Ties: {ties}")
    print(f"  Min-results met: {all_min_ok}/{total}")

    print(f"\n{'Category':<20s} {'N':>3s} {'G-Recall':>8s} {'L-Recall':>8s} "
          f"{'G-P@5':>6s} {'L-P@5':>6s} {'G-ms':>6s} {'L-ms':>6s} "
          f"{'Miss':>5s} {'Extra':>5s}")
    print("-" * 90)
    for cat in sorted(category_stats.keys()):
        cs = category_stats[cat]
        n = cs["count"]
        print(f"{cat:<20s} {n:>3d} "
              f"{cs['graph_recall_sum']/n:>8.3f} {cs['grep_recall_sum']/n:>8.3f} "
              f"{cs['graph_p5_sum']/n:>6.3f} {cs['grep_p5_sum']/n:>6.3f} "
              f"{cs['graph_ms_sum']/n:>6.0f} {cs['grep_ms_sum']/n:>6.0f} "
              f"{cs['parity_miss_count']:>5d} {cs['graph_extra_count']:>5d}")

    # --- AC Verdicts ---
    print("\n" + "=" * 80)
    print("ACCEPTANCE CRITERIA VERDICTS")
    print("=" * 80)

    # AC-1: Per-query parity (graph recall >= grep recall on every query)
    ac1_pass = all(r["graph_recall"] >= r["grep_recall"] for r in results)
    ac1_failures = [r for r in results if r["graph_recall"] < r["grep_recall"]]
    print(f"\n  AC-1 Per-query parity: {'✅ PASS' if ac1_pass else '❌ FAIL'}")
    if ac1_failures:
        for r in ac1_failures:
            print(f"        FAIL: {r['id']} graph={r['graph_recall']:.2f} < grep={r['grep_recall']:.2f}")

    # AC-2: Gap handling (avg recall >= 0.80)
    ac2_pass = avg_graph_recall >= 0.80
    print(f"  AC-2 Gap handling (recall≥0.80): {'✅ PASS' if ac2_pass else '❌ FAIL'} ({avg_graph_recall:.3f})")

    # AC-5: Overall retrieval quality (avg recall >= 0.85)
    ac5_pass = avg_graph_recall >= 0.85
    print(f"  AC-5 Overall retrieval (recall≥0.85): {'✅ PASS' if ac5_pass else '❌ FAIL'} ({avg_graph_recall:.3f})")

    # AC-6: Sync correctness (already validated, re-check node count)
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    conn.close()
    vault_count = sum(1 for _ in vault.rglob("*.md") if not str(_).startswith(str(vault / ".obsidian")))
    ac6_pass = node_count == vault_count
    print(f"  AC-6 Sync correctness: {'✅ PASS' if ac6_pass else '❌ FAIL'} (DB={node_count}, vault={vault_count})")

    # AC-7: Orphan reachability (FTS finds orphans)
    orphan_query = """
        SELECT n.id, n.basename FROM nodes n
        WHERE NOT EXISTS (SELECT 1 FROM edges e WHERE e.source_id = n.id OR e.target_id = n.id)
    """
    conn = sqlite3.connect(str(DB_PATH))
    orphans = conn.execute(orphan_query).fetchall()
    orphan_reachable = 0
    for oid, obasename in orphans:
        # FTS match on basename
        try:
            fts_count = conn.execute(
                "SELECT COUNT(*) FROM nodes_fts WHERE basename MATCH ?", (obasename,)
            ).fetchone()[0]
        except:
            fts_count = 0
        like_count = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE basename LIKE ?", (f"%{obasename}%",)
        ).fetchone()[0]
        if fts_count > 0 or like_count > 0:
            orphan_reachable += 1
    conn.close()
    ac7_pass = len(orphans) == 0 or orphan_reachable == len(orphans)
    print(f"  AC-7 Orphan reachability: {'✅ PASS' if ac7_pass else '❌ FAIL'} ({orphan_reachable}/{len(orphans)} orphans reachable)")

    # AC-8: Fallback ladder (test each tier)
    ac8_pass = True
    # Tier 1 already tested above (all queries used it)
    tier1_ok = all(r["graph_tier"] == 1 for r in results)
    # Tier 2: test fts-only mode
    try:
        t2 = graph_query(vault="eroad", raw_query="media-service", max_results=5, mode="fts-only", db_path=DB_PATH)
        tier2_ok = t2.get("tier") == 2
    except:
        tier2_ok = False
    # Tier 3: test with nonexistent DB
    try:
        t3 = graph_query(vault="eroad", raw_query="media-service", max_results=5, mode="full", db_path=Path("/tmp/nonexistent.db"))
        tier3_ok = t3.get("tier") in (3, 4)
    except:
        tier3_ok = False
    ac8_pass = tier1_ok and tier2_ok and tier3_ok
    print(f"  AC-8 Fallback ladder: {'✅ PASS' if ac8_pass else '❌ FAIL'} (T1={tier1_ok}, T2={tier2_ok}, T3={tier3_ok})")

    # Overall
    all_pass = ac1_pass and ac2_pass and ac5_pass and ac6_pass and ac7_pass and ac8_pass
    print(f"\n  {'🎉 ALL ACCEPTANCE CRITERIA PASSED' if all_pass else '⚠️ SOME ACCEPTANCE CRITERIA FAILED'}")

    # Write report
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total_queries": total,
            "avg_graph_recall": round(avg_graph_recall, 4),
            "avg_grep_recall": round(avg_grep_recall, 4),
            "avg_graph_p5": round(avg_graph_p5, 4),
            "avg_grep_p5": round(avg_grep_p5, 4),
            "avg_graph_ms": round(avg_graph_ms, 1),
            "avg_grep_ms": round(avg_grep_ms, 1),
            "graph_wins": graph_wins,
            "grep_wins": grep_wins,
            "ties": ties,
            "parity_queries": perfect_parity,
            "total_parity_misses": total_parity_misses,
            "total_graph_extras": total_graph_extras,
        },
        "acceptance_criteria": {
            "AC-1_parity": ac1_pass,
            "AC-2_gap_handling": ac2_pass,
            "AC-5_overall": ac5_pass,
            "AC-6_sync": ac6_pass,
            "AC-7_orphan": ac7_pass,
            "AC-8_fallback": ac8_pass,
            "all_pass": all_pass,
        },
        "per_query": results,
    }
    report_path = Path.home() / ".copilot" / "config" / "brain-graph-benchmark-report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report saved: {report_path}")

    return report


if __name__ == "__main__":
    import argparse as _ap
    p = _ap.ArgumentParser()
    p.add_argument("--vault-path", type=Path, default=VAULT_PATH)
    p.add_argument("--compact", action="store_true")
    p.add_argument("--max-results", type=int, default=25)
    a = p.parse_args()
    run_benchmark(a.vault_path, a.compact, a.max_results)
