"""brain_graph_memory.py — Decay, score-blend, supersedes, and access-logging.

Pure-functional core (no I/O) + thin SQL helpers. Feature-flagged via
BRAIN_DECAY_ENABLED env var; when off, every public function is a no-op
that returns inputs unchanged.

Design constraints (from plan-v2):
  * Multiplicative blend on score, not raw multiply — exact-match boosts
    (20.0 for basename, etc.) must remain dominant.
  * effective_strength floors at DECAY_FLOOR so nothing disappears.
  * Nodes with no node_memory row → effective_strength = 1.0 (unmanaged).
  * title is NEVER mutated by this module.
  * Access logging is batched in a single INSERT.

Public API:
    is_enabled() -> bool
    effective_strength(strength, half_life_days, last_retrieved_at, now) -> float
    blend_score(bm25, eff_strength, is_superseded) -> float
    apply_memory(conn, hits, source, query_hash=None) -> list[dict]
    log_access(conn, node_ids, source, query_hash=None) -> None
"""
from __future__ import annotations

import hashlib
import math
import os
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

# ---------------------------------------------------------------------------
# Constants (plan-v2)
# ---------------------------------------------------------------------------

DECAY_FLOOR = 0.05
SUPERSEDES_PENALTY = 0.25       # multiplicative; superseded nodes downranked
BLEND_BASE = 0.5                 # final = bm25 * (BLEND_BASE + (1-BLEND_BASE) * eff)
BLEND_SLOPE = 0.5
DEFAULT_HALF_LIFE = 7.0
MAX_HALF_LIFE = 180.0
HALF_LIFE_GROWTH = 1.05          # successful retrieval extends half-life by 5%
BUMPS = {                         # added to *decayed* strength on access
    "search":   0.05,
    "traverse": 0.05,
    "fetch":    0.20,
}
FEATURE_FLAG_ENV = "BRAIN_DECAY_ENABLED"


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return os.environ.get(FEATURE_FLAG_ENV, "0") == "1"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def effective_strength(
    strength: float | None,
    half_life_days: float | None,
    last_retrieved_at: str | None,
    now: datetime | None = None,
) -> float:
    """Apply exponential decay since last_retrieved_at.

    Unmanaged nodes (strength is None) -> 1.0.
    Floored at DECAY_FLOOR; never returns 0.
    """
    if strength is None:
        return 1.0
    if last_retrieved_at is None:
        return max(DECAY_FLOOR, min(1.0, strength))
    half_life = half_life_days or DEFAULT_HALF_LIFE
    if half_life <= 0:
        return max(DECAY_FLOOR, min(1.0, strength))
    now = now or datetime.now(timezone.utc)
    last = _parse_ts(last_retrieved_at)
    age_days = max(0.0, (now - last).total_seconds() / 86400.0)
    decayed = strength * math.pow(0.5, age_days / half_life)
    return max(DECAY_FLOOR, min(1.0, decayed))


def blend_score(bm25: float, eff_strength: float, is_superseded: bool = False) -> float:
    """Multiplicative blend that preserves exact-match dominance.

    final = bm25 * (BLEND_BASE + BLEND_SLOPE * eff_strength) * (penalty if superseded)
    With BLEND_BASE=0.5: a fully decayed node retains 50-55% of its bm25 score.
    """
    factor = BLEND_BASE + BLEND_SLOPE * eff_strength
    if is_superseded:
        factor *= SUPERSEDES_PENALTY
    return bm25 * factor


def _parse_ts(ts: str) -> datetime:
    """Parse SQLite datetime('now') format → aware UTC datetime."""
    # SQLite stores as 'YYYY-MM-DD HH:MM:SS' (no TZ); treat as UTC.
    if "T" in ts:
        # ISO-8601
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def _fetch_memory_rows(
    conn: sqlite3.Connection, node_ids: list[str]
) -> dict[str, dict]:
    """Return {node_id: {strength, half_life_days, last_retrieved_at,
    superseded_by, confidence, retrieval_count}} for MANAGED nodes only.
    Unmanaged nodes are absent from the dict.
    """
    if not node_ids:
        return {}
    placeholders = ",".join("?" for _ in node_ids)
    rows = conn.execute(
        f"SELECT node_id, strength, half_life_days, last_retrieved_at, "
        f"       superseded_by, confidence, retrieval_count "
        f"FROM node_memory WHERE node_id IN ({placeholders})",
        node_ids,
    ).fetchall()
    return {
        r[0]: {
            "strength": r[1],
            "half_life_days": r[2],
            "last_retrieved_at": r[3],
            "superseded_by": r[4],
            "confidence": r[5],
            "retrieval_count": r[6],
        }
        for r in rows
    }


def log_access(
    conn: sqlite3.Connection,
    node_ids: Iterable[str],
    source: str,
    query_hash: str | None = None,
) -> None:
    """Insert one row per node_id into node_access_log (batched).

    Safe to call when feature flag is off (still useful telemetry once we
    backfill) — but our policy is to only log when flag is on.
    """
    ids = list(node_ids)
    if not ids:
        return
    if source not in ("search", "traverse", "fetch"):
        raise ValueError(f"invalid source: {source}")
    conn.executemany(
        "INSERT INTO node_access_log (node_id, source, query_hash) VALUES (?, ?, ?)",
        [(nid, source, query_hash) for nid in ids],
    )
    conn.commit()


def hash_query(raw_query: str) -> str:
    return hashlib.sha1(raw_query.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Reinforcement (Phase 3)
# ---------------------------------------------------------------------------

def reinforce(
    conn: sqlite3.Connection,
    node_ids: Iterable[str],
    source: str,
    now: datetime | None = None,
) -> int:
    """Bump strength + extend half-life for each MANAGED node accessed.

    Behaviour:
      * No-op when flag is off.
      * Unmanaged nodes (no node_memory row) are NOT auto-created — silently skipped.
      * Bump applied to *decayed* strength (not raw stored value), so stale
        nodes don't bounce straight back to 1.0 on a single hit.
      * Strength capped at 1.0, half-life capped at MAX_HALF_LIFE.
      * Updates last_retrieved_at + retrieval_count + updated_at.

    Returns number of rows updated.
    """
    if not is_enabled():
        return 0
    ids = [n for n in node_ids if n]
    if not ids:
        return 0
    bump = BUMPS.get(source)
    if bump is None:
        raise ValueError(f"invalid source: {source}")

    rows = _fetch_memory_rows(conn, ids)
    if not rows:
        return 0

    now = now or datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    updates = []
    for nid, m in rows.items():
        decayed = effective_strength(
            m["strength"], m["half_life_days"], m["last_retrieved_at"], now=now
        )
        new_strength = min(1.0, decayed + bump)
        new_half_life = min(
            MAX_HALF_LIFE,
            (m["half_life_days"] or DEFAULT_HALF_LIFE) * HALF_LIFE_GROWTH,
        )
        updates.append((new_strength, new_half_life, now_str, nid))

    conn.executemany(
        "UPDATE node_memory SET "
        "  strength = ?, "
        "  half_life_days = ?, "
        "  last_retrieved_at = ?, "
        "  retrieval_count = retrieval_count + 1, "
        "  updated_at = datetime('now') "
        "WHERE node_id = ?",
        updates,
    )
    conn.commit()
    return len(updates)


# ---------------------------------------------------------------------------
# Top-level integration: rerank + log
# ---------------------------------------------------------------------------

def apply_memory(
    conn: sqlite3.Connection,
    hits: list[dict],
    source: str,
    query_hash: str | None = None,
    log: bool = True,
    now: datetime | None = None,
    resort: bool = True,
) -> list[dict]:
    """No-op when feature flag is off. Otherwise:
      1. LEFT JOIN node_memory for every hit
      2. For MANAGED nodes only: attach effective_strength, confidence,
         retrieval_count, superseded_by; blend bm25 into combined_score.
      3. Unmanaged nodes are left untouched (combined_score stays = bm25 + bonus,
         no memory fields added — keeps output clean for the common case).
      4. Re-sort by combined_score (only when resort=True; traverse passes False
         to preserve its edge-weight ordering).
      5. Log access + reinforce managed nodes.

    Mutates `hits` in place and returns the list.
    """
    if not is_enabled() or not hits:
        return hits

    ids = [h["id"] for h in hits if "id" in h]
    mem = _fetch_memory_rows(conn, ids)

    for h in hits:
        nid = h.get("id")
        m = mem.get(nid)
        if m is None:
            # Unmanaged: do not attach any memory fields.
            continue
        eff = effective_strength(
            m["strength"], m["half_life_days"], m["last_retrieved_at"], now=now
        )
        is_sup = m["superseded_by"] is not None
        h["effective_strength"] = round(eff, 4)
        h["superseded_by"] = m["superseded_by"]
        h["confidence"] = m["confidence"]
        h["retrieval_count"] = m["retrieval_count"]
        bm25 = h.get("bm25_score", h.get("combined_score", 0.0))
        graph_bonus = h.get("graph_bonus", 0.0)
        h["combined_score"] = round(blend_score(bm25, eff, is_sup) + graph_bonus, 4)

    if resort:
        hits.sort(key=lambda x: x.get("combined_score", 0.0), reverse=True)

    if log and ids:
        try:
            log_access(conn, ids, source, query_hash)
        except sqlite3.Error:
            # Logging must never break retrieval.
            pass

    # Reinforce managed nodes (no-op when flag off, or for unmanaged nodes)
    try:
        reinforce(conn, ids, source, now=now)
    except sqlite3.Error:
        pass

    return hits
