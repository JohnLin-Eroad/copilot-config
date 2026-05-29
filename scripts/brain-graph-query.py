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
from functools import lru_cache
from pathlib import Path

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

# Memory/decay helpers (Phase 2). No-op when BRAIN_DECAY_ENABLED != "1".
sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_graph_memory as bgm  # noqa: E402

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

# Query result cache (LRU, session-scoped)
_query_cache: dict[str, dict] = {}
_CACHE_MAX = 64

def _cache_key(vault: str, raw_query: str, max_results: int, db_path: Path) -> str:
    return f"{vault}|{raw_query}|{max_results}|{db_path}"

def clear_cache():
    """Clear the query cache (call after sync or at session boundaries)."""
    _query_cache.clear()


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
        "the", "and", "for", "from", "with", "that",
        "this", "are", "was", "were", "been", "being", "have", "has", "had",
        "does", "did", "will", "would", "could", "should", "may", "might",
        "shall", "can", "need", "must", "file",
        "used", "using", "uses",
        "into", "over", "under", "between", "through", "about", "each",
        "which", "their", "there", "when", "where", "what", "some", "more",
        "other", "also", "than", "then", "them", "these", "those", "only",
        "very", "just", "like", "make", "made", "many", "much", "most",
        "such", "well", "back", "even", "still", "after", "before",
        "based",
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

    # ----- Pass 2b: Multi-word intersection boost -----
    # For multi-word queries, files containing ALL significant words score much higher
    significant_words = [w for w in query_words if len(w) >= 3 and w.lower() not in STOP_WORDS]
    if len(significant_words) >= 2:
        # Build SQL to find files containing ALL significant words
        conditions = " AND ".join(
            [f"(content LIKE '%' || ? || '%' OR title LIKE '%' || ? || '%')" for _ in significant_words]
        )
        params = []
        for w in significant_words:
            params.extend([w, w])
        sql = f"""
            SELECT id, rel_path, title, basename, domain, subdomain
            FROM nodes WHERE vault = ? AND tombstone = 0 AND {conditions}
            LIMIT ?
        """
        intersection_rows = conn.execute(sql, (vault, *params, max_results * 3)).fetchall()
        
        for r in intersection_rows:
            if r[0] not in seen_ids:
                seen_ids.add(r[0])
                hits.append({
                    "id": r[0], "rel_path": r[1], "title": r[2], "basename": r[3],
                    "domain": r[4], "subdomain": r[5],
                    "bm25_score": 8.0,
                    "graph_bonus": 0.0, "combined_score": 8.0,
                    "source": "like_intersection",
                })
            else:
                # Boost existing hits that match ALL words
                for h in hits:
                    if h["id"] == r[0] and h["combined_score"] < 8.0:
                        h["bm25_score"] = 8.0
                        h["combined_score"] = 8.0
                        h["source"] = h["source"] + "+intersection"
                        break

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

    # ----- Negative-query guard -----
    # For multi-word queries: if the most distinctive term doesn't exist in the vault,
    # the results are noise from common terms. Suppress them.
    query_terms = [w for w in rewritten["original"].split() if len(w) >= 4]
    if len(query_terms) >= 2:
        # Find the rarest term (lowest count in vault)
        term_counts = []
        for w in query_terms:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE vault = ? AND tombstone = 0 AND content LIKE ?",
                (vault, f"%{w}%")
            ).fetchone()[0]
            term_counts.append((w, cnt))
        
        # Sort by count (rarest first)
        term_counts.sort(key=lambda x: x[1])
        rarest_word, rarest_count = term_counts[0]
        
        if rarest_count == 0:
            # Most distinctive term is absent — suppress all low-scoring hits
            hits = [h for h in hits if h["combined_score"] >= 10.0]
        elif rarest_count <= 3 and len(hits) > rarest_count * 3:
            # Very rare term but exists — keep only hits containing the rare term
            rare_ids = set(
                r[0] for r in conn.execute(
                    "SELECT id FROM nodes WHERE vault = ? AND tombstone = 0 AND content LIKE ?",
                    (vault, f"%{rarest_word}%")
                ).fetchall()
            )
            # Keep hits that contain the rare term OR have high scores
            hits = [h for h in hits if h["id"] in rare_ids or h["combined_score"] >= 10.0]

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
# Node-centric traversal (BFS from a starting node)
# ---------------------------------------------------------------------------

def traverse(
    start_node: str,
    vault: str = "eroad",
    max_depth: int = 1,
    max_results: int = DEFAULT_MAX_RESULTS,
    filter_domain: str | None = None,
    filter_edge_type: str | None = None,
    exclude_visited: set[str] | None = None,
    db_path: Path = DEFAULT_DB,
) -> dict:
    """
    BFS traversal starting from a specific node.
    
    This is the expanding-search mode the brain retrieval agent uses:
    1. Start from a known node (e.g., a service, domain, or repo)
    2. Expand 1-hop (or multi-hop) via graph edges
    3. Return neighbors with metadata
    4. Agent marks irrelevant nodes in exclude_visited for next call
    
    Args:
        start_node: rel_path or partial path of the starting node
        vault: vault name
        max_depth: BFS depth (1 = direct neighbors, 2 = neighbors of neighbors)
        max_results: max nodes to return
        filter_domain: only return nodes in this domain
        filter_edge_type: only follow edges of this type (wiki_link, folder_sibling)
        exclude_visited: nodes to skip (already explored and deemed irrelevant)
        db_path: path to SQLite database
    
    Returns dict with:
        - start_node: the resolved starting node
        - results: list of neighbor nodes with metadata + content_summary
        - depth_reached: actual BFS depth explored
        - edges_traversed: number of edges followed
        - pruned_count: nodes skipped due to exclude_visited
    """
    if not db_path.exists():
        return {"error": "DB not found", "results": [], "result_count": 0}
    
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    exclude = exclude_visited or set()
    
    try:
        # Resolve start_node: try exact match, then LIKE on rel_path, then basename
        row = conn.execute(
            "SELECT id, rel_path, title, domain FROM nodes WHERE vault=? AND tombstone=0 AND rel_path=?",
            (vault, start_node)
        ).fetchone()
        
        if not row:
            row = conn.execute(
                "SELECT id, rel_path, title, domain FROM nodes WHERE vault=? AND tombstone=0 AND rel_path LIKE ?",
                (vault, f"%{start_node}%")
            ).fetchone()
        
        if not row:
            row = conn.execute(
                "SELECT id, rel_path, title, domain FROM nodes WHERE vault=? AND tombstone=0 AND basename LIKE ?",
                (vault, f"%{start_node}%")
            ).fetchone()
        
        if not row:
            return {"error": f"Node '{start_node}' not found", "results": [], "result_count": 0}
        
        start_id, start_path, start_title, start_domain = row
        
        # Load graph
        G = load_graph(conn)
        if not G or start_id not in G:
            return {
                "error": "Graph unavailable or node not in graph",
                "start_node": {"id": start_id, "rel_path": start_path, "title": start_title},
                "results": [], "result_count": 0,
            }
        
        hub_threshold = get_hub_threshold(conn)
        
        # BFS expansion
        visited = {start_id}
        current_layer = [start_id]
        all_neighbors = []
        edges_traversed = 0
        pruned = 0
        depth_reached = 0
        
        for depth in range(max_depth):
            next_layer = []
            for nid in current_layer:
                if nid not in G:
                    continue
                neighbors = list(set(G.predecessors(nid)) | set(G.successors(nid)))
                for nbr in neighbors:
                    # Edge-type filtering
                    if filter_edge_type:
                        has_matching_edge = False
                        if G.has_edge(nid, nbr) and G[nid][nbr].get("edge_type") == filter_edge_type:
                            has_matching_edge = True
                        if G.has_edge(nbr, nid) and G[nbr][nid].get("edge_type") == filter_edge_type:
                            has_matching_edge = True
                        if not has_matching_edge:
                            continue
                    edges_traversed += 1
                    if nbr in visited:
                        continue
                    if nbr in exclude:
                        pruned += 1
                        visited.add(nbr)
                        continue
                    # Skip hubs (too generic)
                    if G.in_degree(nbr) > hub_threshold:
                        continue
                    visited.add(nbr)
                    next_layer.append(nbr)
            
            if not next_layer:
                break
            
            depth_reached = depth + 1
            
            # Fetch metadata for this layer
            for nbr_id in next_layer:
                meta = conn.execute("""
                    SELECT id, rel_path, title, basename, domain, subdomain,
                           LENGTH(content) as content_len,
                           SUBSTR(content, 1, 200) as content_preview
                    FROM nodes WHERE id = ? AND vault = ? AND tombstone = 0
                """, (nbr_id, vault)).fetchone()
                
                if not meta:
                    continue
                
                node_domain = meta[4]
                if filter_domain and node_domain and filter_domain.lower() not in node_domain.lower():
                    continue
                
                # Calculate edge weight from start
                edge_w = 0.0
                if G.has_edge(start_id, nbr_id):
                    edge_w = max(edge_w, G[start_id][nbr_id].get("weight", 0.0))
                if G.has_edge(nbr_id, start_id):
                    edge_w = max(edge_w, G[nbr_id][start_id].get("weight", 0.0))
                
                # Get edge type
                edge_type = "unknown"
                for src, tgt in [(start_id, nbr_id), (nbr_id, start_id)]:
                    if G.has_edge(src, tgt):
                        edge_type = G[src][tgt].get("edge_type", "wiki_link")
                        break
                
                all_neighbors.append({
                    "id": meta[0], "rel_path": meta[1], "title": meta[2],
                    "basename": meta[3], "domain": meta[4], "subdomain": meta[5],
                    "content_length": meta[6] or 0,
                    "content_summary": (meta[7] or "").strip()[:150],
                    "depth": depth + 1,
                    "edge_weight": edge_w,
                    "edge_type": edge_type,
                })
            
            current_layer = next_layer
            if len(all_neighbors) >= max_results:
                break
        
        # Sort by edge weight (strongest connections first), then by depth (closer first)
        all_neighbors.sort(key=lambda x: (-x["edge_weight"], x["depth"]))
        results = all_neighbors[:max_results]
        
        return {
            "start_node": {"id": start_id, "rel_path": start_path, "title": start_title, "domain": start_domain},
            "results": results,
            "result_count": len(results),
            "depth_reached": depth_reached,
            "edges_traversed": edges_traversed,
            "pruned_count": pruned,
            "total_discovered": len(all_neighbors),
            "tier": "traverse",
        }
    finally:
        conn.close()


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
    expand_budget = max(effective_max - len(hits), 5)
    expanded = expand_neighbors(hits, G, hub_threshold, expand_budget, conn, vault)

    # Merge
    all_results = hits + expanded

    # Deduplicate against manifest
    if manifest:
        all_results = [r for r in all_results if r["id"] not in manifest]

    # Trim to effective max
    all_results = all_results[:effective_max]

    # Low confidence check
    high_score_count = sum(1 for h in hits if h["bm25_score"] >= BM25_LOW_CONFIDENCE_THRESHOLD)
    low_confidence = high_score_count < LOW_CONFIDENCE_MIN_HITS

    # Gap analysis
    gaps = gap_analysis(conn, vault, all_results)

    # Phase 2: memory blend + access log (no-op unless BRAIN_DECAY_ENABLED=1)
    all_results = bgm.apply_memory(
        conn, all_results, source="search", query_hash=bgm.hash_query(raw_query)
    )

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

    # Phase 2: memory blend + access log (no-op unless BRAIN_DECAY_ENABLED=1)
    hits = bgm.apply_memory(
        conn, hits, source="search", query_hash=bgm.hash_query(raw_query)
    )

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
    """Execute query with 4-tier fallback ladder. Results are LRU-cached."""
    # Check cache (only for full/fts-only modes with no manifest)
    ck = _cache_key(vault, raw_query, max_results, db_path)
    if manifest is None and mode in ("full", "fts-only") and ck in _query_cache:
        cached = _query_cache[ck].copy()
        cached["cached"] = True
        return cached

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
            result = tier2_query(conn, vault, raw_query, max_results, manifest)
        else:
            try:
                result = tier1_query(conn, vault, raw_query, max_results, manifest)
            except Exception as e:
                print(f"  WARN: Tier 1 failed: {e}, falling to Tier 2", file=sys.stderr)
                try:
                    result = tier2_query(conn, vault, raw_query, max_results, manifest)
                except Exception as e2:
                    print(f"  WARN: Tier 2 failed: {e2}, falling to Tier 3", file=sys.stderr)
                    result = tier3_query(vault, raw_query, max_results)

        # Store in cache (only for manifest-free queries)
        if manifest is None:
            if len(_query_cache) >= _CACHE_MAX:
                # Evict oldest entry
                _query_cache.pop(next(iter(_query_cache)))
            _query_cache[ck] = result

        return result
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
        found = {r[0]: r[1] for r in rows}
        # Phase 2: log fetch accesses (no-op unless BRAIN_DECAY_ENABLED=1)
        if bgm.is_enabled():
            try:
                bgm.log_access(conn, list(found.keys()), source="fetch")
            except Exception:
                pass
        return found
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Brain graph query engine")
    sub = parser.add_subparsers(dest="command", help="Command to run")
    
    # Search command (default)
    search_p = sub.add_parser("search", help="Search by query")
    search_p.add_argument("--vault", required=True)
    search_p.add_argument("--query", required=True)
    search_p.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    search_p.add_argument("--mode", choices=["full", "fts-only", "grep"], default="full")
    search_p.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    search_p.add_argument("--manifest", help="Comma-separated node IDs already fetched")
    search_p.add_argument("--fetch-content", action="store_true")
    search_p.add_argument("--compact", action="store_true")
    
    # Traverse command
    trav_p = sub.add_parser("traverse", help="BFS traversal from a starting node")
    trav_p.add_argument("--vault", default="eroad")
    trav_p.add_argument("--start", required=True, help="Starting node rel_path or partial name")
    trav_p.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    trav_p.add_argument("--max-depth", type=int, default=1)
    trav_p.add_argument("--domain", help="Filter results to this domain")
    trav_p.add_argument("--edge-type", help="Only follow this edge type (wiki_link, folder_sibling)")
    trav_p.add_argument("--exclude", help="Comma-separated node IDs to exclude")
    trav_p.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    trav_p.add_argument("--fetch-content", action="store_true")
    trav_p.add_argument("--compact", action="store_true")
    
    # Legacy: if no subcommand, treat as search
    parser.add_argument("--vault", required=False)
    parser.add_argument("--query", required=False)
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--mode", choices=["full", "fts-only", "grep"], default="full")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--manifest", help="Comma-separated node IDs already fetched")
    parser.add_argument("--fetch-content", action="store_true")
    parser.add_argument("--compact", action="store_true")
    
    args = parser.parse_args()
    
    if args.command == "traverse":
        exclude = set(args.exclude.split(",")) if args.exclude else None
        t0 = time.monotonic()
        result = traverse(
            start_node=args.start, vault=args.vault,
            max_depth=args.max_depth, max_results=args.max_results,
            filter_domain=args.domain, filter_edge_type=args.edge_type,
            exclude_visited=exclude, db_path=args.db_path,
        )
        result["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        if args.fetch_content and result["results"]:
            content_map = fetch_content([r["id"] for r in result["results"]], args.db_path)
            for r in result["results"]:
                r["content"] = content_map.get(r["id"], "")
    else:
        # Search mode (default or explicit)
        vault = args.vault
        raw_query = args.query
        if not vault or not raw_query:
            parser.print_help()
            sys.exit(1)
        manifest = set(args.manifest.split(",")) if args.manifest else None
        t0 = time.monotonic()
        result = query(
            vault=vault, raw_query=raw_query, max_results=args.max_results,
            manifest=manifest, mode=args.mode, db_path=args.db_path,
        )
        result["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        if args.fetch_content and result["results"]:
            content_map = fetch_content([r["id"] for r in result["results"]], args.db_path)
            for r in result["results"]:
                r["content"] = content_map.get(r["id"], "")
    
    indent = None if args.compact else 2
    print(json.dumps(result, indent=indent))


if __name__ == "__main__":
    main()
