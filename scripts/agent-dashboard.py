#!/usr/bin/env python3
"""
Agent Visibility Dashboard

Live-updating HTML dashboard showing:
  - Which agents are active / completed / blocked
  - Pipeline flow diagram with animated connections
  - Per-agent activity cards with status and findings
  - Activity feed / timeline
  - Full STM content viewer

Reads write-stm.sh entries (### AGENT — TIMESTAMP format) from all active STM files.

Usage:
  python3 ~/.copilot/scripts/agent-dashboard.py
  python3 ~/.copilot/scripts/agent-dashboard.py --port 8765
  python3 ~/.copilot/scripts/agent-dashboard.py --stm /path/to/short-term-memory.md
"""

import argparse
import dataclasses
import fcntl
import hashlib
import http.server
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.request
import uuid as uuid_mod
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

STM_DIR = Path.home() / ".copilot" / "stm"
PORT = 8765
STM_FILENAME = "short-term-memory.md"
LOCK_FILE = Path.home() / ".copilot" / "run" / "agent-dashboard.lock"
ACTIVE_LINK = STM_DIR / ".active"

AGENT_COLORS = {
    "orchestrator":          "#6c8ef7",
    "developer":             "#34d399",
    "developer-a":           "#34d399",
    "developer-b":           "#38bdf8",
    "developer-c":           "#fb923c",
    "developer-d":           "#a78bfa",
    "developer-e":           "#f472b6",
    "developer-f":           "#fbbf24",
    "architect":             "#a78bfa",
    "security":              "#f87171",
    "code-reviewer":         "#fb923c",
    "testing":               "#22d3ee",
    "qa-engineer":           "#22d3ee",
    "devops":                "#fbbf24",
    "discovery":             "#4ade80",
    "documentation":         "#94a3b8",
    "brain-data-retrieval":  "#e879f9",
    "brain-consolidation":   "#e879f9",
    "benchmark-runner":      "#f97316",
    "product-manager":       "#60a5fa",
    "product-owner":         "#60a5fa",
    "performance":           "#facc15",
    "data-migration":        "#fb7185",
    "compliance":            "#a3e635",
    "governance":            "#a3e635",
    "integration":           "#38bdf8",
}
DEFAULT_AGENT_COLOR = "#6b7280"

STATUS_META = {
    "starting":    {"color": "#fbbf24", "icon": "◌", "label": "Starting"},
    "in_progress": {"color": "#6c8ef7", "icon": "◉", "label": "Working"},
    "complete":    {"color": "#34d399", "icon": "✓",  "label": "Done"},
    "blocked":     {"color": "#f87171", "icon": "✕",  "label": "Blocked"},
    "failed":      {"color": "#f87171", "icon": "✕",  "label": "Failed"},
}
DEFAULT_STATUS = {"color": "#94a3b8", "icon": "○", "label": "Idle"}

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


# ── Multi-workflow data model ─────────────────────────────────────────────

@dataclasses.dataclass
class WorkflowIdentity:
    """Immutable identity for a discovered STM workflow."""
    uuid: str               # UUID4 from .dashboard-id sidecar
    directory: Path          # Absolute path — I/O locator only, NOT identity
    slug: str               # Directory name as human-readable label
    created_at: str          # ISO timestamp from frontmatter or dir mtime fallback


@dataclasses.dataclass
class WorkflowState:
    """Mutable state for a tracked workflow — updated by poller."""
    identity: WorkflowIdentity
    entries: list           # Parsed timeline entry dicts
    meta: dict              # Parsed STM frontmatter + sections
    content_hash: str       # md5 hex of file content (change detection)
    file_mtime: float       # os.stat st_mtime
    file_size: int          # os.stat st_size
    last_refreshed_at: float   # time.monotonic() — last successful parse
    last_accessed_at: float    # time.monotonic() — bumped on tab view (LRU)
    consecutive_errors: int    # 0 = healthy
    last_error: Optional[str]  # last error message
    parse_ok: bool             # False after 3 consecutive errors


@dataclasses.dataclass
class DashboardState:
    """Top-level mutable state — lock-protected."""
    workflows: dict          # {uuid: WorkflowState}
    active_workflow_id: Optional[str]    # UUID of .active target
    selected_workflow_id: Optional[str]  # UUID user is viewing (defaults to active)
    tab_order: list          # UUIDs in display order


# ── WorkflowRegistry ─────────────────────────────────────────────────────

class WorkflowRegistry:
    """Discovers STM directories and manages workflow lifecycle.

    Thread-safe: all public methods acquire self._lock.
    Discovery is rate-limited to avoid excessive filesystem scans.
    """

    DISCOVERY_WINDOW_H = 72         # scan dirs modified in last 72h
    MAX_TRACKED = 30                # max workflows in memory
    DISCOVERY_INTERVAL_S = 10       # re-scan filesystem every 10s

    def __init__(self, stm_dir: Path):
        self._stm_dir = stm_dir
        self._lock = threading.Lock()
        self._workflows: dict[str, WorkflowState] = {}   # uuid → state
        self._active_uuid: Optional[str] = None
        self._selected_uuid: Optional[str] = None
        self._tab_order: list[str] = []
        self._last_discovery: float = 0.0

    # ── Public accessors (lock-protected) ─────────────────────────────

    def get_state_snapshot(self) -> DashboardState:
        """Return a shallow copy of current state for API serialisation."""
        with self._lock:
            return DashboardState(
                workflows=dict(self._workflows),
                active_workflow_id=self._active_uuid,
                selected_workflow_id=self._selected_uuid or self._active_uuid,
                tab_order=list(self._tab_order),
            )

    def get_workflow(self, uuid: str) -> Optional[WorkflowState]:
        """Get a single workflow by UUID. Returns None if not found."""
        with self._lock:
            return self._workflows.get(uuid)

    def get_all_workflows(self) -> list[WorkflowState]:
        """Return a copy of all tracked workflows."""
        with self._lock:
            return list(self._workflows.values())

    def select_workflow(self, uuid: str) -> bool:
        """Set selected tab. Returns False if UUID not found."""
        with self._lock:
            if uuid not in self._workflows:
                return False
            self._selected_uuid = uuid
            self._workflows[uuid].last_accessed_at = time.monotonic()
            return True

    def bump_accessed(self, uuid: str) -> None:
        """Bump last_accessed_at for LRU tracking (called on serve)."""
        with self._lock:
            wf = self._workflows.get(uuid)
            if wf:
                wf.last_accessed_at = time.monotonic()

    @property
    def lock(self) -> threading.Lock:
        """Expose lock for poller snapshot swap."""
        return self._lock

    # ── Discovery ─────────────────────────────────────────────────────

    def discover(self) -> None:
        """Scan STM_DIR for workflow directories. Thread-safe."""
        now_mono = time.monotonic()
        if now_mono - self._last_discovery < self.DISCOVERY_INTERVAL_S:
            return
        self._last_discovery = now_mono

        # 1. Find candidate directories (modified within rolling window)
        cutoff = time.time() - (self.DISCOVERY_WINDOW_H * 3600)
        candidates: list[tuple[Path, float]] = []

        try:
            for entry in self._stm_dir.iterdir():
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                stm_file = entry / STM_FILENAME
                try:
                    st = stm_file.stat()
                    if st.st_mtime >= cutoff:
                        candidates.append((entry, st.st_mtime))
                except OSError:
                    continue
        except OSError:
            return

        # 2. Resolve .active target
        active_dir = self._resolve_active_dir()

        # 3. Force-include .active target (never evict active)
        if active_dir:
            cand_dirs = {c[0].resolve() for c in candidates}
            resolved_active = active_dir.resolve()
            if resolved_active not in cand_dirs:
                try:
                    mtime = (active_dir / STM_FILENAME).stat().st_mtime
                    candidates.append((active_dir, mtime))
                except OSError:
                    pass

        # 4. LRU eviction — sort by max(last_accessed_at, file_mtime)
        def lru_key(item: tuple[Path, float]) -> float:
            d, mtime = item
            uid = self._read_dashboard_id(d)
            with self._lock:
                existing = self._workflows.get(uid)
            if existing:
                return max(existing.last_accessed_at, mtime)
            return mtime

        candidates.sort(key=lru_key, reverse=True)

        # 5. Cap + force-pin active
        if len(candidates) > self.MAX_TRACKED:
            candidates = candidates[: self.MAX_TRACKED]

        # Force active back in if evicted by cap
        if active_dir:
            cand_dirs_post = {c[0].resolve() for c in candidates}
            resolved_active = active_dir.resolve()
            if resolved_active not in cand_dirs_post and candidates:
                candidates[-1] = (active_dir, time.time())

        # 6. Register new workflows, prune removed — under lock
        with self._lock:
            seen_uuids: set[str] = set()
            for d, _ in candidates:
                uid = self._ensure_dashboard_id(d)
                if not uid:
                    continue
                seen_uuids.add(uid)
                if uid not in self._workflows:
                    # Get initial file mtime for auto-select fallback
                    stm_file = d / STM_FILENAME
                    try:
                        init_mtime = stm_file.stat().st_mtime
                        init_size = stm_file.stat().st_size
                    except OSError:
                        init_mtime, init_size = 0.0, 0
                    self._workflows[uid] = WorkflowState(
                        identity=WorkflowIdentity(
                            uuid=uid,
                            directory=d,
                            slug=d.name,
                            created_at=self._read_created(d),
                        ),
                        entries=[],
                        meta={},
                        content_hash="",
                        file_mtime=init_mtime,
                        file_size=init_size,
                        last_refreshed_at=0.0,
                        last_accessed_at=time.monotonic(),
                        consecutive_errors=0,
                        last_error=None,
                        parse_ok=True,
                    )

            # Prune workflows no longer discovered
            for uid in list(self._workflows.keys()):
                if uid not in seen_uuids:
                    del self._workflows[uid]

            # Update active UUID
            active_uuid = None
            if active_dir:
                active_uuid = self._read_dashboard_id(active_dir)
                if active_uuid and active_uuid not in self._workflows:
                    active_uuid = None
            self._active_uuid = active_uuid

            # If selected no longer exists, reset to active or most recent with entries
            if self._selected_uuid and self._selected_uuid not in self._workflows:
                self._selected_uuid = self._active_uuid

            # Auto-select: if nothing selected, pick active or most-recent workflow with entries
            if not self._selected_uuid:
                if self._active_uuid:
                    self._selected_uuid = self._active_uuid
                else:
                    # Find most recently modified workflow that has entries
                    best_uid, best_mtime = None, 0.0
                    for uid, wf in self._workflows.items():
                        if wf.file_mtime > best_mtime:
                            best_uid, best_mtime = uid, wf.file_mtime
                    self._selected_uuid = best_uid

            # Deterministic tab order: by created_at, ties broken by UUID
            self._tab_order = sorted(
                self._workflows.keys(),
                key=lambda uid: (self._workflows[uid].identity.created_at, uid),
            )

    # ── Internal helpers (no locking — caller holds lock or uses try/except) ──

    def _resolve_active_dir(self) -> Optional[Path]:
        """Resolve .active symlink with containment check."""
        active_link = self._stm_dir / ".active"
        if not active_link.is_symlink():
            return None
        try:
            target = active_link.resolve()
            # Containment check — must be under STM_DIR
            stm_real = self._stm_dir.resolve()
            if not str(target).startswith(str(stm_real) + os.sep):
                return None
            if target.is_dir() and (target / STM_FILENAME).exists():
                return target
        except OSError:
            pass
        return None

    def _read_dashboard_id(self, d: Path) -> str:
        """Read .dashboard-id sidecar. Returns '' if missing/invalid."""
        try:
            content = (d / ".dashboard-id").read_text(encoding="utf-8").strip()
            if UUID_RE.match(content):
                return content
        except OSError:
            pass
        return ""

    def _ensure_dashboard_id(self, d: Path) -> str:
        """Read or create .dashboard-id sidecar with atomic create."""
        # Try read first
        uid = self._read_dashboard_id(d)
        if uid:
            return uid

        # Create atomically
        uid = str(uuid_mod.uuid4())
        id_path = d / ".dashboard-id"
        try:
            fd = os.open(str(id_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, uid.encode("utf-8"))
            finally:
                os.close(fd)
            return uid
        except FileExistsError:
            # Race: another process created it — read theirs
            return self._read_dashboard_id(d)
        except OSError:
            # Disk full / permissions — generate ephemeral ID (not persisted)
            return uid

    def _read_created(self, d: Path) -> str:
        """Extract created timestamp from frontmatter, fallback to dir mtime."""
        try:
            content = (d / STM_FILENAME).read_text(
                encoding="utf-8", errors="replace"
            )[:2000]
            m = re.search(r'created:\s*"?(\d{4}-\d{2}-\d{2}T[\d:]+Z?)"?', content)
            if m:
                return m.group(1)
        except OSError:
            pass
        try:
            return datetime.fromtimestamp(
                d.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            return datetime.now(timezone.utc).isoformat()


# ── Snapshot type ─────────────────────────────────────────────────────────

class STMSnapshot(NamedTuple):
    stm_path: Path
    content: str
    mtime: float
    data: dict
    refreshed_at: float


_snapshot_lock = threading.Lock()
_current_snapshot: Optional[STMSnapshot] = None
_shutdown_event = threading.Event()
_start_time = time.monotonic()
_exit_code = 1       # SIGTERM → exit(1) → launchd restarts
_pinned_stm_path: Optional[Path] = None
_lock_fd = None      # held open for process lifetime; OS releases on death
_workflow_registry = None   # type: Optional[WorkflowRegistry]  (set in main)
_workflow_poller = None     # type: Optional[WorkflowPoller]    (set in main)


# ── Singleton (fcntl exclusive lock) ─────────────────────────────────────

def _acquire_singleton() -> bool:
    global _lock_fd
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = open(LOCK_FILE, 'w')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(os.getpid()))
        fd.flush()
        _lock_fd = fd
        return True
    except OSError:
        try:
            fd.close()
        except Exception:
            pass
        return False


def _release_singleton():
    global _lock_fd
    if _lock_fd:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
        except Exception:
            pass
        _lock_fd = None
        LOCK_FILE.unlink(missing_ok=True)


# ── STM discovery ─────────────────────────────────────────────────────────

def _resolve_active_stm() -> Optional[Path]:
    """Active STM: pinned path → .active symlink → newest-mtime fallback."""
    if _pinned_stm_path is not None and _pinned_stm_path.exists():
        return _pinned_stm_path
    if ACTIVE_LINK.is_symlink():
        try:
            target_dir = ACTIVE_LINK.resolve()
            if target_dir.is_dir():
                candidate = target_dir / STM_FILENAME
                if candidate.exists():
                    return candidate
        except Exception:
            pass
        try:
            ACTIVE_LINK.unlink()
        except Exception:
            pass
    if not STM_DIR.exists():
        return None
    candidates = sorted(
        [p for p in STM_DIR.rglob(STM_FILENAME) if p.exists()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


# ── Atomic STM read ───────────────────────────────────────────────────────

def _atomic_read_stm(path: Path, retries: int = 3) -> tuple:
    """Read with stable-mtime guarantee. Returns (content, mtime) or (None, 0.0)."""
    for _ in range(retries):
        try:
            mtime_before = path.stat().st_mtime
            content = path.read_text(encoding="utf-8", errors="replace")
            mtime_after = path.stat().st_mtime
            if mtime_before == mtime_after:
                return content, mtime_before
        except Exception:
            return None, 0.0
        time.sleep(0.05)
    return None, 0.0


# ── Background snapshot refresh ───────────────────────────────────────────

def _do_refresh():
    global _current_snapshot
    stm_path = _resolve_active_stm()
    if stm_path is None:
        return
    content, mtime = _atomic_read_stm(stm_path)
    if content is None:
        return
    with _snapshot_lock:
        if _current_snapshot is not None and _current_snapshot.mtime == mtime:
            return
    data = _build_dashboard_data(stm_path, content)
    with _snapshot_lock:
        if _current_snapshot is None or mtime >= _current_snapshot.mtime:
            _current_snapshot = STMSnapshot(
                stm_path=stm_path,
                content=content,
                mtime=mtime,
                data=data,
                refreshed_at=time.monotonic(),
            )


def _refresh_loop():
    while not _shutdown_event.wait(2.0):
        try:
            _do_refresh()
        except Exception:
            pass


# ── WorkflowPoller ────────────────────────────────────────────────────────

class WorkflowPoller:
    """Single-thread, sleep-after-completion poller for all tracked workflows.

    Design choices from dual-critique:
    - sleep-after-completion (NOT threading.Timer) — no overlap risk
    - Three-tier change detection: (mtime,size) → md5 → forced reparse
    - Parse outside lock — lock only for snapshot swap (<1μs)
    - Per-file try/except — skip on error, don't crash
    - Error tracking with explicit reset on success
    - Adaptive polling: 2s active, 10s idle
    """

    ACTIVE_INTERVAL_S = 1.0     # any workflow changed recently
    IDLE_INTERVAL_S = 5.0       # no changes in last 60s
    FORCE_REPARSE_S = 30.0      # bypass fast-path every 30s
    IDLE_THRESHOLD_S = 60.0     # no change for this long → idle mode

    def __init__(self, registry: WorkflowRegistry, shutdown: threading.Event):
        self._registry = registry
        self._shutdown = shutdown
        self._last_any_change: float = time.monotonic()
        self._poll_running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the poller background thread."""
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="workflow-poller"
        )
        self._thread.start()

    def _run(self) -> None:
        """Main loop: poll → sleep → repeat. Sleep AFTER completion (no overlap)."""
        while not self._shutdown.is_set():
            interval = self._poll_cycle()
            self._shutdown.wait(interval)

    def _poll_cycle(self) -> float:
        """Run one poll cycle. Returns next sleep interval."""
        if self._poll_running:
            return self.ACTIVE_INTERVAL_S
        self._poll_running = True
        try:
            # 1. Let registry discover/prune workflows
            self._registry.discover()

            # 2. Get current workflow list (snapshot under lock)
            workflows = self._registry.get_all_workflows()

            any_change = False
            for wf in workflows:
                try:
                    changed = self._poll_workflow(wf)
                    if changed:
                        any_change = True
                except Exception:
                    pass  # per-file try/except — never crash the loop

            if any_change:
                self._last_any_change = time.monotonic()

            # Also maintain v1 compat: update _current_snapshot for active workflow
            self._update_v1_snapshot()

        except Exception:
            pass  # Never crash the poller
        finally:
            self._poll_running = False

        # Adaptive interval
        idle_seconds = time.monotonic() - self._last_any_change
        return self.IDLE_INTERVAL_S if idle_seconds > self.IDLE_THRESHOLD_S else self.ACTIVE_INTERVAL_S

    def _poll_workflow(self, wf: WorkflowState) -> bool:
        """Poll a single workflow. Returns True if content changed."""
        stm_file = wf.identity.directory / STM_FILENAME
        now = time.monotonic()

        # ── Tier 1: fast stat check ──────────────────────────
        try:
            st = stm_file.stat()
        except OSError as e:
            wf.consecutive_errors += 1
            wf.last_error = f"stat failed: {e}"
            if wf.consecutive_errors >= 3:
                wf.parse_ok = False
            return False

        force_reparse = (now - wf.last_refreshed_at) >= self.FORCE_REPARSE_S
        if not force_reparse and st.st_mtime == wf.file_mtime and st.st_size == wf.file_size:
            return False  # fast-path: nothing changed

        # ── Tier 2: read + hash ──────────────────────────────
        content, mtime = _atomic_read_stm(stm_file)
        if content is None:
            wf.consecutive_errors += 1
            wf.last_error = "atomic read failed (mtime changed during read)"
            if wf.consecutive_errors >= 3:
                wf.parse_ok = False
            return False

        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        if content_hash == wf.content_hash and not force_reparse:
            # Content identical (e.g. file touched but not modified)
            wf.file_mtime = mtime
            wf.file_size = st.st_size
            return False

        # ── Tier 3: parse (outside lock) ─────────────────────
        try:
            entries = parse_stm_entries(content)
            meta = parse_stm_meta(content)
        except Exception as e:
            wf.consecutive_errors += 1
            wf.last_error = f"parse failed: {e}"
            if wf.consecutive_errors >= 3:
                wf.parse_ok = False
            return False

        # Build timeline entry keys with byte offsets
        for i, entry in enumerate(entries):
            entry["_key"] = f"{entry['agent']}::{entry['timestamp']}::{i}"

        # ── Snapshot swap (under lock, <1μs) ──────────────────
        with self._registry.lock:
            wf.entries = entries
            wf.meta = meta
            wf.content_hash = content_hash
            wf.file_mtime = mtime
            wf.file_size = st.st_size
            wf.last_refreshed_at = now
            # Explicit reset on success
            wf.consecutive_errors = 0
            wf.last_error = None
            wf.parse_ok = True

        return True

    def _update_v1_snapshot(self) -> None:
        """Keep the old _current_snapshot in sync for v1 API compat."""
        global _current_snapshot
        state = self._registry.get_state_snapshot()
        sel_id = state.selected_workflow_id or state.active_workflow_id
        if not sel_id or sel_id not in state.workflows:
            return
        wf = state.workflows[sel_id]
        if not wf.entries:
            return
        stm_path = wf.identity.directory / STM_FILENAME

        # Build v1-shaped data from workflow state
        agent_latest: dict[str, dict] = {}
        for e in wf.entries:
            agent_latest[e["agent"]] = e

        # Infer implied completion (same logic as _build_payload_from_content)
        if agent_latest:
            pipeline_complete = any(
                e["status"] == "complete" for e in agent_latest.values()
            )
            if pipeline_complete:
                latest_complete_ts = max(
                    (e["timestamp"] for e in agent_latest.values() if e["status"] == "complete"),
                    default="",
                )
                for e in agent_latest.values():
                    if (
                        e["status"] == "in_progress"
                        and e["timestamp"] < latest_complete_ts
                    ):
                        e["status"] = "complete"
                        e["_implied_complete"] = True

        agents_sorted = sorted(agent_latest.values(), key=lambda a: a["timestamp"], reverse=True)
        latest_ts = {a["agent"]: a["timestamp"] for a in agents_sorted}
        timeline_raw = list(reversed(wf.entries[-40:]))
        for e in timeline_raw:
            e["is_latest"] = (e["timestamp"] == latest_ts.get(e["agent"]))

        data = {
            "stm_path":    str(stm_path),
            "stm_name":    re.sub(r"^\d{4}[-\s]\d{2}[-\s]\d{2}[-\s]", "",
                                  stm_path.parent.name.replace("-", " ")).title(),
            "meta":        wf.meta,
            "agents":      agents_sorted,
            "timeline":    timeline_raw,
            "entry_count": len(wf.entries),
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }

        with _snapshot_lock:
            _current_snapshot = STMSnapshot(
                stm_path=stm_path,
                content="",  # not needed for v1 API
                mtime=wf.file_mtime,
                data=data,
                refreshed_at=time.monotonic(),
            )


def parse_stm_entries(content: str) -> list[dict]:
    """Parse write-stm.sh entries: ### AGENT — TIMESTAMP\\nBody"""
    entries = []

    # Restrict to Agent Contributions section only (defense in depth)
    contrib_marker = "## [STM] Agent Contributions"
    contrib_idx = content.find(contrib_marker)
    search_text = content[contrib_idx:] if contrib_idx >= 0 else content

    # Match entries written by write-stm.sh
    # [^\n]+? prevents agent name from crossing newlines (fixes Prior Sessions bleed)
    pattern = re.compile(
        r"### ([^\n]+?) — (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\n(.*?)(?=\n### |\Z)",
        re.DOTALL,
    )
    for m in pattern.finditer(search_text):
        agent = m.group(1).strip()
        ts = m.group(2).strip()
        body = m.group(3).strip()

        status = "idle"
        findings = ""
        files = ""
        decisions = ""
        next_step = ""
        parent = ""
        unit = ""

        for line in body.splitlines():
            low = line.strip().lower()
            if low.startswith("status:"):
                status = line.split(":", 1)[1].strip().lower()
            elif low.startswith("findings:"):
                findings = line.split(":", 1)[1].strip()
            elif low.startswith("files:"):
                files = line.split(":", 1)[1].strip()
            elif low.startswith("decisions:"):
                decisions = line.split(":", 1)[1].strip()
            elif low.startswith("next:"):
                next_step = line.split(":", 1)[1].strip()
            elif low.startswith("parent:"):
                parent = line.split(":", 1)[1].strip()
            elif low.startswith("unit:"):
                unit = line.split(":", 1)[1].strip()
            elif low.startswith("phase:"):
                # PHASE: is written by developer agents — map to dashboard status
                # Only use it if STATUS: wasn't explicitly set
                if status == "idle":
                    phase_val = line.split(":", 1)[1].strip().lower()
                    phase_map = {
                        "starting": "starting", "code": "in_progress",
                        "in_progress": "in_progress", "compile": "in_progress",
                        "compile_checked": "in_progress", "done": "complete",
                        "failed": "failed", "deferred": "blocked",
                    }
                    status = phase_map.get(phase_val, status)

        # Multi-line findings (lines after FINDINGS: that don't start with a key)
        in_findings = False
        extra_lines = []
        keys = {"status:", "files:", "decisions:", "next:", "findings:", "parent:", "unit:"}
        for line in body.splitlines():
            low = line.strip().lower()
            if low.startswith("findings:"):
                in_findings = True
                continue
            if any(low.startswith(k) for k in keys if not low.startswith("findings:")):
                in_findings = False
            if in_findings and line.strip():
                extra_lines.append(line.strip())
        if extra_lines:
            findings = (findings + " " + " ".join(extra_lines)).strip()

        # Resource metrics
        tool_used = tool_max = context_tokens = context_pct = context_max = None
        model = ""
        for line in body.splitlines():
            stripped = line.strip()
            m_tool = re.match(r"TOOL_CALLS:\s*(\d+)\s*/\s*(\d+)", stripped, re.IGNORECASE)
            if m_tool:
                tool_used, tool_max = int(m_tool.group(1)), int(m_tool.group(2))
            # CONTEXT: N/M  (absolute tokens, e.g. "CONTEXT: 108000/128000")
            m_ctx_abs = re.match(r"CONTEXT:\s*(\d+)\s*/\s*(\d+)", stripped, re.IGNORECASE)
            if m_ctx_abs:
                context_tokens = int(m_ctx_abs.group(1))
                context_max    = int(m_ctx_abs.group(2))
            # CONTEXT: ~Nk tokens
            m_ctx_k = re.match(r"CONTEXT:\s*~?(\d+(?:\.\d+)?)k\s*tokens?", stripped, re.IGNORECASE)
            if m_ctx_k:
                context_tokens = int(float(m_ctx_k.group(1)) * 1000)
            # CONTEXT: N%
            m_ctx_p = re.match(r"CONTEXT:\s*~?(\d+(?:\.\d+)?)%", stripped, re.IGNORECASE)
            if m_ctx_p:
                context_pct = float(m_ctx_p.group(1))
            m_model = re.match(r"MODEL:\s*(.+)", stripped, re.IGNORECASE)
            if m_model:
                model = m_model.group(1).strip()

        entries.append({
            "agent":          agent,
            "timestamp":      ts,
            "status":         status,
            "findings":       findings,
            "files":          files,
            "decisions":      decisions,
            "next":           next_step,
            "raw":            body,
            "tool_used":      tool_used,
            "tool_max":       tool_max,
            "context_tokens": context_tokens,
            "context_pct":    context_pct,
            "context_max":    context_max,
            "model":          model,
            "parent":         parent,
            "unit":           unit,
        })

    return entries


def parse_stm_meta(content: str) -> dict:
    """Extract task name and high-level info from STM frontmatter / Task Brief."""
    meta = {"task": "Unknown Task", "brain": "", "started": "", "sections": {}}

    fm = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if fm:
        for line in fm.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip().lower()] = v.strip().strip('"')

    # Task Brief section
    brief = re.search(r"## \[STM\] Task Brief\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if brief:
        meta["sections"]["Task Brief"] = brief.group(1).strip()
        task_m = re.search(r"(?:\*\*Task\*\*|Task):\s*(.+)", brief.group(1))
        if task_m:
            meta["task"] = task_m.group(1).strip()
        brain_m = re.search(r"BRAIN_TYPE:\s*(\w+)", brief.group(1))
        if brain_m:
            meta["brain"] = brain_m.group(1).strip()

    # Also capture other sections
    for section_m in re.finditer(r"## \[STM\] (.+?)\n(.*?)(?=\n## |\Z)", content, re.DOTALL):
        name = section_m.group(1).strip()
        body = section_m.group(2).strip()
        if name not in meta["sections"]:
            meta["sections"][name] = body

    return meta


def _build_dashboard_data(stm_path: Path, content: str) -> dict:
    """Build dashboard payload from pre-read content (avoids double-read in refresh loop)."""
    entries = parse_stm_entries(content)
    meta = parse_stm_meta(content)

    agent_latest: dict[str, dict] = {}
    for e in entries:
        agent_latest[e["agent"]] = e

    # Infer implied completion: if an agent's last status is "in_progress"
    # but a later agent has already reached "complete", the stuck agent is
    # implicitly done (it handed off and was never updated).
    if agent_latest:
        pipeline_complete = any(
            e["status"] == "complete" for e in agent_latest.values()
        )
        if pipeline_complete:
            latest_complete_ts = max(
                (e["timestamp"] for e in agent_latest.values() if e["status"] == "complete"),
                default="",
            )
            for e in agent_latest.values():
                if (
                    e["status"] == "in_progress"
                    and e["timestamp"] < latest_complete_ts
                ):
                    e["status"] = "complete"
                    e["_implied_complete"] = True

    agents_sorted = sorted(agent_latest.values(), key=lambda a: a["timestamp"], reverse=True)
    latest_ts_per_agent = {a["agent"]: a["timestamp"] for a in agents_sorted}

    timeline_raw = list(reversed(entries[-40:]))
    for e in timeline_raw:
        e["is_latest"] = (e["timestamp"] == latest_ts_per_agent.get(e["agent"]))

    # Read pipeline DAG if present (lives alongside STM)
    dag = None
    dag_path = stm_path.parent / "pipeline-dag.json"
    if dag_path.exists():
        try:
            dag = json.loads(dag_path.read_text(encoding="utf-8"))
        except Exception:
            dag = None

    return {
        "stm_path":    str(stm_path),
        "stm_name":    re.sub(r"^\d{4}[-\s]\d{2}[-\s]\d{2}[-\s]", "", stm_path.parent.name.replace("-", " ")).title(),
        "meta":        meta,
        "agents":      agents_sorted,
        "timeline":    timeline_raw,
        "entry_count": len(entries),
        "updated_at":  datetime.now(timezone.utc).isoformat(),
        "dag":         dag,
    }


def get_dashboard_data(stm_path: Path) -> dict:
    try:
        content = stm_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": str(e), "agents": [], "timeline": [], "meta": {}}
    return _build_dashboard_data(stm_path, content)


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚡ Agent Dashboard</title>
<style>
:root {
  --bg: #0a0d14;
  --bg-card: #111827;
  --bg-card2: #1a2235;
  --border: #1e2d45;
  --border2: #243552;
  --text: #e2e8f0;
  --text2: #94a3b8;
  --text3: #64748b;
  --blue: #6c8ef7;
  --green: #34d399;
  --yellow: #fbbf24;
  --red: #f87171;
  --purple: #a78bfa;
  --cyan: #22d3ee;
  --orange: #fb923c;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --mono: 'SF Mono','Fira Code',monospace;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font);overflow:hidden}

/* ── Layout ── */
#app{display:grid;grid-template-rows:56px auto 1fr;grid-template-columns:280px 1fr 320px;height:100vh}
#topbar{grid-column:1/-1;display:flex;align-items:center;gap:16px;padding:0 24px;
  background:var(--bg-card);border-bottom:1px solid var(--border);z-index:10}
#tab-bar{grid-column:1/-1;display:flex;align-items:center;gap:2px;padding:0 16px;
  background:var(--bg);border-bottom:1px solid var(--border);overflow-x:auto;
  min-height:36px;flex-shrink:0;scrollbar-width:thin}
#tab-bar::-webkit-scrollbar{height:4px}
#tab-bar::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.tab{display:flex;align-items:center;gap:6px;padding:4px 12px;font-size:0.72rem;
  color:var(--text2);cursor:pointer;border-radius:6px 6px 0 0;white-space:nowrap;
  border:1px solid transparent;border-bottom:none;transition:all 0.15s;max-width:200px;overflow:hidden;text-overflow:ellipsis}
.tab:hover{background:var(--bg-card);color:var(--text)}
.tab.active{background:var(--bg-card);color:var(--text);border-color:var(--border);font-weight:600}
.tab .tab-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.tab .tab-dot.green{background:#34d399}
.tab .tab-dot.gray{background:#64748b}
.tab .tab-badge{font-size:0.65rem;opacity:0.7}
.tab .tab-entries{font-size:0.6rem;color:var(--text2);opacity:0.6}
.tab-toggle{display:flex;align-items:center;gap:4px;padding:4px 10px;font-size:0.65rem;
  color:var(--text2);cursor:pointer;border-radius:4px;white-space:nowrap;margin-left:auto;
  border:1px solid var(--border);transition:all 0.15s;flex-shrink:0;user-select:none}
.tab-toggle:hover{background:var(--bg-card);color:var(--text)}
.tab-toggle.on{color:var(--accent);border-color:var(--accent)}
#sidebar{grid-row:3;overflow-y:auto;border-right:1px solid var(--border);padding:16px}
#main{grid-row:3;overflow-y:auto;padding:20px 24px}
#rightpanel{grid-row:3;overflow-y:auto;border-left:1px solid var(--border);padding:16px}

/* ── Topbar ── */
.topbar-title{font-size:1rem;font-weight:700;color:var(--text);flex:1}
.topbar-task{font-size:0.8rem;color:var(--text2);max-width:400px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--green);
  box-shadow:0 0 6px var(--green);animation:pulse-dot 2s ease-in-out infinite}
@keyframes pulse-dot{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.5;transform:scale(1.3)}}
.topbar-time{font-size:0.75rem;color:var(--text3);font-family:var(--mono)}
.refresh-badge{font-size:0.7rem;padding:2px 8px;background:rgba(108,142,247,0.15);
  color:var(--blue);border-radius:99px;border:1px solid rgba(108,142,247,0.3)}

/* ── Section label ── */
.section-label{font-size:0.7rem;text-transform:uppercase;letter-spacing:.08em;
  color:var(--text3);margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border)}

/* ── Pipeline summary banner ── */
#pipeline-summary{display:none;margin-bottom:16px;padding:14px 18px;border-radius:12px;
  background:#111827;border:1px solid var(--border);font-size:0.82rem;line-height:1.55}
#pipeline-summary.visible{display:block}
#pipeline-summary.done{border-color:rgba(52,211,153,0.4);background:rgba(52,211,153,0.06)}
#pipeline-summary.running{border-color:rgba(108,142,247,0.4);background:rgba(108,142,247,0.06)}
#pipeline-summary.failed{border-color:rgba(248,113,113,0.4);background:rgba(248,113,113,0.06)}
#pipeline-summary .ps-header{display:flex;align-items:center;gap:10px;margin-bottom:8px}
#pipeline-summary .ps-title{color:#e2e8f0;font-weight:600;font-size:0.9rem}
#pipeline-summary .ps-badge{font-size:0.7rem;padding:2px 10px;border-radius:99px;font-weight:500}
#pipeline-summary .ps-stats{display:flex;gap:16px;flex-wrap:wrap}
#pipeline-summary .ps-stat{color:#94a3b8;font-size:0.76rem}
#pipeline-summary .ps-stat b{color:#cbd5e1;font-weight:600}

/* ── Pipeline diagram ── */
#pipeline-wrap{position:relative;overflow-x:auto;margin-bottom:24px}
#pipeline-svg{display:block;min-height:240px}

/* ── DAG Node Tooltip (hover) ── */
#dag-tooltip{position:fixed;z-index:9999;pointer-events:none;
  background:#151b2b;border:1px solid rgba(108,142,247,0.35);border-radius:10px;
  padding:10px 14px;max-width:340px;font-size:0.78rem;line-height:1.45;
  color:#94a3b8;box-shadow:0 8px 24px rgba(0,0,0,0.55);display:none;
  backdrop-filter:blur(8px)}
#dag-tooltip .tt-agent{color:#e2e8f0;font-weight:600;font-size:0.85rem;margin-bottom:4px}
#dag-tooltip .tt-status{font-size:0.72rem;padding:2px 8px;border-radius:99px;display:inline-block;margin-bottom:6px}
#dag-tooltip .tt-findings{color:#cbd5e1;white-space:pre-wrap;max-height:120px;overflow:hidden;text-overflow:ellipsis}
#dag-tooltip .tt-meta{color:#475569;font-size:0.7rem;margin-top:6px}

/* ── DAG Node Detail Modal (click) ── */
#dag-modal-overlay{position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.6);
  display:none;align-items:center;justify-content:center;backdrop-filter:blur(3px)}
#dag-modal-overlay.visible{display:flex}
#dag-modal{background:#0f1420;border:1px solid rgba(108,142,247,0.3);border-radius:14px;
  padding:0;width:min(580px,90vw);max-height:80vh;overflow:hidden;
  box-shadow:0 16px 48px rgba(0,0,0,0.7)}
#dag-modal .modal-header{display:flex;align-items:center;justify-content:space-between;
  padding:16px 20px;border-bottom:1px solid var(--border);background:#111827}
#dag-modal .modal-header h3{margin:0;font-size:1rem;color:#e2e8f0;font-weight:600}
#dag-modal .modal-close{background:none;border:none;color:#64748b;font-size:1.3rem;
  cursor:pointer;padding:4px 8px;border-radius:6px;transition:color .2s}
#dag-modal .modal-close:hover{color:#e2e8f0}
#dag-modal .modal-body{padding:16px 20px;overflow-y:auto;max-height:calc(80vh - 60px)}
#dag-modal .detail-row{display:flex;gap:10px;margin-bottom:10px;align-items:baseline}
#dag-modal .detail-label{color:#475569;font-size:0.72rem;text-transform:uppercase;
  letter-spacing:.06em;min-width:70px;flex-shrink:0}
#dag-modal .detail-value{color:#cbd5e1;font-size:0.82rem;line-height:1.5}
#dag-modal .detail-value.findings{white-space:pre-wrap;background:#0a0d14;padding:10px 12px;
  border-radius:8px;border:1px solid #1e2d45;font-family:'SF Mono',monospace;font-size:0.76rem;
  max-height:240px;overflow-y:auto;width:100%}
#dag-modal .detail-value .badge{display:inline-block;padding:2px 8px;border-radius:99px;
  font-size:0.7rem;margin-right:6px}
#dag-modal .files-list{list-style:none;padding:0;margin:0}
#dag-modal .files-list li{color:#6c8ef7;font-family:'SF Mono',monospace;font-size:0.76rem;
  padding:2px 0}

/* ── Agent cards ── */
.agent-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;margin-bottom:24px}
.agent-card{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;
  padding:14px;transition:border-color .3s,box-shadow .3s;position:relative;overflow:hidden}
.agent-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--agent-color,var(--blue))}
.agent-card.active{border-color:var(--agent-color,var(--blue));
  box-shadow:0 0 20px -4px var(--agent-color,var(--blue)),0 0 0 1px rgba(108,142,247,.1)}
.agent-card.active .card-ring{animation:ring-pulse 1.8s ease-in-out infinite}
.card-header{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.card-ring{width:34px;height:34px;border-radius:50%;background:rgba(108,142,247,.1);
  display:flex;align-items:center;justify-content:center;font-size:1rem;flex-shrink:0;
  border:2px solid var(--agent-color,var(--blue));transition:border-color .3s}
@keyframes ring-pulse{0%,100%{box-shadow:0 0 0 0 var(--agent-color,var(--blue))}
  50%{box-shadow:0 0 0 6px transparent}}
.card-name{font-size:0.9rem;font-weight:600;color:var(--text)}
.card-ts{font-size:0.7rem;color:var(--text3);font-family:var(--mono)}
.card-status{display:inline-flex;align-items:center;gap:5px;font-size:0.72rem;font-weight:600;
  padding:3px 9px;border-radius:99px;margin-bottom:8px;border:1px solid}
.card-body{font-size:0.78rem;color:var(--text2);line-height:1.5}
.card-findings{margin-bottom:6px}
.card-files{font-family:var(--mono);font-size:0.72rem;color:var(--text3);
  background:var(--bg);padding:4px 8px;border-radius:6px;margin-top:6px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ── Working shimmer overlay ── */
.agent-card.active::after{content:'';position:absolute;top:0;left:-100%;width:60%;height:100%;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.03),transparent);
  animation:shimmer 2s ease-in-out infinite}
@keyframes shimmer{0%{left:-100%}100%{left:150%}}

/* ── Stale card ── */
.agent-card.stale{opacity:0.55;filter:grayscale(0.4)}
.stale-badge{font-size:0.65rem;padding:2px 7px;border-radius:99px;
  background:rgba(100,116,139,0.18);color:var(--text3);border:1px solid rgba(100,116,139,0.25);
  display:inline-flex;align-items:center;gap:3px}

/* ── Timeline ── */
.timeline-entry{display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);
  animation:slide-in .3s ease}
.timeline-entry.superseded{opacity:0.38}
.timeline-entry.superseded .tl-agent{color:var(--text3)}
.superseded-badge{font-size:0.62rem;padding:1px 5px;border-radius:3px;
  background:rgba(100,116,139,0.15);color:var(--text3);margin-left:6px;vertical-align:middle}
@keyframes slide-in{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:none}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
.tl-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:5px}
.tl-content{flex:1;min-width:0}
.tl-agent{font-size:0.78rem;font-weight:600;color:var(--text)}
.tl-status{font-size:0.7rem;margin-left:6px;padding:1px 6px;border-radius:99px}
.tl-findings{font-size:0.75rem;color:var(--text2);margin-top:2px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tl-time{font-size:0.68rem;color:var(--text3);font-family:var(--mono);flex-shrink:0;padding-top:2px}

/* ── STM section label → Resources label ── */
/* ── Resource gauge styles ── */
.res-agent{padding:9px 0;border-bottom:1px solid var(--border)}
.res-agent:last-child{border-bottom:none}
.res-agent-name{display:flex;align-items:center;gap:6px;font-size:0.75rem;
  font-family:var(--mono);color:var(--text);margin-bottom:5px}
.res-status-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.res-model-pill{font-size:0.63rem;color:var(--text3);background:rgba(167,139,250,.1);
  border:1px solid rgba(167,139,250,.25);border-radius:4px;padding:1px 5px;
  font-family:var(--mono);margin-left:auto;flex-shrink:0;max-width:130px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.res-warn-badge{font-size:0.62rem;padding:1px 5px;border-radius:8px;font-weight:700;flex-shrink:0}
.gauge-row{display:flex;align-items:center;gap:7px;margin:2px 0}
.gauge-lbl{font-size:0.62rem;color:var(--text3);text-transform:uppercase;
  letter-spacing:.04em;width:34px;flex-shrink:0}
.gauge-track{flex:1;height:4px;background:var(--bg);border-radius:2px;overflow:hidden;
  border:1px solid var(--border)}
.gauge-fill{height:100%;border-radius:2px;transition:width .4s ease,background .4s ease}
.gauge-val{font-size:0.62rem;font-family:var(--mono);width:88px;
  text-align:right;flex-shrink:0;color:var(--text3)}
.gauge-unknown{font-size:0.62rem;color:var(--text3);font-style:italic}
/* card-level inline gauge */
.card-gauges{padding:4px 0 8px;margin-bottom:8px;border-bottom:1px solid var(--border)}

/* ── Empty state ── */
.empty-state{text-align:center;padding:48px 24px;color:var(--text3)}
.empty-icon{font-size:3rem;margin-bottom:12px}

/* ── Scrollbar ── */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}

/* ── Stat strip ── */
.stat-strip{display:flex;gap:12px;margin-bottom:20px}
.stat-box{flex:1;background:var(--bg-card);border:1px solid var(--border);
  border-radius:10px;padding:10px 14px;text-align:center}
.stat-val{font-size:1.5rem;font-weight:700;line-height:1}
.stat-lbl{font-size:0.68rem;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-top:2px}

/* No-STM overlay */
#no-stm{display:none;position:fixed;inset:0;background:rgba(10,13,20,.9);
  z-index:999;align-items:center;justify-content:center;text-align:center}
#no-stm.show{display:flex}
</style>
</head>
<body>

<div id="app">
  <!-- Topbar -->
  <header id="topbar">
    <div class="status-dot" id="conn-dot"></div>
    <div>
      <div class="topbar-title">⚡ Agent Dashboard</div>
    </div>
    <div class="topbar-task" id="task-name">Loading…</div>
    <div style="flex:1"></div>
    <span class="refresh-badge">Live · 2s</span>
    <span class="topbar-time" id="topbar-time"></span>
  </header>

  <!-- Tab bar: workflow tabs -->
  <nav id="tab-bar"></nav>

  <!-- Left sidebar: Task Context + Resources -->
  <aside id="sidebar">
    <div id="stm-sections"></div>
    <div class="section-label" style="margin-top:12px">🔋 Resources</div>
    <div id="res-summary" style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap"></div>
    <div id="res-agents"></div>
  </aside>

  <!-- Main: pipeline + agent cards -->
  <main id="main">
    <!-- Stat strip -->
    <div class="stat-strip">
      <div class="stat-box">
        <div class="stat-val" id="stat-workers" style="color:#34d399">0</div>
        <div class="stat-lbl">👷 Workers</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" id="stat-active" style="color:var(--blue)">0</div>
        <div class="stat-lbl">Active</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" id="stat-done" style="color:var(--green)">0</div>
        <div class="stat-lbl">Done</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" id="stat-blocked" style="color:var(--red)">0</div>
        <div class="stat-lbl">Blocked</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" id="stat-entries" style="color:var(--text2)">0</div>
        <div class="stat-lbl">Entries</div>
      </div>
    </div>

    <!-- Pipeline SVG diagram -->
    <div class="section-label" style="margin-bottom:12px">Pipeline Flow</div>
    <div id="pipeline-summary"></div>
    <div id="pipeline-wrap">
      <svg id="pipeline-svg" width="100%" height="240"></svg>
    </div>
    <!-- DAG hover tooltip -->
    <div id="dag-tooltip"></div>
    <!-- DAG click detail modal -->
    <div id="dag-modal-overlay" onclick="if(event.target===this)this.classList.remove('visible')">
      <div id="dag-modal">
        <div class="modal-header">
          <h3 id="modal-title">Agent Detail</h3>
          <button class="modal-close" onclick="document.getElementById('dag-modal-overlay').classList.remove('visible')">&times;</button>
        </div>
        <div class="modal-body" id="modal-body"></div>
      </div>
    </div>

    <!-- Agent cards -->
    <div class="section-label" style="margin-bottom:12px">Agent Activity</div>
    <div class="agent-grid" id="agent-grid">
      <div class="empty-state"><div class="empty-icon">🤖</div><p>No agent activity yet.<br>Waiting for write-stm.sh entries…</p></div>
    </div>
  </main>

  <!-- Right panel: timeline -->
  <aside id="rightpanel">
    <div class="section-label">Activity Feed</div>
    <div id="timeline"></div>
  </aside>
</div>

<!-- No STM overlay -->
<div id="no-stm">
  <div>
    <div style="font-size:3rem;margin-bottom:16px">🔍</div>
    <div style="font-size:1.1rem;font-weight:600;margin-bottom:8px">No Active STM</div>
    <div style="font-size:0.85rem;color:#64748b">Start a task to see agent activity here.</div>
  </div>
</div>

<script>
const AGENT_COLORS = {
  "orchestrator":         "#6c8ef7",
  "developer":            "#34d399",
  "developer-a":          "#34d399",
  "developer-b":          "#38bdf8",
  "developer-c":          "#fb923c",
  "developer-d":          "#a78bfa",
  "developer-e":          "#f472b6",
  "developer-f":          "#fbbf24",
  "architect":            "#a78bfa",
  "security":             "#f87171",
  "code-reviewer":        "#fb923c",
  "testing":              "#22d3ee",
  "qa-engineer":          "#22d3ee",
  "devops":               "#fbbf24",
  "discovery":            "#4ade80",
  "documentation":        "#94a3b8",
  "brain-data-retrieval": "#e879f9",
  "brain-consolidation":  "#e879f9",
  "benchmark-runner":     "#f97316",
  "product-manager":      "#60a5fa",
  "product-owner":        "#60a5fa",
  "performance":          "#facc15",
  "data-migration":       "#fb7185",
  "compliance":           "#a3e635",
  "governance":           "#a3e635",
  "integration":          "#38bdf8",
};
const DEFAULT_COLOR = "#6b7280";

const STATUS_META = {
  "starting":    { color: "#fbbf24", icon: "◌", label: "Starting" },
  "in_progress": { color: "#6c8ef7", icon: "◉", label: "Working"  },
  "complete":    { color: "#34d399", icon: "✓",  label: "Done"     },
  "blocked":     { color: "#f87171", icon: "✕",  label: "Blocked"  },
  "failed":      { color: "#f87171", icon: "✕",  label: "Failed"   },
  "idle":        { color: "#6b7280", icon: "○",  label: "Idle"     },
};

function agentColor(name) {
  return AGENT_COLORS[name.toLowerCase()] || DEFAULT_COLOR;
}
function statusMeta(s) {
  return STATUS_META[s?.toLowerCase()] || STATUS_META["idle"];
}
function agentEmoji(name) {
  const map = {
    orchestrator:"🎯", developer:"💻", architect:"🏛️", security:"🔒",
    "developer-a":"💻", "developer-b":"💻", "developer-c":"💻",
    "developer-d":"💻", "developer-e":"💻", "developer-f":"💻",
    "code-reviewer":"👁️", testing:"🧪", "qa-engineer":"🧪", devops:"⚙️",
    discovery:"🔍", documentation:"📝", "brain-data-retrieval":"🧠",
    "brain-consolidation":"💾", "benchmark-runner":"📊", "product-manager":"📋",
    performance:"⚡", "data-migration":"🗄️", compliance:"✅", governance:"⚖️",
    integration:"🔌",
  };
  return map[name.toLowerCase()] || "🤖";
}

function relTime(isoStr) {
  try {
    const d = new Date(isoStr);
    const diff = Math.floor((Date.now() - d) / 1000);
    if (diff < 5)  return "just now";
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
    return `${Math.floor(diff/3600)}h ago`;
  } catch { return ""; }
}

// ── Pipeline diagram — multi-row stage layout ──────────────────────────────────
// When a DAG is present, uses actual dependencies for layout and edges.
// Falls back to hardcoded stages when no DAG exists.
function pipelineStage(name) {
  if (name === "orchestrator")                    return 0;
  if (name === "brain-data-retrieval")            return 1;
  if (/^developer-[a-z]$/.test(name))            return 2;
  if (name === "integration-lanes")               return 3;
  if (name === "reconcile")                       return 4;
  if (name === "brain-consolidation")             return 5;
  return 1; // unknown agents sit alongside brain-retrieval
}

const STAGE_LABELS = {
  0: "ORCHESTRATE", 1: "FETCH", 2: "PARALLEL DEV",
  3: "INTEGRATE",   4: "RECONCILE", 5: "CONSOLIDATE"
};

function drawPipeline(agents, timeline) {
  const svg = document.getElementById("pipeline-svg");
  const dagData = window.__latestData?.dag;

  // DAG takes priority — render even with empty agents array
  if (dagData && dagData.nodes && dagData.nodes.length > 0) {
    const W = svg.clientWidth || 900;
    drawPipelineFromDag(svg, dagData, agents || [], W, 24, 100, 40);
    return;
  }

  if (!agents || agents.length === 0) {
    svg.innerHTML = '<text x="50%" y="120" text-anchor="middle" fill="#334155" font-size="13">No agents yet</text>';
    return;
  }

  // ── Legacy hardcoded stage layout (fallback) ───────────────────────
  // Collect unique agent names in timeline order; always include orchestrator first
  const seen = new Set();
  const agentNames = [];
  if (!seen.has("orchestrator")) { agentNames.push("orchestrator"); seen.add("orchestrator"); }
  for (const e of (timeline || [])) {
    if (!seen.has(e.agent)) { agentNames.push(e.agent); seen.add(e.agent); }
  }

  // Group by stage
  const stageGroups = {}; // stage → [names]
  for (const name of agentNames) {
    const s = pipelineStage(name);
    if (!stageGroups[s]) stageGroups[s] = [];
    if (!stageGroups[s].includes(name)) stageGroups[s].push(name);
  }
  const stages = Object.keys(stageGroups).map(Number).sort((a, b) => a - b);

  // Compute (x, y) for every agent
  const pos = {}; // name → {x, y}
  for (const s of stages) {
    const nodes  = stageGroups[s];
    const rowIdx = stages.indexOf(s);
    const rowY   = TOP_PAD + rowIdx * ROW_H;
    const maxGap = Math.min(110, (W - 120) / Math.max(nodes.length, 1));
    const totalW = maxGap * (nodes.length - 1);
    const startX = W / 2 - totalW / 2;
    nodes.forEach((name, i) => {
      pos[name] = { x: startX + i * maxGap, y: rowY };
    });
  }

  const maxY = Math.max(...Object.values(pos).map(p => p.y));
  const H    = maxY + R + 38;
  svg.setAttribute("height", H);

  let html = `<defs>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <marker id="arr"       viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#1e2d45"/></marker>
    <marker id="arr-green" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#34d399"/></marker>
    <marker id="arr-blue"  viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#6c8ef7"/></marker>
  </defs>`;

  // Stage separator lines + labels
  for (const s of stages) {
    const rowY = pos[stageGroups[s][0]].y;
    html += `<line x1="0" y1="${rowY}" x2="${W}" y2="${rowY}" stroke="#1e2d45" stroke-width="1" opacity="0.35" stroke-dasharray="3 4"/>`;
    html += `<text x="6" y="${rowY - 5}" font-size="7" fill="#334155" font-family="system-ui,monospace" letter-spacing="1">${STAGE_LABELS[s] || `STAGE ${s}`}</text>`;
  }

  // Stage-to-stage edges: every node in stageN → every node in stageN+1
  for (let si = 0; si < stages.length - 1; si++) {
    const fromNodes = stageGroups[stages[si]];
    const toNodes   = stageGroups[stages[si + 1]];
    for (const from of fromNodes) {
      for (const to of toNodes) {
        const { x: x1, y: y1 } = pos[from];
        const { x: x2, y: y2 } = pos[to];
        const fe = agents.find(a => a.agent === from);
        const te = agents.find(a => a.agent === to);
        const active = fe?.status === "in_progress" || fe?.status === "starting" ||
                       te?.status === "in_progress" || te?.status === "starting";
        const done   = fe?.status === "complete";
        const col    = active ? agentColor(from) : done ? "#34d399" : "#1e2d45";
        const op     = active ? 0.9 : done ? 0.5 : 0.2;
        const sw     = active ? 2   : done ? 1.5 : 1;
        const mid    = (y1 + y2) / 2;
        const marker = active ? "arr-blue" : done ? "arr-green" : "arr";
        html += `<path d="M${x1},${y1+R} C${x1},${mid} ${x2},${mid} ${x2},${y2-R}"
          fill="none" stroke="${col}" stroke-width="${sw}" opacity="${op}"
          marker-end="url(#${marker})" stroke-dasharray="${active ? '6 3' : done ? '0' : '4 4'}">
          ${active ? `<animate attributeName="stroke-dashoffset" values="0;-18" dur="1.2s" repeatCount="indefinite"/>` : ''}
        </path>`;
      }
    }
  }

  // Node renderer (inner function)
  function nodeHtml(name, x, y, entry) {
    const col       = agentColor(name);
    const sm        = statusMeta(entry?.status || "idle");
    const isActive  = entry?.status === "in_progress" || entry?.status === "starting";
    const isDone    = entry?.status === "complete";
    const isBlocked = entry?.status === "blocked"     || entry?.status === "failed";
    const fill      = isActive  ? `rgba(${hexToRgb(col)},0.18)` :
                      isDone    ? `rgba(52,211,153,0.1)` :
                      isBlocked ? `rgba(248,113,113,0.1)` : "#111827";
    const stroke    = isActive  ? col : isDone ? "#34d399" : isBlocked ? "#f87171" : "#1e2d45";
    const short     = name.replace("brain-data-retrieval","brain-ret.")
                          .replace("brain-consolidation","brain-cons.")
                          .replace(/-/g," ");
    let g = `<g>`;
    if (isActive) {
      g += `<circle cx="${x}" cy="${y}" r="${R+4}" fill="none" stroke="${col}" stroke-width="1" opacity="0.3">
        <animate attributeName="r" values="${R+2};${R+10};${R+2}" dur="1.8s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.4;0;0.4" dur="1.8s" repeatCount="indefinite"/>
      </circle>`;
    }
    g += `<circle cx="${x}" cy="${y}" r="${R}" fill="${fill}" stroke="${stroke}"
      stroke-width="${isActive ? 2.5 : 1.5}" ${isActive ? 'filter="url(#glow)"' : ''}/>`;
    g += `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle" font-size="13">${agentEmoji(name)}</text>`;
    g += `<text x="${x}" y="${y+R+14}" text-anchor="middle" font-size="9"
      fill="${isActive ? col : isDone ? '#34d399' : '#64748b'}"
      font-family="system-ui,sans-serif">${short}</text>`;
    if (entry) {
      g += `<circle cx="${x+R-5}" cy="${y-R+5}" r="5" fill="${sm.color}" stroke="#0a0d14" stroke-width="1.5">
        ${isActive ? `<animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite"/>` : ''}
      </circle>`;
    }
    g += `</g>`;
    return g;
  }

  // Draw nodes bottom-up so orchestrator renders on top of edges
  for (let i = stages.length - 1; i >= 0; i--) {
    for (const name of stageGroups[stages[i]]) {
      html += nodeHtml(name, pos[name].x, pos[name].y, agents.find(a => a.agent === name));
    }
  }

  svg.innerHTML = html;
}

// ── DAG-based pipeline renderer ──────────────────────────────────────────────
function drawPipelineFromDag(svg, dag, agents, W, R, ROW_H, TOP_PAD) {
  const nodes = dag.nodes;

  // Compute depth of each node (longest path from root)
  const depthMap = {};
  function getDepth(nodeId) {
    if (depthMap[nodeId] !== undefined) return depthMap[nodeId];
    const node = nodes.find(n => n.id === nodeId);
    if (!node || !node.deps || node.deps.length === 0) {
      depthMap[nodeId] = 0;
      return 0;
    }
    const maxParent = Math.max(...node.deps.map(d => getDepth(d)));
    depthMap[nodeId] = maxParent + 1;
    return depthMap[nodeId];
  }
  nodes.forEach(n => getDepth(n.id));

  // Group by depth layer
  const layers = {};
  nodes.forEach(n => {
    const d = depthMap[n.id];
    if (!layers[d]) layers[d] = [];
    layers[d].push(n);
  });
  const layerKeys = Object.keys(layers).map(Number).sort((a, b) => a - b);

  // Compute (x, y) positions
  const pos = {};
  layerKeys.forEach((layer, rowIdx) => {
    const nodesInLayer = layers[layer];
    const rowY = TOP_PAD + rowIdx * ROW_H;
    const maxGap = Math.min(130, (W - 120) / Math.max(nodesInLayer.length, 1));
    const totalW = maxGap * (nodesInLayer.length - 1);
    const startX = W / 2 - totalW / 2;
    nodesInLayer.forEach((n, i) => {
      pos[n.id] = { x: startX + i * maxGap, y: rowY };
    });
  });

  const maxY = Math.max(...Object.values(pos).map(p => p.y));
  const H = maxY + R + 38;
  svg.setAttribute("height", H);

  // DAG status → dashboard status mapping
  function dagStatus(node) {
    if (node.status === "done")    return "complete";
    if (node.status === "running") return "in_progress";
    if (node.status === "failed")  return "failed";
    if (node.status === "skipped") return "complete";
    return "idle";
  }

  let html = `<defs>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <marker id="arr"       viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#475569"/></marker>
    <marker id="arr-green" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#34d399"/></marker>
    <marker id="arr-blue"  viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#6c8ef7"/></marker>
    <marker id="arr-red"   viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#f87171"/></marker>
  </defs>`;

  // Layer separator lines with labels
  layerKeys.forEach(layer => {
    const nodesInLayer = layers[layer];
    const rowY = pos[nodesInLayer[0].id].y;
    const label = nodesInLayer.length === 1 ? nodesInLayer[0].label.toUpperCase() : `LAYER ${layer}`;
    html += `<line x1="0" y1="${rowY}" x2="${W}" y2="${rowY}" stroke="#1e2d45" stroke-width="1" opacity="0.35" stroke-dasharray="3 4"/>`;
    html += `<text x="6" y="${rowY - 5}" font-size="7" fill="#334155" font-family="system-ui,monospace" letter-spacing="1">${label}</text>`;
  });

  // Edges based on ACTUAL dependencies — progressive reveal
  nodes.forEach(node => {
    if (!node.deps) return;
    node.deps.forEach(depId => {
      const fromPos = pos[depId];
      const toPos   = pos[node.id];
      if (!fromPos || !toPos) return;

      const fromNode = nodes.find(n => n.id === depId);
      const fromStatus = fromNode ? fromNode.status : "pending";
      const toStatus   = node.status;

      const fromDone   = fromStatus === "done" || fromStatus === "skipped";
      const fromActive = fromStatus === "running";
      const toActive   = toStatus === "running";
      const toDone     = toStatus === "done" || toStatus === "skipped";
      const toFailed   = toStatus === "failed";

      // Progressive reveal: hide edge if BOTH endpoints are pending (untouched)
      const fromTouched = fromDone || fromActive;
      const toTouched   = toDone || toActive || toFailed;
      if (!fromTouched && !toTouched) return;

      const bothDone = fromDone && toDone;
      const active   = toActive;

      const col    = toFailed  ? "#f87171"
                   : active    ? agentColor(node.agent)
                   : bothDone  ? "#34d399"
                   : fromDone  ? "#6c8ef7"
                   :             "#475569";
      const op     = active    ? 0.95
                   : bothDone  ? 0.75
                   : fromDone  ? 0.5
                   :             0.3;
      const sw     = active    ? 2.5
                   : bothDone  ? 2
                   : fromDone  ? 1.8
                   :             1.2;
      const mid    = (fromPos.y + toPos.y) / 2;
      const marker = toFailed ? "arr-red" : active ? "arr-blue" : fromDone ? "arr-green" : "arr";

      html += `<path d="M${fromPos.x},${fromPos.y+R} C${fromPos.x},${mid} ${toPos.x},${mid} ${toPos.x},${toPos.y-R}"
        fill="none" stroke="${col}" stroke-width="${sw}" opacity="${op}"
        marker-end="url(#${marker})" stroke-dasharray="${active ? '6 3' : bothDone ? '0' : fromDone ? '0' : '4 4'}">
        ${active ? `<animate attributeName="stroke-dashoffset" values="0;-18" dur="1.2s" repeatCount="indefinite"/>` : ''}
      </path>`;
    });
  });

  // Node renderer — adds data attributes for hover/click
  function dagNodeHtml(node, x, y) {
    const name    = node.agent;
    const status  = dagStatus(node);
    const entry   = agents.find(a => a.agent === name);
    const col     = agentColor(name);
    const sm      = statusMeta(status);
    const isActive  = status === "in_progress" || status === "starting";
    const isDone    = status === "complete";
    const isSkipped = node.status === "skipped";
    const isFailed  = status === "failed";
    const fill    = isActive  ? `rgba(${hexToRgb(col)},0.18)` :
                    isDone    ? `rgba(52,211,153,0.1)` :
                    isFailed  ? `rgba(248,113,113,0.1)` : "#111827";
    const stroke  = isActive  ? col : isDone ? "#34d399" : isFailed ? "#f87171" : "#1e2d45";
    const label   = (node.label || name).replace(/-/g, " ");
    const isPending = !isActive && !isDone && !isFailed && !isSkipped;
    const opacity = isSkipped ? "0.35" : isPending ? "0.45" : "1";

    let g = `<g class="dag-node" data-node-id="${node.id}" opacity="${opacity}" style="cursor:pointer"
      onmouseover="window.__dagShowTooltip(event, '${node.id}')"
      onmouseout="window.__dagHideTooltip()"
      onclick="window.__dagShowModal('${node.id}')">`;
    if (isActive) {
      g += `<circle cx="${x}" cy="${y}" r="${R+4}" fill="none" stroke="${col}" stroke-width="1" opacity="0.3">
        <animate attributeName="r" values="${R+2};${R+10};${R+2}" dur="1.8s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.4;0;0.4" dur="1.8s" repeatCount="indefinite"/>
      </circle>`;
    }
    // Invisible larger hit target for easier hover/click
    g += `<circle cx="${x}" cy="${y}" r="${R+8}" fill="transparent" class="dag-hit-target"/>`;
    g += `<circle cx="${x}" cy="${y}" r="${R}" fill="${fill}" stroke="${stroke}"
      stroke-width="${isActive ? 2.5 : 1.5}" ${isActive ? 'filter="url(#glow)"' : ''}
      ${isSkipped ? 'stroke-dasharray="4 3"' : ''}/>`;
    g += `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle" font-size="13" pointer-events="none">${agentEmoji(name)}</text>`;
    g += `<text x="${x}" y="${y+R+14}" text-anchor="middle" font-size="9" pointer-events="none"
      fill="${isActive ? col : isDone ? '#34d399' : isFailed ? '#f87171' : '#64748b'}"
      font-family="system-ui,sans-serif">${label}</text>`;
    const dotColor = sm.color;
    g += `<circle cx="${x+R-5}" cy="${y-R+5}" r="5" fill="${dotColor}" stroke="#0a0d14" stroke-width="1.5" pointer-events="none">
      ${isActive ? `<animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite"/>` : ''}
    </circle>`;
    g += `</g>`;
    return g;
  }

  // Draw nodes
  for (let i = layerKeys.length - 1; i >= 0; i--) {
    for (const node of layers[layerKeys[i]]) {
      const p = pos[node.id];
      html += dagNodeHtml(node, p.x, p.y);
    }
  }

  svg.innerHTML = html;

  // ── Attach hover + click handlers to rendered nodes ──
  // Smart agent matching: STM uses "developer (dev-01)" but DAG has id="dev-01" agent="developer"
  function findAgentEntry(node) {
    if (!agents || agents.length === 0) return null;
    // 1. Exact match by node.id in parentheses: "developer (dev-01)" or "security" etc.
    let entry = agents.find(a => {
      const m = a.agent.match(/\(([^)]+)\)/);
      return m && m[1] === node.id;
    });
    if (entry) return entry;
    // 2. Exact match on agent type (works when only one of that type, e.g., "architect")
    const sameType = agents.filter(a => a.agent === node.agent || a.agent.startsWith(node.agent));
    if (sameType.length === 1) return sameType[0];
    // 3. Match by unit field if present
    entry = agents.find(a => a.unit && a.unit === node.id);
    if (entry) return entry;
    // 4. Match where agent name contains the node label
    entry = agents.find(a => a.agent.toLowerCase().includes(node.id.toLowerCase()));
    if (entry) return entry;
    return null;
  }

  window.__dagNodeMeta = {};
  nodes.forEach(node => {
    window.__dagNodeMeta[node.id] = { node, entry: findAgentEntry(node) };
  });

}

// ── Global handlers for DAG node hover/click — called via inline SVG attributes ──
// (Inline handlers survive innerHTML replacement; no event delegation needed)
window.__dagShowTooltip = function(evt, nodeId) {
  const meta = window.__dagNodeMeta?.[nodeId];
  if (!meta) return;
  const tt = document.getElementById('dag-tooltip');
  const n = meta.node;
  const a = meta.entry;
  const statusColors = {done:'#34d399',running:'#6c8ef7',failed:'#f87171',skipped:'#64748b',pending:'#334155'};
  const sCol = statusColors[n.status] || '#475569';
  let html = `<div class="tt-agent">${agentEmoji(n.agent)} ${(n.label||n.agent).replace(/-/g,' ')}</div>`;
  html += `<span class="tt-status" style="background:${sCol}22;color:${sCol};border:1px solid ${sCol}44">${n.status}</span>`;
  if (a && a.findings) {
    const preview = a.findings.length > 180 ? a.findings.slice(0,180) + '…' : a.findings;
    html += `<div class="tt-findings">${preview}</div>`;
  } else if (n.status === 'pending') {
    const desc = n.description ? n.description.slice(0,120) + (n.description.length > 120 ? '…' : '') : '';
    html += `<div class="tt-findings" style="color:#475569">${desc || 'Waiting for dependencies…'}</div>`;
  } else if (n.status === 'running') {
    const desc = n.description ? n.description.slice(0,120) + (n.description.length > 120 ? '…' : '') : '';
    html += `<div class="tt-findings" style="color:#6c8ef7">${desc || 'Agent is working…'}</div>`;
  } else if (n.status === 'done' && !a) {
    html += `<div class="tt-findings" style="color:#34d399">✅ Completed</div>`;
  }
  if (a && a.model) {
    html += `<div class="tt-meta">Model: ${a.model}</div>`;
  }
  tt.innerHTML = html;
  tt.style.display = 'block';
  // Position near the node
  const g = evt.currentTarget;
  const rect = g.getBoundingClientRect();
  tt.style.left = Math.min(rect.left + rect.width/2 - 150, window.innerWidth - 360) + 'px';
  tt.style.top  = (rect.bottom + 10) + 'px';
};

window.__dagHideTooltip = function() {
  document.getElementById('dag-tooltip').style.display = 'none';
};

window.__dagShowModal = function(nodeId) {
  const meta = window.__dagNodeMeta?.[nodeId];
  if (!meta) return;
  document.getElementById('dag-tooltip').style.display = 'none';
  const n = meta.node;
  const a = meta.entry;
  const statusColors = {done:'#34d399',running:'#6c8ef7',failed:'#f87171',skipped:'#64748b',pending:'#334155'};
  const sCol = statusColors[n.status] || '#475569';

  document.getElementById('modal-title').innerHTML =
    `${agentEmoji(n.agent)} ${(n.label||n.agent).replace(/-/g,' ')}`;

  let body = '';

  // Status badge
  body += `<div class="detail-row"><span class="detail-label">Status</span>
    <span class="detail-value"><span class="badge" style="background:${sCol}22;color:${sCol};border:1px solid ${sCol}44">${n.status}</span></span></div>`;

  // Agent type
  body += `<div class="detail-row"><span class="detail-label">Agent</span>
    <span class="detail-value">${n.agent}</span></div>`;

  // Model
  if (a && a.model) {
    body += `<div class="detail-row"><span class="detail-label">Model</span>
      <span class="detail-value">${a.model}</span></div>`;
  }

  // Tool usage
  if (a && (a.tool_used || a.tool_max)) {
    const used = a.tool_used || 0;
    const max  = a.tool_max || '?';
    const pct  = a.tool_max ? Math.round(used/a.tool_max*100) : 0;
    const barCol = pct > 75 ? '#f87171' : pct > 50 ? '#fbbf24' : '#34d399';
    body += `<div class="detail-row"><span class="detail-label">Tools</span>
      <span class="detail-value">${used}/${max} calls
        <div style="background:#1e2d45;height:4px;border-radius:2px;width:120px;margin-top:4px">
          <div style="background:${barCol};height:4px;border-radius:2px;width:${pct}%"></div>
        </div>
      </span></div>`;
  }

  // Dependencies
  if (n.deps && n.deps.length > 0) {
    body += `<div class="detail-row"><span class="detail-label">Depends</span>
      <span class="detail-value">${n.deps.map(d => `<span class="badge" style="background:#1e2d45;color:#64748b">${d}</span>`).join(' ')}</span></div>`;
  }

  // Timing
  if (n.started_at) {
    body += `<div class="detail-row"><span class="detail-label">Started</span>
      <span class="detail-value" style="font-family:'SF Mono',monospace;font-size:0.74rem">${new Date(n.started_at).toLocaleTimeString()}</span></div>`;
  }
  if (n.completed_at) {
    body += `<div class="detail-row"><span class="detail-label">Finished</span>
      <span class="detail-value" style="font-family:'SF Mono',monospace;font-size:0.74rem">${new Date(n.completed_at).toLocaleTimeString()}</span></div>`;
  }
  if (n.started_at && n.completed_at) {
    const dur = Math.round((new Date(n.completed_at) - new Date(n.started_at)) / 1000);
    body += `<div class="detail-row"><span class="detail-label">Duration</span>
      <span class="detail-value">${dur}s</span></div>`;
  }

  // Findings (main content)
  if (a && a.findings) {
    body += `<div class="detail-row" style="flex-direction:column;gap:4px"><span class="detail-label">Findings</span>
      <span class="detail-value findings">${a.findings}</span></div>`;
  } else if (n.status === 'pending') {
    const desc = n.description || '';
    body += `<div class="detail-row" style="flex-direction:column;gap:4px"><span class="detail-label">Status</span>
      <span class="detail-value findings" style="color:#334155">⏳ Waiting for dependencies to complete…</span></div>`;
    if (desc) {
      body += `<div class="detail-row" style="flex-direction:column;gap:4px"><span class="detail-label">Task Brief</span>
        <span class="detail-value findings" style="color:#64748b">${desc}</span></div>`;
    }
  } else if (n.status === 'running') {
    const desc = n.description || '';
    const elapsed = n.started_at ? Math.round((Date.now() - new Date(n.started_at).getTime()) / 1000) : 0;
    body += `<div class="detail-row" style="flex-direction:column;gap:4px"><span class="detail-label">Live Status</span>
      <span class="detail-value findings" style="color:#6c8ef7">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <span style="display:inline-block;width:8px;height:8px;background:#6c8ef7;border-radius:50%;animation:pulse 1.2s infinite"></span>
          Agent is working… ${elapsed > 0 ? '(' + elapsed + 's elapsed)' : ''}
        </div>
        ${desc ? '<div style="color:#94a3b8;margin-top:4px;padding-top:8px;border-top:1px solid #1e2d45"><strong style="color:#64748b;font-size:0.7rem;text-transform:uppercase">Task Brief:</strong><br/>' + desc + '</div>' : ''}
      </span></div>`;
  } else if (n.status === 'done' && !a) {
    const desc = n.description || 'Completed successfully';
    body += `<div class="detail-row" style="flex-direction:column;gap:4px"><span class="detail-label">Output</span>
      <span class="detail-value findings" style="color:#34d399">✅ ${desc}</span></div>`;
  }

  // Decisions
  if (a && a.decisions) {
    body += `<div class="detail-row" style="flex-direction:column;gap:4px"><span class="detail-label">Decisions</span>
      <span class="detail-value findings" style="border-color:#fbbf2433">${a.decisions}</span></div>`;
  }

  // Files
  if (a && a.files && a.files.length > 0) {
    const fileItems = a.files.map(f => `<li>📄 ${f}</li>`).join('');
    body += `<div class="detail-row" style="flex-direction:column;gap:4px"><span class="detail-label">Files</span>
      <ul class="files-list">${fileItems}</ul></div>`;
  }

  // Next step
  if (a && a.next) {
    body += `<div class="detail-row"><span class="detail-label">Next</span>
      <span class="detail-value" style="color:#fbbf24">${a.next}</span></div>`;
  }

  // Failed reason
  if (n.failed_reason) {
    body += `<div class="detail-row" style="flex-direction:column;gap:4px"><span class="detail-label">Error</span>
      <span class="detail-value findings" style="color:#f87171;border-color:#f8717133">${n.failed_reason}</span></div>`;
  }

  document.getElementById('modal-body').innerHTML = body;
  document.getElementById('dag-modal-overlay').classList.add('visible');
};

function hexToRgb(hex) {
  const r = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return r ? `${parseInt(r[1],16)},${parseInt(r[2],16)},${parseInt(r[3],16)}` : "108,142,247";
}

// ── Resource monitor constants ────────────────────────────────────────────────
const MODEL_CTX = {
  "claude-opus-4.7": 200000,
  "claude-opus-4.6": 200000,
  "claude-sonnet-4.6": 200000,
  "claude-sonnet-4.5": 200000,
  "claude-haiku-4.5": 200000,
  "gpt-5.4":   128000,
  "gpt-5.4-mini": 128000,
  "gpt-5.3-codex": 128000,
  "gpt-5.2-codex": 128000,
  "gpt-5.2":   128000,
  "gpt-5-mini":128000,
  "gpt-4.1":   128000,
};
function ctxLimit(model) {
  if (!model) return null;
  const key = Object.keys(MODEL_CTX).find(k => model.toLowerCase().includes(k));
  return key ? MODEL_CTX[key] : null;
}
function gaugeColor(pct, warnAt=60, critAt=85) {
  if (pct >= critAt) return "var(--red)";
  if (pct >= warnAt) return "var(--yellow)";
  return "var(--green)";
}
function warnBadge(pct) {
  if (pct >= 90) return `<span class="res-warn-badge" style="background:rgba(248,113,113,.18);color:var(--red);border:1px solid rgba(248,113,113,.3)">🔴 CRIT</span>`;
  if (pct >= 75) return `<span class="res-warn-badge" style="background:rgba(251,191,36,.12);color:var(--yellow);border:1px solid rgba(251,191,36,.28)">⚠ HIGH</span>`;
  return "";
}
function gaugeHtml(label, pct, valText) {
  const col = gaugeColor(pct);
  return `<div class="gauge-row">
    <span class="gauge-lbl">${label}</span>
    <div class="gauge-track"><div class="gauge-fill" style="width:${Math.min(pct,100).toFixed(1)}%;background:${col}"></div></div>
    <span class="gauge-val" style="color:${col}">${valText}</span>
  </div>`;
}

// ── Agent cards ───────────────────────────────────────────────────────────────
const STALE_MS = 5 * 60 * 1000; // 5 minutes

function isStale(isoTs) {
  try { return (Date.now() - new Date(isoTs)) > STALE_MS; } catch { return false; }
}

function inlineGauges(a) {
  let html = "";
  // Tool gauge
  if (a.tool_used != null && a.tool_max != null) {
    const pct = (a.tool_used / a.tool_max) * 100;
    html += gaugeHtml("Tools", pct, `${a.tool_used}/${a.tool_max} calls`);
  }
  // Context gauge — prefer explicit context_max from N/M format, else model-based limit
  if (a.context_tokens != null || a.context_pct != null) {
    const limit = a.context_max || ctxLimit(a.model);
    let pct = a.context_pct;
    let valText;
    if (pct == null && a.context_tokens != null && limit) {
      pct = (a.context_tokens / limit) * 100;
    }
    if (a.context_tokens != null) {
      const kk = a.context_tokens >= 1000 ? `~${(a.context_tokens/1000).toFixed(0)}k` : a.context_tokens;
      valText = limit ? `${kk} / ${(limit/1000).toFixed(0)}k tokens` : `${kk} tokens`;
    } else if (pct != null) {
      valText = `${pct.toFixed(0)}%`;
    }
    if (pct != null) {
      html += gaugeHtml("Ctx", pct, valText || `${pct.toFixed(0)}%`);
    }
  }
  if (!html) return "";
  return `<div class="card-gauges">${html}</div>`;
}

function renderAgentCards(agents) {
  const grid = document.getElementById("agent-grid");
  if (!agents || agents.length === 0) {
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">🤖</div>
      <p>No agent activity yet.<br>Waiting for write-stm.sh entries…</p></div>`;
    return;
  }

  grid.innerHTML = agents.map(a => {
    const col = agentColor(a.agent);
    const sm  = statusMeta(a.status);
    const isActive = a.status === "in_progress" || a.status === "starting";
    const stale = !isActive && isStale(a.timestamp);
    const modelPill = a.model ? `<span style="font-size:0.63rem;color:var(--text3);background:rgba(167,139,250,.1);border:1px solid rgba(167,139,250,.25);border-radius:4px;padding:1px 5px;font-family:var(--mono);margin-left:auto">${escHtml(a.model)}</span>` : '';
    const parentBadge = a.parent ? `<span style="font-size:0.6rem;color:var(--text3);background:rgba(96,165,250,.1);border:1px solid rgba(96,165,250,.2);border-radius:3px;padding:0 4px;margin-left:4px">↑ ${escHtml(a.parent)}</span>` : '';
    const unitBadge = a.unit ? `<span style="font-size:0.6rem;color:var(--text3);background:rgba(250,204,21,.1);border:1px solid rgba(250,204,21,.2);border-radius:3px;padding:0 4px;margin-left:4px">Unit ${escHtml(a.unit)}</span>` : '';
    return `<div class="agent-card ${isActive ? 'active' : ''} ${stale ? 'stale' : ''}"
      style="--agent-color:${col}">
      <div class="card-header">
        <div class="card-ring">${agentEmoji(a.agent)}</div>
        <div style="flex:1;min-width:0">
          <div class="card-name">${a.agent}${unitBadge}${parentBadge}</div>
          <div class="card-ts">${relTime(a.timestamp)}</div>
        </div>
        ${modelPill}
      </div>
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px">
        <div class="card-status" style="color:${sm.color};border-color:${sm.color}33;background:${sm.color}18;margin-bottom:0">
          <span style="font-size:0.85rem">${sm.icon}</span> ${sm.label}
        </div>
        ${stale ? `<span class="stale-badge">⏱ stale</span>` : ''}
      </div>
      ${inlineGauges(a)}
      <div class="card-body">
        ${a.findings ? `<div class="card-findings">${escHtml(a.findings.slice(0,120))}${a.findings.length>120?'…':''}</div>` : (a.raw ? `<div class="card-findings" style="color:var(--text3)">${escHtml(summarizeRaw(a.raw))}</div>` : '')}
        ${a.files ? `<div class="card-files">📄 ${escHtml(a.files.slice(0,80))}</div>` : ''}
        ${a.next && a.next !== 'none' ? `<div style="margin-top:6px;font-size:0.72rem;color:#64748b">→ ${escHtml(a.next.slice(0,80))}</div>` : ''}
      </div>
    </div>`;
  }).join("");
}

// ── Resource sidebar ──────────────────────────────────────────────────────────
function renderResources(agents) {
  const sumEl = document.getElementById("res-summary");
  const agEl  = document.getElementById("res-agents");
  if (!sumEl || !agEl) return;

  if (!agents || agents.length === 0) {
    sumEl.innerHTML = "";
    agEl.innerHTML = `<div class="gauge-unknown" style="padding:12px 0">No agents yet</div>`;
    return;
  }

  // Summary pills: overall tool pressure + context pressure
  const withTools = agents.filter(a => a.tool_used != null && a.tool_max != null);
  const withCtx   = agents.filter(a => a.context_tokens != null || a.context_pct != null);
  const avgTool = withTools.length ? withTools.reduce((s,a) => s + a.tool_used/a.tool_max, 0) / withTools.length * 100 : null;
  let sumHtml = "";
  if (avgTool != null) {
    const col = gaugeColor(avgTool);
    sumHtml += `<div style="font-size:0.65rem;padding:3px 8px;border-radius:6px;background:${col}18;
      border:1px solid ${col}35;color:${col}">🛠 Avg tools ${avgTool.toFixed(0)}%</div>`;
  }
  const highCtx = withCtx.filter(a => {
    let pct = a.context_pct;
    if (pct == null && a.context_tokens != null) {
      const lim = ctxLimit(a.model); if (lim) pct = a.context_tokens / lim * 100;
    }
    return pct != null && pct >= 75;
  });
  if (highCtx.length) {
    sumHtml += `<div style="font-size:0.65rem;padding:3px 8px;border-radius:6px;background:rgba(248,113,113,.12);
      border:1px solid rgba(248,113,113,.28);color:var(--red)">🔴 ${highCtx.length} high ctx</div>`;
  }
  sumEl.innerHTML = sumHtml;

  // Per-agent resource rows
  agEl.innerHTML = agents.map(a => {
    const col = agentColor(a.agent);
    const sm  = statusMeta(a.status);

    // Tool gauge row
    let toolGauge = "";
    if (a.tool_used != null && a.tool_max != null) {
      const pct = (a.tool_used / a.tool_max) * 100;
      toolGauge = gaugeHtml("🛠", pct, `${a.tool_used}/${a.tool_max} calls`) + warnBadge(pct);
    } else {
      toolGauge = `<div class="gauge-unknown">no tool data</div>`;
    }

    // Context gauge row
    let ctxGauge = "";
    if (a.context_tokens != null || a.context_pct != null) {
      const limit = ctxLimit(a.model);
      let pct = a.context_pct;
      let valText;
      if (pct == null && a.context_tokens != null && limit) {
        pct = (a.context_tokens / limit) * 100;
      }
      if (a.context_tokens != null) {
        const kk = a.context_tokens >= 1000 ? `~${(a.context_tokens/1000).toFixed(0)}k` : a.context_tokens;
        valText = limit ? `${kk}/${(limit/1000).toFixed(0)}k` : `${kk} tok`;
      } else {
        valText = `${pct ? pct.toFixed(0) : '?'}%`;
      }
      if (pct != null) {
        ctxGauge = gaugeHtml("📊", pct, valText) + warnBadge(pct);
      }
    } else {
      ctxGauge = `<div class="gauge-unknown">no ctx data</div>`;
    }

    const modelPill = a.model
      ? `<span class="res-model-pill">${escHtml(a.model)}</span>` : "";

    return `<div class="res-agent">
      <div class="res-agent-name">
        <div class="res-status-dot" style="background:${sm.color}"></div>
        ${escHtml(a.agent)}
        ${modelPill}
      </div>
      ${toolGauge}
      ${ctxGauge}
    </div>`;
  }).join("");
}

// ── Timeline (append-only — entries are never removed) ────────────────────────
// Maps "agent@timestamp" → last-known is_latest value.
const tlState = new Map();

function buildTimelineEl(e) {
  const sm = statusMeta(e.status);
  const superseded = e.is_latest === false;
  const el = document.createElement("div");
  el.className = `timeline-entry${superseded ? ' superseded' : ''}`;
  el.dataset.key = `${e.agent}@${e.timestamp}`;
  el.innerHTML = `
    <div class="tl-dot" style="background:${superseded ? '#334155' : sm.color}"></div>
    <div class="tl-content">
      <div>
        <span class="tl-agent">${agentEmoji(e.agent)} ${e.agent}</span>
        <span class="tl-status" style="background:${sm.color}18;color:${sm.color}">${sm.label}</span>
        ${superseded ? `<span class="superseded-badge">history</span>` : ''}
      </div>
      ${e.findings ? `<div class="tl-findings">${escHtml(e.findings.slice(0,80))}${e.findings.length>80?'…':''}</div>` : (e.raw ? `<div class="tl-findings" style="opacity:0.7">${escHtml(summarizeRaw(e.raw).slice(0,80))}</div>` : '')}
    </div>
    <div class="tl-time">${relTime(e.timestamp)}</div>`;
  return el;
}

function renderTimeline(timeline) {
  const tl = document.getElementById("timeline");

  if (!timeline || timeline.length === 0) {
    if (!tl.querySelector('.timeline-entry')) {
      tl.innerHTML = `<div class="tl-empty" style="color:#475569;font-size:0.8rem;padding:16px 0">No activity yet</div>`;
    }
    return;
  }

  // Remove placeholder if present
  tl.querySelector('.tl-empty')?.remove();

  // Pass 1 — prepend new entries (API is newest-first; collect then prepend oldest-first)
  const newEntries = [];
  for (const e of timeline) {
    const key = `${e.agent}@${e.timestamp}`;
    if (!tlState.has(key)) {
      newEntries.push(e);
    }
  }
  // Prepend oldest-first so newest ends up at top
  for (let i = newEntries.length - 1; i >= 0; i--) {
    const e = newEntries[i];
    tl.prepend(buildTimelineEl(e));
    tlState.set(`${e.agent}@${e.timestamp}`, e.is_latest);
  }

  // Pass 2 — patch is_latest changes in-place (entry went latest → superseded)
  for (const e of timeline) {
    const key = `${e.agent}@${e.timestamp}`;
    if (tlState.get(key) !== e.is_latest) {
      const el = tl.querySelector(`[data-key="${CSS.escape(key)}"]`);
      if (el) {
        const sm = statusMeta(e.status);
        const superseded = e.is_latest === false;
        el.classList.toggle('superseded', superseded);
        el.querySelector('.tl-dot').style.background = superseded ? '#334155' : sm.color;
        const badge = el.querySelector('.superseded-badge');
        if (superseded && !badge) {
          const b = document.createElement('span');
          b.className = 'superseded-badge';
          b.textContent = 'history';
          el.querySelector('.tl-content > div')?.appendChild(b);
        } else if (!superseded && badge) {
          badge.remove();
        }
      }
      tlState.set(key, e.is_latest);
    }
  }
}

// ── STM Sections (left sidebar) ───────────────────────────────────────────────
function renderStmSections(data) {
  const el = document.getElementById("stm-sections");
  if (!el) return;
  const sections = data?.meta?.sections || {};
  const task = data?.meta?.task || data?.stm_name || "Unknown task";
  const brain = data?.meta?.brain;

  let html = `<div style="font-size:0.82rem;font-weight:600;color:var(--text);margin-bottom:6px;
    padding:8px 10px;background:var(--bg-card);border-radius:8px;border:1px solid var(--border)">
    📋 ${escHtml(task.slice(0,60))}</div>`;

  if (brain) {
    html += `<div style="font-size:0.63rem;color:var(--text3);margin-bottom:10px;padding:0 2px">
      🧠 ${escHtml(brain)}</div>`;
  }

  // Show compact section pills — skip empty sections and noise
  const skipSections = new Set(["Task Brief"]);
  for (const [name, body] of Object.entries(sections)) {
    if (skipSections.has(name)) continue;
    // Strip HTML comments from body
    const clean = (body || "").replace(/<!--[\s\S]*?-->/g, "").trim();
    if (!clean) continue;

    // For Prior Sessions, just show a count
    if (name === "Prior Sessions Today") {
      const sessionCount = (clean.match(/^### /gm) || []).length;
      html += `<div style="font-size:0.7rem;color:var(--text3);padding:4px 8px;margin-bottom:4px;
        background:rgba(148,163,184,.08);border-radius:6px;border:1px solid var(--border)">
        📚 ${sessionCount} prior session${sessionCount !== 1 ? 's' : ''} today</div>`;
      continue;
    }

    // Other sections: one-line preview
    const oneLine = clean.replace(/\n/g, " ").slice(0, 100);
    html += `<div style="font-size:0.7rem;color:var(--text3);padding:4px 8px;margin-bottom:4px;
      background:rgba(148,163,184,.08);border-radius:6px;border:1px solid var(--border);
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${escHtml(clean.slice(0,300))}">
      📄 <strong style="color:var(--text2)">${escHtml(name)}</strong> — ${escHtml(oneLine)}${clean.length>100?'…':''}</div>`;
  }

  el.innerHTML = html;
}

// ── Stats ─────────────────────────────────────────────────────────────────────
function renderStats(data) {
  const agents = data?.agents || [];
  const active  = agents.filter(a => a.status==="in_progress"||a.status==="starting").length;
  const workers = agents.filter(a => /^developer-[a-f]$/.test((a.agent||"").toLowerCase()) && (a.status==="in_progress"||a.status==="starting")).length;
  const done    = agents.filter(a => a.status==="complete").length;
  const blocked = agents.filter(a => a.status==="blocked"||a.status==="failed").length;
  document.getElementById("stat-workers").textContent = workers > 0 ? `${workers}` : "0";
  document.getElementById("stat-active").textContent = active;
  document.getElementById("stat-done").textContent   = done;
  document.getElementById("stat-blocked").textContent= blocked;
  document.getElementById("stat-entries").textContent = data?.entry_count || 0;
}

// ── Clock ─────────────────────────────────────────────────────────────────────
function updateClock() {
  document.getElementById("topbar-time").textContent =
    new Date().toLocaleTimeString([], {hour12:false});
}
setInterval(updateClock, 1000);
updateClock();

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

// Extract a short summary from raw STM body when no Findings: line exists
function summarizeRaw(raw) {
  const skip = /^(status:|phase:|findings:|files:|decisions:|next:|parent:|unit:|tool_calls:|context:|model:)/i;
  const lines = raw.split('\n').filter(l => l.trim() && !skip.test(l.trim()));
  return lines.slice(0, 2).join(' · ').slice(0, 120) + (lines.length > 2 ? '…' : '');
}

// ── Main poll loop ────────────────────────────────────────────────────────────
let lastUpdate = null;
let lastGoodData = null;   // persist last known good state — prevents flicker on transient errors
let errorCount = 0;        // only show "no active STM" after sustained errors
let currentSelectedId = null;
let showAllWorkflows = false;

function toggleShowAll() {
  showAllWorkflows = !showAllWorkflows;
  fetchStatus();
}

// Scroll preservation — save positions before render, restore after
function saveScrollPositions() {
  return {
    main: document.getElementById("main")?.scrollTop || 0,
    right: document.getElementById("rightpanel")?.scrollTop || 0,
    sidebar: document.getElementById("sidebar")?.scrollTop || 0,
  };
}
function restoreScrollPositions(pos) {
  const m = document.getElementById("main");
  const r = document.getElementById("rightpanel");
  const s = document.getElementById("sidebar");
  if (m) m.scrollTop = pos.main;
  if (r) r.scrollTop = pos.right;
  if (s) s.scrollTop = pos.sidebar;
}

function renderTabBar(workflows, activeId, selectedId) {
  const bar = document.getElementById("tab-bar");
  if (!bar || !workflows) { if (bar) bar.innerHTML = ""; return; }
  const sixHoursAgo = Date.now() / 1000 - 6 * 3600;
  let visible;
  if (showAllWorkflows) {
    // Show all workflows with entries in the last 6 hours
    visible = workflows.filter(w =>
      (w.entry_count > 0 && w.last_modified > sixHoursAgo) || w.uuid === activeId || w.uuid === selectedId
    );
  } else {
    // Show workflows with running agents OR modified in last 5 minutes, plus active/selected
    const fiveMinAgo = Date.now() / 1000 - 5 * 60;
    visible = workflows.filter(w =>
      ((w.has_running_agents || w.last_modified > fiveMinAgo) && w.entry_count > 0 && w.last_modified > sixHoursAgo)
      || w.uuid === activeId || w.uuid === selectedId
    );
  }
  // Count how many are hidden for the toggle label
  const allRecent = workflows.filter(w => w.entry_count > 0 && w.last_modified > sixHoursAgo);
  const hiddenCount = allRecent.length - visible.length;
  let html = "";
  for (const w of visible) {
    const isSelected = w.uuid === selectedId;
    const isActive = w.uuid === activeId;
    let label = w.slug.replace(/^\d{4}-\d{2}-\d{2}-/, "").replace(/-/g, " ");
    if (label.length > 30) label = label.slice(0, 28) + "…";
    const dotClass = w.has_running_agents ? "green" : (isActive ? "green" : "gray");
    const errorBadge = w.consecutive_errors >= 10 ? ' <span class="tab-badge">🔴</span>'
                     : w.consecutive_errors >= 3  ? ' <span class="tab-badge">⚠️</span>'
                     : "";
    const entries = w.entry_count > 0 ? ` <span class="tab-entries">(${w.entry_count})</span>` : "";
    html += `<div class="tab${isSelected ? ' active' : ''}" data-uuid="${w.uuid}" onclick="selectTab('${w.uuid}')">`;
    html += `<span class="tab-dot ${dotClass}"></span>`;
    html += `${escHtml(label)}${entries}${errorBadge}`;
    html += `</div>`;
  }
  // Toggle button
  const toggleLabel = showAllWorkflows ? "Active only" : `Show all (${hiddenCount > 0 ? '+' + hiddenCount : '0'} more)`;
  html += `<div class="tab-toggle${showAllWorkflows ? ' on' : ''}" onclick="toggleShowAll()">${toggleLabel}</div>`;
  bar.innerHTML = html;
}

async function selectTab(uuid) {
  try {
    const r = await fetch("/api/v2/select/" + uuid);
    if (r.ok) {
      currentSelectedId = uuid;
      fetchStatus(); // immediately refresh
    }
  } catch(e) { /* silent */ }
}

async function fetchStatus() {
  try {
    const r = await fetch("/api/v2/status");
    if (!r.ok) throw new Error(r.status);
    const v2 = await r.json();

    // v2 wraps the selected workflow's data under "selected"
    const data = v2.selected;
    const workflows = v2.workflows || [];
    currentSelectedId = v2.selected_workflow_id;

    // Always render tabs first — even if selected data is empty
    renderTabBar(workflows, v2.active_workflow_id, v2.selected_workflow_id);

    if (!data || (!data.agents?.length && !data.dag)) {
      // No data for selected workflow
      errorCount++;
      if (errorCount >= 5 || !lastGoodData) {
        // Only show "No Active STM" if there are no tabs at all
        const hasWorkflows = workflows.some(w => w.entry_count > 0);
        if (!hasWorkflows) {
          document.getElementById("no-stm").classList.add("show");
        }
      }
      document.getElementById("conn-dot").style.background = "#fbbf24";
      document.getElementById("conn-dot").style.boxShadow  = "0 0 6px #fbbf24";
      return;
    }

    // Good data — reset error tracking
    errorCount = 0;
    lastGoodData = data;
    document.getElementById("no-stm").classList.remove("show");

    document.getElementById("task-name").textContent = data.meta?.task || data.stm_name || "";
    document.getElementById("conn-dot").style.background = "#34d399";
    document.getElementById("conn-dot").style.boxShadow  = "0 0 6px #34d399";

    const scrollPos = saveScrollPositions();
    window.__latestData = data;
    renderStats(data);
    renderStmSections(data);
    drawPipeline(data.agents, data.timeline);
    renderAgentCards(data.agents);
    renderTimeline(data.timeline);
    renderResources(data.agents);
    restoreScrollPositions(scrollPos);
  } catch(e) {
    errorCount++;
    document.getElementById("conn-dot").style.background = "#f87171";
    document.getElementById("conn-dot").style.boxShadow  = "0 0 6px #f87171";
  }
}

fetchStatus();
setInterval(fetchStatus, 1000);

// Close modal on Escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.getElementById('dag-modal-overlay').classList.remove('visible');
  }
});
</script>
</body>
</html>
"""


class DashboardServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class AgentDashboardHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass  # silence access logs

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_html()
        elif self.path == "/api/status":
            self._serve_status()
        elif self.path == "/api/v2/status":
            self._serve_v2_status()
        elif self.path.startswith("/api/v2/select/"):
            uuid_str = self.path[len("/api/v2/select/"):]
            self._serve_v2_select(uuid_str)
        elif self.path == "/health":
            self._serve_health()
        else:
            self.send_error(404)

    def _serve_html(self):
        body = DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_status(self):
        with _snapshot_lock:
            snap = _current_snapshot
        if snap is None:
            payload = {"error": "No active STM found", "agents": [], "timeline": [], "meta": {}}
        else:
            payload = snap.data
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_v2_status(self):
        """Multi-workflow API: all workflows summary + selected workflow full data."""
        t0 = time.monotonic()
        if _workflow_registry is None:
            self._json_response({"error": "registry not initialized"}, 503)
            return

        state = _workflow_registry.get_state_snapshot()
        sel_id = state.selected_workflow_id or state.active_workflow_id

        # Build workflow summaries (shallow copy under lock already done)
        workflow_list = []
        for uid in state.tab_order:
            wf = state.workflows.get(uid)
            if not wf:
                continue
            # Check if workflow has any non-complete agents
            agent_latest: dict[str, str] = {}
            for e in wf.entries:
                agent_latest[e["agent"]] = e.get("status", "")
            # Infer implied completion for has_running check
            if agent_latest:
                _pipeline_done = any(s == "complete" for s in agent_latest.values())
                if _pipeline_done:
                    _latest_done_ts = max(
                        (e["timestamp"] for e in wf.entries if e.get("status") == "complete"),
                        default="",
                    )
                    for e in wf.entries:
                        ag = e["agent"]
                        if (
                            agent_latest.get(ag) == "in_progress"
                            and e["timestamp"] < _latest_done_ts
                            and e.get("status") == "in_progress"
                        ):
                            agent_latest[ag] = "complete"
            has_running = any(s in ("in_progress", "starting", "blocked")
                             for s in agent_latest.values())
            workflow_list.append({
                "uuid":               uid,
                "slug":               wf.identity.slug,
                "created_at":         wf.identity.created_at,
                "is_active":          uid == state.active_workflow_id,
                "is_healthy":         wf.parse_ok,
                "consecutive_errors": wf.consecutive_errors,
                "last_error":         wf.last_error,
                "entry_count":        len(wf.entries),
                "agent_count":        len(set(agent_latest.keys())),
                "last_modified":      wf.file_mtime,
                "has_running_agents": has_running,
            })

        # Build selected workflow full data
        selected_data = None
        if sel_id and sel_id in state.workflows:
            wf = state.workflows[sel_id]
            # Bump LRU on serve
            _workflow_registry.bump_accessed(sel_id)

            # Build v1-shaped data for the selected workflow
            agent_latest = {}
            for e in wf.entries:
                agent_latest[e["agent"]] = e

            # Infer implied completion (same logic as other code paths)
            if agent_latest:
                _pipeline_done = any(
                    e["status"] == "complete" for e in agent_latest.values()
                )
                if _pipeline_done:
                    _latest_done_ts = max(
                        (e["timestamp"] for e in agent_latest.values() if e["status"] == "complete"),
                        default="",
                    )
                    for e in agent_latest.values():
                        if (
                            e["status"] == "in_progress"
                            and e["timestamp"] < _latest_done_ts
                        ):
                            e["status"] = "complete"
                            e["_implied_complete"] = True

            agents_sorted = sorted(agent_latest.values(), key=lambda a: a["timestamp"], reverse=True)
            latest_ts = {a["agent"]: a["timestamp"] for a in agents_sorted}
            timeline = list(reversed(wf.entries[-40:]))
            for e in timeline:
                e["is_latest"] = (e["timestamp"] == latest_ts.get(e["agent"]))

            stm_path = wf.identity.directory / STM_FILENAME
            selected_data = {
                "stm_path":    str(stm_path),
                "stm_name":    re.sub(r"^\d{4}[-\s]\d{2}[-\s]\d{2}[-\s]", "",
                                      stm_path.parent.name.replace("-", " ")).title(),
                "meta":        wf.meta,
                "agents":      agents_sorted,
                "timeline":    timeline,
                "entry_count": len(wf.entries),
                "updated_at":  datetime.now(timezone.utc).isoformat(),
            }
            # Attach DAG if present
            dag_path = wf.identity.directory / "pipeline-dag.json"
            if dag_path.exists():
                try:
                    selected_data["dag"] = json.loads(dag_path.read_text(encoding="utf-8"))
                except Exception:
                    selected_data["dag"] = None

        payload = {
            "active_workflow_id":   state.active_workflow_id,
            "selected_workflow_id": sel_id,
            "workflows":            workflow_list,
            "selected":             selected_data,
            "poll_interval_ms":     2000,
            "server_uptime_s":      round(time.monotonic() - _start_time, 1),
        }

        elapsed_ms = round((time.monotonic() - t0) * 1000)
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Poll-Duration-Ms", str(elapsed_ms))
        self.end_headers()
        self.wfile.write(body)

    def _serve_v2_select(self, uuid_str: str):
        """Set selected workflow tab. Returns 404 if UUID not found."""
        if _workflow_registry is None:
            self._json_response({"error": "registry not initialized"}, 503)
            return

        # Validate UUID format
        if not UUID_RE.match(uuid_str):
            self._json_response({"error": "invalid UUID format"}, 400)
            return

        ok = _workflow_registry.select_workflow(uuid_str)
        if not ok:
            self._json_response({"error": "workflow not found", "uuid": uuid_str}, 404)
            return

        self._json_response({"ok": True, "selected": uuid_str})

    def _json_response(self, payload: dict, status: int = 200):
        """Helper: send a JSON response."""
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_health(self):
        with _snapshot_lock:
            snap = _current_snapshot

        # Extended health with workflow stats
        wf_count = 0
        error_wf_count = 0
        active_id = None
        if _workflow_registry:
            state = _workflow_registry.get_state_snapshot()
            wf_count = len(state.workflows)
            error_wf_count = sum(1 for wf in state.workflows.values() if not wf.parse_ok)
            active_id = state.active_workflow_id

        payload = {
            "status":              "ok",
            "pid":                 os.getpid(),
            "ready":               snap is not None,
            "active_stm_path":     str(snap.stm_path) if snap else None,
            "last_parse_mtime":    snap.mtime if snap else None,
            "uptime_s":            round(time.monotonic() - _start_time, 1),
            "workflow_count":      wf_count,
            "active_workflow_id":  active_id,
            "error_workflows":     error_wf_count,
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    global _exit_code, _pinned_stm_path, _workflow_registry, _workflow_poller

    parser = argparse.ArgumentParser(description="Agent Visibility Dashboard")
    parser.add_argument("--stm",     help="Path to short-term-memory.md (default: auto-detect)")
    parser.add_argument("--port",    type=int, default=PORT)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    # ── Singleton: acquire OS-level exclusive lock ────────────────────────────
    if not _acquire_singleton():
        deadline = time.monotonic() + 10.0
        healthy = False
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://localhost:{args.port}/health", timeout=2
                ) as resp:
                    health = json.loads(resp.read())
                    if health.get("status") == "ok":
                        healthy = True
                        break
            except Exception:
                pass
            time.sleep(0.5)
        if healthy:
            print(f"[agent-dashboard] healthy copy running on :{args.port} — exiting (no restart)")
            sys.exit(0)   # SuccessfulExit → launchd does NOT restart
        else:
            print(f"[agent-dashboard] lock held but /health unresponsive — will retry", file=sys.stderr)
            sys.exit(2)   # launchd restarts after ThrottleInterval

    # ── Ensure STM dir exists (never fail on missing dir) ─────────────────────
    STM_DIR.mkdir(parents=True, exist_ok=True)

    # ── Optional pinned STM path ──────────────────────────────────────────────
    if args.stm:
        p = Path(args.stm).expanduser().resolve()
        if not p.exists():
            print(f"[agent-dashboard] STM file not found: {p}", file=sys.stderr)
            _release_singleton()
            sys.exit(2)
        _pinned_stm_path = p

    # ── Signal handlers ───────────────────────────────────────────────────────
    def _sigterm(signum, frame):
        _shutdown_event.set()           # exit(1) → launchd restarts

    def _sigusr1(signum, frame):
        global _exit_code
        _exit_code = 0                  # operator stop → exit(0) → launchd does NOT restart
        _shutdown_event.set()

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGUSR1, _sigusr1)

    # ── Eager first refresh before binding ───────────────────────────────────
    try:
        _do_refresh()
    except Exception:
        pass

    # ── WorkflowRegistry + WorkflowPoller (multi-workflow support) ─────────
    _workflow_registry = WorkflowRegistry(STM_DIR)
    try:
        _workflow_registry.discover()  # eager first discovery
    except Exception:
        pass
    _workflow_poller = WorkflowPoller(_workflow_registry, _shutdown_event)
    _workflow_poller.start()

    # ── Legacy background refresh thread (v1 compat fallback) ─────────────
    refresh_thread = threading.Thread(target=_refresh_loop, daemon=True, name="stm-refresh")
    refresh_thread.start()

    # ── Bind HTTP server ──────────────────────────────────────────────────────
    try:
        server = DashboardServer(("", args.port), AgentDashboardHandler)
    except OSError as e:
        print(f"[agent-dashboard] cannot bind :{args.port}: {e}", file=sys.stderr)
        _release_singleton()
        sys.exit(2)

    url = f"http://localhost:{args.port}"
    wf_count = len(_workflow_registry.get_state_snapshot().workflows) if _workflow_registry else 0
    print(f"⚡ Agent Dashboard running at {url}")
    print(f"   STM: {'auto-detect (.active symlink + mtime scan)' if not args.stm else args.stm}")
    print(f"   Workflows: {wf_count} discovered")
    print(f"   SIGTERM=restart · SIGUSR1=graceful-stop-no-restart")

    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    # ── Serve until shutdown signal ───────────────────────────────────────────
    server_thread = threading.Thread(target=server.serve_forever, daemon=True, name="http-server")
    server_thread.start()

    _shutdown_event.wait()

    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass
    finally:
        _release_singleton()

    sys.exit(_exit_code)


if __name__ == "__main__":
    main()

