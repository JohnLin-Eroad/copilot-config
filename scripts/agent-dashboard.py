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
import fcntl
import http.server
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.request
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


def parse_stm_entries(content: str) -> list[dict]:
    """Parse write-stm.sh entries: ### AGENT — TIMESTAMP\\nBody"""
    entries = []
    # Match entries written by write-stm.sh
    pattern = re.compile(
        r"### (.+?) — (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\n(.*?)(?=\n### |\Z)",
        re.DOTALL,
    )
    for m in pattern.finditer(content):
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

    agents_sorted = sorted(agent_latest.values(), key=lambda a: a["timestamp"], reverse=True)
    latest_ts_per_agent = {a["agent"]: a["timestamp"] for a in agents_sorted}

    timeline_raw = list(reversed(entries[-40:]))
    for e in timeline_raw:
        e["is_latest"] = (e["timestamp"] == latest_ts_per_agent.get(e["agent"]))

    return {
        "stm_path":    str(stm_path),
        "stm_name":    re.sub(r"^\d{4}[-\s]\d{2}[-\s]\d{2}[-\s]", "", stm_path.parent.name.replace("-", " ")).title(),
        "meta":        meta,
        "agents":      agents_sorted,
        "timeline":    timeline_raw,
        "entry_count": len(entries),
        "updated_at":  datetime.now(timezone.utc).isoformat(),
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
#app{display:grid;grid-template-rows:56px 1fr;grid-template-columns:280px 1fr 320px;height:100vh}
#topbar{grid-column:1/-1;display:flex;align-items:center;gap:16px;padding:0 24px;
  background:var(--bg-card);border-bottom:1px solid var(--border);z-index:10}
#sidebar{grid-row:2;overflow-y:auto;border-right:1px solid var(--border);padding:16px}
#main{grid-row:2;overflow-y:auto;padding:20px 24px}
#rightpanel{grid-row:2;overflow-y:auto;border-left:1px solid var(--border);padding:16px}

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

/* ── Pipeline diagram ── */
#pipeline-wrap{position:relative;overflow-x:auto;margin-bottom:24px}
#pipeline-svg{display:block;min-height:240px}

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

  <!-- Left sidebar: Resource Monitor -->
  <aside id="sidebar">
    <div class="section-label">🔋 Resources</div>
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
    <div id="pipeline-wrap">
      <svg id="pipeline-svg" width="100%" height="240"></svg>
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
// Each named pipeline stage gets its own row; parallel agents spread horizontally.
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
  if (!agents || agents.length === 0) {
    svg.innerHTML = '<text x="50%" y="120" text-anchor="middle" fill="#334155" font-size="13">No agents yet</text>';
    return;
  }

  const W       = svg.clientWidth || 900;
  const R       = 24;
  const ROW_H   = 100;
  const TOP_PAD = 40;

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
    return `<div class="agent-card ${isActive ? 'active' : ''} ${stale ? 'stale' : ''}"
      style="--agent-color:${col}">
      <div class="card-header">
        <div class="card-ring">${agentEmoji(a.agent)}</div>
        <div style="flex:1;min-width:0">
          <div class="card-name">${a.agent}</div>
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
        ${a.findings ? `<div class="card-findings">${escHtml(a.findings.slice(0,120))}${a.findings.length>120?'…':''}</div>` : ''}
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
      ${e.findings ? `<div class="tl-findings">${escHtml(e.findings.slice(0,80))}${e.findings.length>80?'…':''}</div>` : ''}
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
  const sections = data?.meta?.sections || {};
  const task = data?.meta?.task || data?.stm_name || "Unknown task";

  let html = `<div style="font-size:0.82rem;font-weight:600;color:var(--text);margin-bottom:12px;
    padding:8px;background:var(--bg-card);border-radius:8px;border:1px solid var(--border)">
    📋 ${escHtml(task.slice(0,60))}</div>`;

  if (data?.stm_path) {
    html += `<div style="font-size:0.68rem;color:var(--text3);font-family:var(--mono);
      margin-bottom:12px;word-break:break-all;line-height:1.4">${escHtml(data.stm_path)}</div>`;
  }

  for (const [name, body] of Object.entries(sections)) {
    if (!body) continue;
    const preview = body.slice(0, 400);
    html += `<div class="stm-section">
      <div class="stm-section-title">📄 ${escHtml(name)}</div>
      <div class="stm-content">${escHtml(preview)}${body.length>400?'\n…':''}</div>
    </div>`;
  }

  if (!Object.keys(sections).length) {
    html += `<div style="color:var(--text3);font-size:0.8rem">No STM sections yet</div>`;
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

// ── Main poll loop ────────────────────────────────────────────────────────────
let lastUpdate = null;
let lastGoodData = null;   // persist last known good state — prevents flicker on transient errors
let errorCount = 0;        // only show "no active STM" after sustained errors

async function fetchStatus() {
  try {
    const r = await fetch("/api/status");
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();

    if (!data || data.error) {
      // Transient: keep showing last known good data unless we've had 5+ consecutive errors
      errorCount++;
      if (errorCount >= 5 || !lastGoodData) {
        document.getElementById("no-stm").classList.add("show");
      }
      // dim the conn dot to warn but don't blank the dashboard
      document.getElementById("conn-dot").style.background = "#fbbf24";
      document.getElementById("conn-dot").style.boxShadow  = "0 0 6px #fbbf24";
      return;
    }

    // Good data — reset error tracking and hide the "no active STM" banner
    errorCount = 0;
    lastGoodData = data;
    document.getElementById("no-stm").classList.remove("show");

    document.getElementById("task-name").textContent = data.meta?.task || data.stm_name || "";
    document.getElementById("conn-dot").style.background = "#34d399";
    document.getElementById("conn-dot").style.boxShadow  = "0 0 6px #34d399";

    renderStats(data);
    drawPipeline(data.agents, data.timeline);
    renderAgentCards(data.agents);
    renderTimeline(data.timeline);
    renderResources(data.agents);
  } catch(e) {
    errorCount++;
    document.getElementById("conn-dot").style.background = "#f87171";
    document.getElementById("conn-dot").style.boxShadow  = "0 0 6px #f87171";
  }
}

fetchStatus();
setInterval(fetchStatus, 2000);
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

    def _serve_health(self):
        with _snapshot_lock:
            snap = _current_snapshot
        payload = {
            "status":           "ok",
            "pid":              os.getpid(),
            "ready":            snap is not None,
            "active_stm_path":  str(snap.stm_path) if snap else None,
            "last_parse_mtime": snap.mtime if snap else None,
            "uptime_s":         round(time.monotonic() - _start_time, 1),
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    global _exit_code, _pinned_stm_path

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

    # ── Background refresh thread ─────────────────────────────────────────────
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
    print(f"⚡ Agent Dashboard running at {url}")
    print(f"   STM: {'auto-detect (.active symlink + mtime scan)' if not args.stm else args.stm}")
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

