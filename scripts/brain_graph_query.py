#!/usr/bin/env python3
"""
brain-graph-query.py — Graph-augmented retrieval for the brain index.

Architecture: FTS search (primary) → graph re-rank (Jaccard) → 1-hop expand → merge → deliver
4-tier fallback: full pipeline → FTS-only → legacy grep → empty+error

Usage:
  python3 brain-graph-query.py --vault eroad --query "media-service SQS events"
  python3 brain-graph-query.py --vault eroad --query "auth patterns" --max-results 20
  python3 brain-graph-query.py --vault eroad --query "RUCUS compliance" --mode fts-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB = Path.home() / ".copilot" / "brain-graph.db"
FLAGS_PATH = Path.home() / ".copilot" / "config" / "feature-flags.json"
BM25_LOW_CONFIDENCE_THRESHOLD = 2.0
LOW_CONFIDENCE_MIN_HITS = 3
GRAPH_BONUS_CAP = 0.5
MAX_EXPAND_SOURCES = 5
MAX_EXPAND_NEIGHBORS = 10


# ---------------------------------------------------------------------------
# Query rewriting — handles hyphens, paths, acronyms
# ---------------------------------------------------------------------------

def rewrite_query(raw_query: str) -> dict:
    """Rewrite raw query for FTS5 and LIKE fallbacks."""
    tokens = raw_query.split()
    fts_parts = []
    like_fallbacks = []
    basename_terms = []

    for token in tokens:
        if "-" in token or "/" in token:
            # Hyphenated/path: phrase query + LIKE fallback + basename search
            clean = token.replace("-", " ").replace("/", " ")
            fts_parts.append(f'"{clean}"')
            like_fallbacks.append(token)
            basename_terms.append(token)
        elif token.isupper() and len(token) <= 6:
            # Acronym: exact match (skip stemmer)
            fts_parts.append(f'"{token}"')
        else:
            fts_parts.append(token)

    return {
        "fts_query": " ".join(fts_parts),
        "like_fallbacks": list(set(like_fallbacks + [raw_query])),  # always include raw query
        "basename_terms": basename_terms,
        "original": raw_query,
    }


# ---------------------------------------------------------------------------
# Graph loading (NetworkX)
# ---------------------------------------------------------------------------

def load_graph(conn: sqlite3.Connection) -> nx.DiGraph | None:
    """Load edge table into NetworkX DiGraph."""
    if not HAS_NETWORKX:
        return None
    G = nx.DiGraph()
    for src, tgt, etype, weight in conn.execute(
        "SELECT source_id, target_id, edge_type, weight FROM edges"
    ):
        G.add_edge(src, tgt, edge_type=etype, weight=weight)
    # Also add nodes with no edges
    for (nid,) in conn.execute("SELECT id FROM nodes WHERE tombstone = 0"):
        if nid not in G:
            G.add_node(nid)
    return G


def get_hub_threshold(conn: sqlite3.Connection) -> int:
    """Read adaptive hub threshold from sync_meta."""
    row = conn.execute("SELECT value FROM sync_meta WHERE key = 'hub_threshold'").fetchone()
    return int(row[0]) if row else 10


# ---------------------------------------------------------------------------
# Tier 1: Full pipeline — FTS + graph rerank + 1-hop expand + gap analysis
# ---------------------------------------------------------------------------

def fts_search(conn: sqlite3.Connection, vault: str, rewritten: dict, max_results: int) -> list[dict]:
    """Run FTS5 search and return ranked hits with BM25 scores."""
    fts_query = rewritten["fts_query"]
    hits = []

    if fts_query.strip():
        try:
            rows = conn.execute("""
                SELECT n.id, n.rel_path, n.title, n.basename, n.domain, n.subdomain,
                       bm25(nodes_fts, 0, 5, 10, 1) as score
                FROM nodes_fts
                JOIN nodes n ON n.id = nodes_fts.id
                WHERE nodes_fts MATCH ?
                  AND n.vault = ?
                  AND n.tombstone = 0
                ORDER BY score ASC
                LIMIT ?
            """, (fts_query, vault, max_results * 8)).fetchall()

            for r in rows:
                hits.append({
                    "id": r[0], "rel_path": r[1], "title": r[2], "basename": r[3],
                    "domain": r[4], "subdomain": r[5],
                    "bm25_score": abs(r[6]),  # bm25() returns negative; lower = better
                    "graph_bonus": 0.0, "combined_score": abs(r[6]),
                    "source": "fts",
                })
        except sqlite3.OperationalError:
            # FTS query syntax error — fall through to LIKE
            pass

    # LIKE fallback for hyphenated terms that FTS may tokenize wrong
    seen_ids = {h["id"] for h in hits}
    for term in rewritten.get("like_fallbacks", []):
        like_rows = conn.execute("""
            SELECT id, rel_path, title, basename, domain, subdomain
            FROM nodes
            WHERE vault = ? AND tombstone = 0
              AND (basename LIKE ? OR content LIKE ?)
            LIMIT ?
        """, (vault, f"%{term}%", f"%{term}%", max_results * 3)).fetchall()

        for r in like_rows:
            if r[0] not in seen_ids:
                seen_ids.add(r[0])
                hits.append({
                    "id": r[0], "rel_path": r[1], "title": r[2], "basename": r[3],
                    "domain": r[4], "subdomain": r[5],
                    "bm25_score": 1.0,  # low synthetic score for LIKE hits
                    "graph_bonus": 0.0, "combined_score": 1.0,
                    "source": "like_fallback",
                })

    # Basename exact match boost — push direct name matches to top
    for term in rewritten.get("basename_terms", []):
        bn_rows = conn.execute("""
            SELECT id, rel_path, title, basename, domain, subdomain
            FROM nodes
            WHERE vault = ? AND tombstone = 0 AND LOWER(basename) = LOWER(?)
        """, (vault, term)).fetchall()

        for r in bn_rows:
            if r[0] not in seen_ids:
                seen_ids.add(r[0])
                hits.append({
                    "id": r[0], "rel_path": r[1], "title": r[2], "basename": r[3],
                    "domain": r[4], "subdomain": r[5],
                    "bm25_score": 20.0,  # high score for exact basename match
                    "graph_bonus": 0.0, "combined_score": 20.0,
                    "source": "basename_match",
                })
            else:
                # Boost existing hit
                for h in hits:
                    if h["id"] == r[0]:
                        h["bm25_score"] = max(h["bm25_score"], 20.0)
                        h["combined_score"] = max(h["combined_score"], 20.0)
                        h["source"] = "basename_match"
                        break

    return hits


def graph_rerank(hits: list[dict], G: nx.DiGraph) -> list[dict]:
    """Jaccard-normalized graph reranking, bonus capped at 0.5."""
    if not G or not hits:
        return hits

    hit_ids = {h["id"] for h in hits}

    for hit in hits:
        nid = hit["id"]
        if nid not in G:
            hit["graph_bonus"] = 0.0
            continue

        neighbors = set(G.predecessors(nid)) | set(G.successors(nid))
        if not neighbors:
            hit["graph_bonus"] = 0.0
            continue

        overlap = neighbors & hit_ids
        union = neighbors | hit_ids
        jaccard = len(overlap) / len(union) if union else 0.0
        hit["graph_bonus"] = min(jaccard * GRAPH_BONUS_CAP, GRAPH_BONUS_CAP)
        hit["combined_score"] = hit["bm25_score"] + hit["graph_bonus"]

    return sorted(hits, key=lambda h: h["combined_score"], reverse=True)


def expand_neighbors(
    hits: list[dict],
    G: nx.DiGraph,
    hub_threshold: int,
    max_results: int,
    conn: sqlite3.Connection,
    vault: str,
) -> list[dict]:
    """1-hop expansion from top hits. Returns new nodes not already in hits."""
    if not G or not hits:
        return []

    hit_ids = {h["id"] for h in hits}
    expanded = []
    seen = set(hit_ids)

    # Expand from top N hits
    for hit in hits[:MAX_EXPAND_SOURCES]:
        nid = hit["id"]
        if nid not in G:
            continue

        # Get all neighbors (both directions)
        neighbors = list(set(G.predecessors(nid)) | set(G.successors(nid)))
        # Filter out hubs and already-seen
        neighbors = [
            n for n in neighbors
            if n not in seen and G.in_degree(n) <= hub_threshold
        ]
        # Sort by edge weight (prefer wiki_link over folder_sibling)
        def edge_weight(n):
            w = 0.0
            if G.has_edge(nid, n):
                w = max(w, G[nid][n].get("weight", 0.0))
            if G.has_edge(n, nid):
                w = max(w, G[n][nid].get("weight", 0.0))
            return w
        neighbors.sort(key=edge_weight, reverse=True)

        for n in neighbors[:MAX_EXPAND_NEIGHBORS]:
            if n in seen:
                continue
            seen.add(n)
            # Fetch node metadata
            row = conn.execute("""
                SELECT id, rel_path, title, basename, domain, subdomain
                FROM nodes WHERE id = ? AND vault = ? AND tombstone = 0
            """, (n, vault)).fetchone()
            if row:
                expanded.append({
                    "id": row[0], "rel_path": row[1], "title": row[2], "basename": row[3],
                    "domain": row[4], "subdomain": row[5],
                    "bm25_score": 0.0, "graph_bonus": 0.0, "combined_score": 0.0,
                    "source": "graph_expand",
                })

        if len(expanded) >= max_results:
            break

    return expanded[:max_results]


def gap_analysis(conn: sqlite3.Connection, vault: str, hits: list[dict]) -> dict:
    """Per-domain gap analysis: how many nodes exist vs how many were hit."""
    # Get domain totals
    domain_totals = {}
    for domain, count in conn.execute(
        "SELECT domain, COUNT(*) FROM nodes WHERE vault = ? AND tombstone = 0 GROUP BY domain",
        (vault,)
    ):
        domain_totals[domain] = count

    # Count hits per domain
    domain_hits = defaultdict(int)
    for h in hits:
        if h.get("domain"):
            domain_hits[h["domain"]] += 1

    gaps = {}
    for domain, total in domain_totals.items():
        hit_count = domain_hits.get(domain, 0)
        entry = {"total": total, "hits": hit_count}
        if hit_count == 0:
            entry["negative_context"] = f"No {domain} docs matched query"
        gaps[domain] = entry

    return gaps


def tier1_query(
    conn: sqlite3.Connection,
    vault: str,
    raw_query: str,
    max_results: int,
    manifest: set[str] | None = None,
) -> dict:
    """Full pipeline: FTS + graph rerank + expand + gap analysis."""
    rewritten = rewrite_query(raw_query)

    # FTS search
    hits = fts_search(conn, vault, rewritten, max_results)

    # Load graph + rerank
    G = load_graph(conn)
    hub_threshold = get_hub_threshold(conn)

    if G:
        hits = graph_rerank(hits, G)

    # 1-hop expansion
    expand_budget = max(max_results - len(hits), 5)
    expanded = expand_neighbors(hits, G, hub_threshold, expand_budget, conn, vault)

    # Merge
    all_results = hits + expanded

    # Deduplicate against manifest
    if manifest:
        all_results = [r for r in all_results if r["id"] not in manifest]

    # Trim to max
    all_results = all_results[:max_results]

    # Low confidence check
    high_score_count = sum(1 for h in hits if h["bm25_score"] >= BM25_LOW_CONFIDENCE_THRESHOLD)
    low_confidence = high_score_count < LOW_CONFIDENCE_MIN_HITS

    # Gap analysis
    gaps = gap_analysis(conn, vault, all_results)

    return {
        "results": all_results,
        "gap_analysis": gaps,
        "low_confidence": low_confidence,
        "tier": 1,
        "degraded": False,
        "query_rewritten": rewritten["fts_query"],
        "result_count": len(all_results),
        "fts_hits": len(hits),
        "graph_expanded": len(expanded),
    }


# ---------------------------------------------------------------------------
# Tier 2: FTS-only (no graph)
# ---------------------------------------------------------------------------

def tier2_query(
    conn: sqlite3.Connection,
    vault: str,
    raw_query: str,
    max_results: int,
    manifest: set[str] | None = None,
) -> dict:
    """FTS-only fallback — no graph, no expansion."""
    rewritten = rewrite_query(raw_query)
    hits = fts_search(conn, vault, rewritten, max_results)

    if manifest:
        hits = [r for r in hits if r["id"] not in manifest]

    hits = hits[:max_results]
    high_score_count = sum(1 for h in hits if h["bm25_score"] >= BM25_LOW_CONFIDENCE_THRESHOLD)

    return {
        "results": hits,
        "gap_analysis": {},
        "low_confidence": high_score_count < LOW_CONFIDENCE_MIN_HITS,
        "tier": 2,
        "degraded": True,
        "query_rewritten": rewritten["fts_query"],
        "result_count": len(hits),
        "fts_hits": len(hits),
        "graph_expanded": 0,
    }


# ---------------------------------------------------------------------------
# Tier 3: Legacy grep fallback (no DB at all)
# ---------------------------------------------------------------------------

def tier3_query(
    vault: str,
    raw_query: str,
    max_results: int,
) -> dict:
    """Legacy grep fallback — searches vault directly."""
    vault_paths = {
        "eroad": Path.home() / "eroad-brain",
        "john": Path.home() / "john-brain",
    }
    vault_path = vault_paths.get(vault)
    if not vault_path or not vault_path.is_dir():
        return tier4_error(f"Vault path not found for '{vault}'")

    results = []
    terms = raw_query.split()

    for term in terms[:3]:  # limit to avoid slow grep
        try:
            proc = subprocess.run(
                ["grep", "-ril", "--include=*.md", term, str(vault_path)],
                capture_output=True, text=True, timeout=10,
            )
            for line in proc.stdout.strip().splitlines():
                fp = Path(line)
                rel = str(fp.relative_to(vault_path))
                rid = f"{vault}/{rel[:-3]}" if rel.endswith(".md") else f"{vault}/{rel}"
                if rid not in {r["id"] for r in results}:
                    results.append({
                        "id": rid, "rel_path": rel,
                        "title": fp.stem, "basename": fp.stem,
                        "domain": None, "subdomain": None,
                        "bm25_score": 0.0, "graph_bonus": 0.0, "combined_score": 0.0,
                        "source": "grep_fallback",
                    })
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    return {
        "results": results[:max_results],
        "gap_analysis": {},
        "low_confidence": True,
        "tier": 3,
        "degraded": True,
        "query_rewritten": raw_query,
        "result_count": len(results[:max_results]),
        "fts_hits": 0,
        "graph_expanded": 0,
    }


# ---------------------------------------------------------------------------
# Tier 4: Empty result with error signal
# ---------------------------------------------------------------------------

def tier4_error(error_msg: str) -> dict:
    """Terminal fallback — return empty with error."""
    return {
        "results": [],
        "gap_analysis": {},
        "low_confidence": True,
        "tier": 4,
        "degraded": True,
        "error": error_msg,
        "query_rewritten": "",
        "result_count": 0,
        "fts_hits": 0,
        "graph_expanded": 0,
    }


# ---------------------------------------------------------------------------
# Main query dispatcher with fallback ladder
# ---------------------------------------------------------------------------

def query(
    vault: str,
    raw_query: str,
    max_results: int = 15,
    manifest: set[str] | None = None,
    mode: str = "full",
    db_path: Path = DEFAULT_DB,
) -> dict:
    """Execute query with 4-tier fallback ladder.

    Args:
        vault: Vault name (eroad/john)
        raw_query: Search query
        max_results: Max results to return
        manifest: Set of node IDs already fetched (to deduplicate)
        mode: 'full' (Tier 1), 'fts-only' (Tier 2), 'grep' (Tier 3)
        db_path: Path to SQLite database
    """
    # Check mode override
    if mode == "grep":
        return tier3_query(vault, raw_query, max_results)

    # Try to open DB
    if not db_path.exists():
        print(f"  WARN: DB not found at {db_path}, falling to Tier 3", file=sys.stderr)
        return tier3_query(vault, raw_query, max_results)

    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode = WAL")
    except Exception as e:
        print(f"  WARN: DB open failed: {e}, falling to Tier 3", file=sys.stderr)
        return tier3_query(vault, raw_query, max_results)

    try:
        if mode == "fts-only":
            return tier2_query(conn, vault, raw_query, max_results, manifest)

        # Tier 1: Full pipeline
        try:
            return tier1_query(conn, vault, raw_query, max_results, manifest)
        except Exception as e:
            print(f"  WARN: Tier 1 failed: {e}, falling to Tier 2", file=sys.stderr)

        # Tier 2: FTS-only
        try:
            return tier2_query(conn, vault, raw_query, max_results, manifest)
        except Exception as e:
            print(f"  WARN: Tier 2 failed: {e}, falling to Tier 3", file=sys.stderr)

        # Tier 3: Grep
        return tier3_query(vault, raw_query, max_results)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Content fetcher — retrieve full content for result nodes
# ---------------------------------------------------------------------------

def fetch_content(result_ids: list[str], db_path: Path = DEFAULT_DB) -> dict[str, str]:
    """Fetch full markdown content for a list of node IDs."""
    if not result_ids or not db_path.exists():
        return {}

    conn = sqlite3.connect(str(db_path))
    try:
        placeholders = ",".join("?" for _ in result_ids)
        rows = conn.execute(
            f"SELECT id, content FROM nodes WHERE id IN ({placeholders})",
            result_ids,
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Brain graph query engine")
    parser.add_argument("--vault", required=True, help="Vault name (eroad/john)")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--max-results", type=int, default=15, help="Max results (default: 15)")
    parser.add_argument("--mode", choices=["full", "fts-only", "grep"], default="full")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--manifest", help="Comma-separated node IDs already fetched")
    parser.add_argument("--fetch-content", action="store_true", help="Include full content in results")
    parser.add_argument("--compact", action="store_true", help="Compact JSON output (no indent)")
    args = parser.parse_args()

    manifest = set(args.manifest.split(",")) if args.manifest else None

    t0 = time.monotonic()
    result = query(
        vault=args.vault,
        raw_query=args.query,
        max_results=args.max_results,
        manifest=manifest,
        mode=args.mode,
        db_path=args.db_path,
    )
    elapsed = time.monotonic() - t0
    result["elapsed_ms"] = round(elapsed * 1000, 1)

    # Optionally fetch content
    if args.fetch_content and result["results"]:
        content_map = fetch_content([r["id"] for r in result["results"]], args.db_path)
        for r in result["results"]:
            r["content"] = content_map.get(r["id"], "")

    indent = None if args.compact else 2
    print(json.dumps(result, indent=indent))


if __name__ == "__main__":
    main()
