#!/usr/bin/env python3
"""
brain-graph-query.py — Graph-augmented retrieval for the brain index.

Architecture: Dual-search (FTS + LIKE) → graph re-rank → 1-hop BFS expand → deliver
4-tier fallback: full pipeline → FTS-only → legacy grep → empty+error

Design principles:
  1. Recall-first: LIKE search guarantees coverage parity with grep
  2. FTS for ranking: BM25 provides relevance ordering
  3. Graph for discovery: 1-hop BFS expansion finds structurally related docs
  4. Overfetch over underfetch: default 25 results

Usage:
  python3 brain-graph-query.py --vault eroad --query "media-service SQS events"
  python3 brain-graph-query.py --vault eroad --query "auth patterns" --max-results 30
  python3 brain-graph-query.py --vault eroad --query "RUCUS compliance" --mode fts-only
"""

from __future__ import annotations

import argparse
import json
import math
import os
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
DEFAULT_MAX_RESULTS = 25
BM25_LOW_CONFIDENCE_THRESHOLD = 2.0
LOW_CONFIDENCE_MIN_HITS = 3
GRAPH_BONUS_CAP = 0.5
MAX_EXPAND_SOURCES = 7
MAX_EXPAND_NEIGHBORS = 10
FTS_WINDOW_MULTIPLIER = 8


# ---------------------------------------------------------------------------
# Query rewriting — simple 3-case handler
# ---------------------------------------------------------------------------

def rewrite_query(raw_query: str) -> dict:
    """Rewrite raw query for FTS5 + LIKE dual search.

    Three cases:
      1. Path queries ('Brain/Departments/...') → path prefix + last-segment FTS
      2. Hyphenated terms ('media-service') → phrase FTS + basename search
      3. Everything else → pass through + multi-word phrase
    """
    tokens = raw_query.split()
    fts_parts = []
    like_terms = [raw_query]  # always LIKE the raw query
    basename_terms = []
    path_prefix = None

    # Case 1: Path query (≥3 slash-separated segments)
    if "/" in raw_query and len(raw_query.split("/")) >= 3:
        path_prefix = raw_query.rstrip("/")
        last_seg = path_prefix.split("/")[-1]
        if last_seg:
            fts_parts.append(f'"{last_seg}"')
            like_terms.append(last_seg)
    else:
        # Case 2 & 3: token-level processing
        for token in tokens:
            if "-" in token:
                # Hyphenated: phrase query in FTS + exact LIKE + basename
                fts_parts.append(f'"{token.replace("-", " ")}"')
                like_terms.append(token)
                basename_terms.append(token)
            elif token.isupper() and len(token) <= 6:
                # Acronym: exact match
                fts_parts.append(f'"{token}"')
            else:
                fts_parts.append(token)

        # Multi-word: also search as exact phrase
        if len(tokens) >= 2:
            fts_parts.append(f'"{raw_query}"')

    return {
        "fts_query": " ".join(fts_parts),
        "like_terms": list(set(like_terms)),
        "basename_terms": basename_terms,
        "path_prefix": path_prefix,
        "original": raw_query,
    }


# ---------------------------------------------------------------------------
# Graph loading (NetworkX)
# ---------------------------------------------------------------------------

_graph_cache: tuple[nx.DiGraph | None, float] = (None, 0.0)

def load_graph(conn: sqlite3.Connection) -> nx.DiGraph | None:
    """Load edge table into NetworkX DiGraph. Cached for 60s."""
    global _graph_cache
    if not HAS_NETWORKX:
        return None

    now = time.monotonic()
    if _graph_cache[0] is not None and (now - _graph_cache[1]) < 60:
        return _graph_cache[0]

    G = nx.DiGraph()
    for src, tgt, etype, weight in conn.execute(
        "SELECT source_id, target_id, edge_type, weight FROM edges"
    ):
        G.add_edge(src, tgt, edge_type=etype, weight=weight)
    for (nid,) in conn.execute("SELECT id FROM nodes WHERE tombstone = 0"):
        if nid not in G:
            G.add_node(nid)

    _graph_cache = (G, now)
    return G


def get_hub_threshold(conn: sqlite3.Connection) -> int:
    """Read adaptive hub threshold from sync_meta."""
    row = conn.execute("SELECT value FROM sync_meta WHERE key = 'hub_threshold'").fetchone()
    return int(row[0]) if row else 200


# ---------------------------------------------------------------------------
# Dual search: FTS (ranking) + LIKE (coverage guarantee)
# ---------------------------------------------------------------------------

def dual_search(
    conn: sqlite3.Connection,
    vault: str,
    rewritten: dict,
    max_results: int,
) -> list[dict]:
    """Run FTS for ranking, then LIKE for coverage guarantee.

    Pass 1: FTS5 BM25 search (provides relevance ranking)
    Pass 2: LIKE search for all query terms (catches what FTS misses)
    Pass 3: Path prefix search (for path-like queries)
    Pass 4: Basename exact match boost
    """
    hits = []
    seen_ids: set[str] = set()
    fts_query = rewritten["fts_query"]

    # ----- Pass 1: FTS search -----
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
            """, (fts_query, vault, max_results * FTS_WINDOW_MULTIPLIER)).fetchall()

            for r in rows:
                seen_ids.add(r[0])
                hits.append({
                    "id": r[0], "rel_path": r[1], "title": r[2], "basename": r[3],
                    "domain": r[4], "subdomain": r[5],
                    "bm25_score": abs(r[6]),
                    "graph_bonus": 0.0, "combined_score": abs(r[6]),
                    "source": "fts",
                })
        except sqlite3.OperationalError:
            pass  # FTS syntax error — rely on LIKE pass

    # ----- Pass 2: LIKE search (coverage guarantee) -----
    # This ensures we find everything grep would find
    like_search_terms = list(rewritten["like_terms"])
    # For multi-word queries, also search individual words — but only specific ones
    STOP_WORDS = {
        "service", "services", "the", "and", "for", "from", "with", "that",
        "this", "are", "was", "were", "been", "being", "have", "has", "had",
        "does", "did", "will", "would", "could", "should", "may", "might",
        "shall", "can", "need", "must", "data", "type", "name", "file",
        "code", "test", "tests", "testing", "used", "using", "uses",
        "into", "over", "under", "between", "through", "about", "each",
        "which", "their", "there", "when", "where", "what", "some", "more",
        "other", "also", "than", "then", "them", "these", "those", "only",
        "very", "just", "like", "make", "made", "many", "much", "most",
        "such", "well", "back", "even", "still", "after", "before",
        "mobile", "framework", "distributed", "mesh", "end", "based",
        "management", "platform", "system", "process", "event", "events",
        "pattern", "patterns", "application", "config", "configuration",
        "deploy", "deployment", "build", "version", "update", "create",
    }
    query_words = rewritten["original"].split()
    if len(query_words) >= 2:
        for w in query_words:
            wl = w.lower()
            if len(w) >= 5 and wl not in STOP_WORDS and w not in like_search_terms:
                like_search_terms.append(w)

    for term in like_search_terms:
        if len(term) < 2:
            continue
        like_rows = conn.execute("""
            SELECT id, rel_path, title, basename, domain, subdomain
            FROM nodes
            WHERE vault = ? AND tombstone = 0
              AND (content LIKE ? OR title LIKE ? OR basename LIKE ?)
            LIMIT ?
        """, (vault, f"%{term}%", f"%{term}%", f"%{term}%",
              max_results * 4)).fetchall()

        # LIKE-only hits get a base score; individual words get less than full phrase
        is_individual_word = term != rewritten["original"] and term in query_words
        base_score = 0.3 if is_individual_word else 0.5

        for r in like_rows:
            if r[0] not in seen_ids:
                seen_ids.add(r[0])
                hits.append({
                    "id": r[0], "rel_path": r[1], "title": r[2], "basename": r[3],
                    "domain": r[4], "subdomain": r[5],
                    "bm25_score": base_score,
                    "graph_bonus": 0.0, "combined_score": base_score,
                    "source": "like",
                })

    # ----- Pass 3: Path prefix search -----
    if rewritten["path_prefix"]:
        prefix = rewritten["path_prefix"]
        path_rows = conn.execute("""
            SELECT id, rel_path, title, basename, domain, subdomain
            FROM nodes
            WHERE vault = ? AND tombstone = 0 AND rel_path LIKE ?
            LIMIT ?
        """, (vault, f"{prefix}%", max_results * 3)).fetchall()

        for r in path_rows:
            if r[0] not in seen_ids:
                seen_ids.add(r[0])
                hits.append({
                    "id": r[0], "rel_path": r[1], "title": r[2], "basename": r[3],
                    "domain": r[4], "subdomain": r[5],
                    "bm25_score": 15.0,
                    "graph_bonus": 0.0, "combined_score": 15.0,
                    "source": "path_prefix",
                })
            else:
                # Boost existing hits that are under the path prefix
                for h in hits:
                    if h["id"] == r[0]:
                        h["bm25_score"] = max(h["bm25_score"], 15.0)
                        h["combined_score"] = max(h["combined_score"], 15.0)
                        h["source"] = "path_prefix"
                        break

    # ----- Pass 4: Basename exact match boost -----
    for term in rewritten["basename_terms"]:
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
                    "bm25_score": 20.0,
                    "graph_bonus": 0.0, "combined_score": 20.0,
                    "source": "basename_match",
                })
            else:
                for h in hits:
                    if h["id"] == r[0]:
                        h["bm25_score"] = max(h["bm25_score"], 20.0)
                        h["combined_score"] = max(h["combined_score"], 20.0)
                        h["source"] = "basename_match"
                        break

    # ----- Pass 5: Basename-substring match (basename ⊂ query or query ⊂ basename) -----
    query_lower = rewritten["original"].lower()
    if len(query_lower) >= 3:
        # Search for files where basename contains query or query contains basename
        # Use LIKE for basename contains query
        bn_sub_rows = conn.execute("""
            SELECT id, rel_path, title, basename, domain, subdomain
            FROM nodes WHERE vault = ? AND tombstone = 0
              AND (LOWER(basename) LIKE ? OR ? LIKE '%' || LOWER(basename) || '%')
            LIMIT ?
        """, (vault, f"%{query_lower}%", query_lower, max_results * 3)).fetchall()

        for r in bn_sub_rows:
            bn_lower = (r[3] or "").lower()
            if len(bn_lower) < 3:
                continue
            if r[0] not in seen_ids:
                seen_ids.add(r[0])
                hits.append({
                    "id": r[0], "rel_path": r[1], "title": r[2], "basename": r[3],
                    "domain": r[4], "subdomain": r[5],
                    "bm25_score": 12.0,
                    "graph_bonus": 0.0, "combined_score": 12.0,
                    "source": "basename_substring",
                })
            else:
                for h in hits:
                    if h["id"] == r[0]:
                        if h["bm25_score"] < 12.0:
                            h["bm25_score"] = 12.0
                            h["combined_score"] = max(h["combined_score"], 12.0)
                        break

    # ----- Content-match boost: reward files containing the exact query -----
    raw_lower = rewritten["original"].lower()
    if hits and len(raw_lower) >= 3:
        fts_scores = sorted(
            [h["bm25_score"] for h in hits if h["source"] == "fts"],
            reverse=True,
        )
        if fts_scores:
            p75 = fts_scores[len(fts_scores) // 4]
            boost_base = max(p75, 3.0)
        else:
            boost_base = 3.0

        # Check content for exact term and count occurrences
        hit_ids_list = [h["id"] for h in hits]
        placeholders = ",".join("?" for _ in hit_ids_list)
        content_tf: dict[str, int] = {}
        for row in conn.execute(
            f"SELECT id, content, title, basename FROM nodes WHERE id IN ({placeholders})",
            hit_ids_list,
        ):
            text = f"{row[1] or ''} {row[2] or ''} {row[3] or ''}".lower()
            count = text.count(raw_lower)
            if count > 0:
                content_tf[row[0]] = count

        for h in hits:
            if h["id"] in content_tf and h["source"] in ("fts", "like"):
                tf = content_tf[h["id"]]
                tf_boost = boost_base + math.log1p(tf) * 2.0
                if h["bm25_score"] < tf_boost:
                    h["bm25_score"] = tf_boost
                    h["combined_score"] = tf_boost
                    h["source"] = h["source"] + "+boost"

    return hits


# ---------------------------------------------------------------------------
# Graph re-ranking
# ---------------------------------------------------------------------------

def graph_rerank(hits: list[dict], G: nx.DiGraph) -> list[dict]:
    """Re-rank hits using Jaccard graph connectivity bonus."""
    if not G or len(hits) < 2:
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


# ---------------------------------------------------------------------------
# 1-hop BFS expansion
# ---------------------------------------------------------------------------

def expand_neighbors(
    hits: list[dict],
    G: nx.DiGraph,
    hub_threshold: int,
    max_expand: int,
    conn: sqlite3.Connection,
    vault: str,
) -> list[dict]:
    """1-hop BFS expansion from top hits. Returns new nodes not already in hits."""
    if not G or not hits:
        return []

    hit_ids = {h["id"] for h in hits}
    expanded = []
    seen = set(hit_ids)

    for hit in hits[:MAX_EXPAND_SOURCES]:
        nid = hit["id"]
        if nid not in G:
            continue

        neighbors = list(set(G.predecessors(nid)) | set(G.successors(nid)))
        neighbors = [
            n for n in neighbors
            if n not in seen and G.in_degree(n) <= hub_threshold
        ]

        # Sort by edge weight (prefer wiki_link over folder_sibling)
        def edge_weight(n, _nid=nid):
            w = 0.0
            if G.has_edge(_nid, n):
                w = max(w, G[_nid][n].get("weight", 0.0))
            if G.has_edge(n, _nid):
                w = max(w, G[n][_nid].get("weight", 0.0))
            return w

        neighbors.sort(key=edge_weight, reverse=True)

        for n in neighbors[:MAX_EXPAND_NEIGHBORS]:
            if n in seen:
                continue
            seen.add(n)
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

        if len(expanded) >= max_expand:
            break

    return expanded[:max_expand]


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------

def gap_analysis(conn: sqlite3.Connection, vault: str, hits: list[dict]) -> dict:
    """Per-domain gap analysis: how many nodes exist vs how many were hit."""
    domain_totals = {}
    for domain, count in conn.execute(
        "SELECT domain, COUNT(*) FROM nodes WHERE vault = ? AND tombstone = 0 GROUP BY domain",
        (vault,),
    ):
        domain_totals[domain] = count

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


# ---------------------------------------------------------------------------
# Tier 1: Full pipeline
# ---------------------------------------------------------------------------

def tier1_query(
    conn: sqlite3.Connection,
    vault: str,
    raw_query: str,
    max_results: int,
    manifest: set[str] | None = None,
) -> dict:
    """Full pipeline: dual-search + graph rerank + 1-hop expand + gap analysis."""
    rewritten = rewrite_query(raw_query)

    # Adaptive max: for broad queries, return more results
    # Count FTS hits to gauge query breadth
    fts_count = conn.execute(
        "SELECT COUNT(*) FROM nodes_fts WHERE nodes_fts MATCH ?",
        (rewritten["fts_query"],)
    ).fetchone()[0] if rewritten["fts_query"] else 0
    
    effective_max = max_results
    if fts_count > 60:
        effective_max = min(max_results + 20, 50)  # Up to 50 for broad queries
    elif fts_count > 30:
        effective_max = min(max_results + 10, 40)  # Up to 40 for medium queries

    # Dual search
    hits = dual_search(conn, vault, rewritten, effective_max)

    # Graph rerank
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
        "fts_hits": sum(1 for h in hits if h["source"].startswith("fts")),
        "like_hits": sum(1 for h in hits if h["source"].startswith("like")),
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
    hits = dual_search(conn, vault, rewritten, max_results)

    if manifest:
        hits = [r for r in hits if r["id"] not in manifest]

    hits = sorted(hits, key=lambda h: h["combined_score"], reverse=True)[:max_results]
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
        "like_hits": 0,
        "graph_expanded": 0,
    }


# ---------------------------------------------------------------------------
# Tier 3: Legacy grep fallback (no DB)
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

    for term in terms[:3]:
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
        "like_hits": 0,
        "graph_expanded": 0,
    }


# ---------------------------------------------------------------------------
# Tier 4: Empty result with error
# ---------------------------------------------------------------------------

def tier4_error(error_msg: str) -> dict:
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
        "like_hits": 0,
        "graph_expanded": 0,
    }


# ---------------------------------------------------------------------------
# Main query dispatcher with fallback ladder
# ---------------------------------------------------------------------------

def query(
    vault: str,
    raw_query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    manifest: set[str] | None = None,
    mode: str = "full",
    db_path: Path = DEFAULT_DB,
) -> dict:
    """Execute query with 4-tier fallback ladder."""
    if mode == "grep":
        return tier3_query(vault, raw_query, max_results)

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

        try:
            return tier1_query(conn, vault, raw_query, max_results, manifest)
        except Exception as e:
            print(f"  WARN: Tier 1 failed: {e}, falling to Tier 2", file=sys.stderr)

        try:
            return tier2_query(conn, vault, raw_query, max_results, manifest)
        except Exception as e:
            print(f"  WARN: Tier 2 failed: {e}, falling to Tier 3", file=sys.stderr)

        return tier3_query(vault, raw_query, max_results)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Content fetcher
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
    parser.add_argument("--vault", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--mode", choices=["full", "fts-only", "grep"], default="full")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--manifest", help="Comma-separated node IDs already fetched")
    parser.add_argument("--fetch-content", action="store_true")
    parser.add_argument("--compact", action="store_true")
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

    if args.fetch_content and result["results"]:
        content_map = fetch_content([r["id"] for r in result["results"]], args.db_path)
        for r in result["results"]:
            r["content"] = content_map.get(r["id"], "")

    indent = None if args.compact else 2
    print(json.dumps(result, indent=indent))


if __name__ == "__main__":
    main()
