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
import http.server
import json
import os
import re
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

STM_DIR = Path.home() / ".copilot" / "stm"

AGENT_COLORS = {
    "orchestrator":          "#6c8ef7",
    "developer":             "#34d399",
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


_stm_cache: dict = {"path": None, "expires": 0.0}

def find_active_stm() -> Path | None:
    """Find the most recently modified STM file. Caches result for 10s to prevent flicker."""
    import time
    now = time.monotonic()
    if now < _stm_cache["expires"] and _stm_cache["path"] is not None:
        p = _stm_cache["path"]
        if p.exists():
            return p
    if not STM_DIR.exists():
        return None
    candidates = sorted(
        [p for p in STM_DIR.rglob("short-term-memory.md") if p.exists()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    result = candidates[0] if candidates else None
    if result is not None:
        _stm_cache["path"] = result
        _stm_cache["expires"] = now + 2.0  # re-evaluate every 2s for fast task switching
    return result


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

        # Multi-line findings (lines after FINDINGS: that don't start with a key)
        in_findings = False
        extra_lines = []
        keys = {"status:", "files:", "decisions:", "next:", "findings:"}
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
        tool_used = tool_max = context_tokens = context_pct = None
        model = ""
        for line in body.splitlines():
            stripped = line.strip()
            m_tool = re.match(r"TOOL_CALLS:\s*(\d+)\s*/\s*(\d+)", stripped, re.IGNORECASE)
            if m_tool:
                tool_used, tool_max = int(m_tool.group(1)), int(m_tool.group(2))
            m_ctx_k = re.match(r"CONTEXT:\s*~?(\d+(?:\.\d+)?)k\s*tokens?", stripped, re.IGNORECASE)
            if m_ctx_k:
                context_tokens = int(float(m_ctx_k.group(1)) * 1000)
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
            "model":          model,
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


def get_dashboard_data(stm_path: Path) -> dict:
    try:
        content = stm_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": str(e), "agents": [], "timeline": [], "meta": {}}

    entries = parse_stm_entries(content)
    meta = parse_stm_meta(content)

    # Deduplicate agents — keep latest entry per agent, sorted newest-first
    agent_latest: dict[str, dict] = {}
    for e in entries:
        agent_latest[e["agent"]] = e

    agents_sorted = sorted(agent_latest.values(), key=lambda a: a["timestamp"], reverse=True)

    # Build set of latest timestamps per agent for timeline superseded tagging
    latest_ts_per_agent = {a["agent"]: a["timestamp"] for a in agents_sorted}

    # Timeline — last 40 entries, newest first; tag superseded (non-latest) entries
    timeline_raw = list(reversed(entries[-40:]))
    for e in timeline_raw:
        e["is_latest"] = (e["timestamp"] == latest_ts_per_agent.get(e["agent"]))

    return {
        "stm_path":  str(stm_path),
        "stm_name":  re.sub(r"^\d{4}[-\s]\d{2}[-\s]\d{2}[-\s]", "", stm_path.parent.name.replace("-", " ")).title(),
        "meta":      meta,
        "agents":    agents_sorted,
        "timeline":  timeline_raw,
        "entry_count": len(entries),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


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

// ── Pipeline tree (orchestrator root → children row + handoff arrows) ─────────
function drawPipeline(agents, timeline) {
  const svg = document.getElementById("pipeline-svg");
  if (!agents || agents.length === 0) {
    svg.innerHTML = '<text x="50%" y="120" text-anchor="middle" fill="#334155" font-size="13">No agents yet</text>';
    return;
  }

  const W        = svg.clientWidth || 800;
  const R        = 26;
  const ROOT_Y   = 44;
  const CHILD_Y  = 150;
  const LABEL_PAD= 16;
  const ROOT     = "orchestrator";

  // Child nodes in appearance order (deduplicated)
  const seen = new Set();
  const childNodes = (timeline || [])
    .map(e => e.agent)
    .filter(n => n !== ROOT && !seen.has(n) && seen.add(n));

  // Build handoff edges from Next: field (exclude orchestrator and "none")
  const knownAgents = new Set([ROOT, ...childNodes]);
  const handoffEdges = []; // {from, to, done}
  const edgeSeen = new Set();
  for (const e of (timeline || [])) {
    const next = (e.next || "").trim().toLowerCase().replace(/^none$/, "");
    if (!next || e.agent === ROOT) continue;
    // next can be comma-separated
    for (const target of next.split(/[,\s]+/)) {
      if (!knownAgents.has(target) || target === e.agent || target === ROOT) continue;
      const key = `${e.agent}→${target}`;
      if (edgeSeen.has(key)) continue;
      edgeSeen.add(key);
      const targetEntry = agents.find(a => a.agent === target);
      const done = targetEntry?.status === "complete";
      handoffEdges.push({ from: e.agent, to: target, done });
    }
  }

  // X positions for children
  const gap    = Math.min(120, (W - 80) / Math.max(childNodes.length, 1));
  const totalW = gap * (childNodes.length - 1);
  const startX = W / 2 - totalW / 2;
  const cx     = (name) => startX + childNodes.indexOf(name) * gap;

  // SVG height: expand if we have handoff arrows below
  const H = handoffEdges.length > 0 ? 260 : 220;
  svg.setAttribute("height", H);

  let html = `<defs>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5"
      markerWidth="5" markerHeight="5" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#1e2d45"/>
    </marker>
    <marker id="arr-green" viewBox="0 0 10 10" refX="9" refY="5"
      markerWidth="5" markerHeight="5" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#34d399"/>
    </marker>
    <marker id="arr-blue" viewBox="0 0 10 10" refX="9" refY="5"
      markerWidth="5" markerHeight="5" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#6c8ef7"/>
    </marker>
  </defs>`;

  // ── Orchestrator → child edges (curved bezier, top half) ───────────────────
  for (const n of childNodes) {
    const entry      = agents.find(a => a.agent === n);
    const childActive= entry?.status === "in_progress" || entry?.status === "starting";
    const childDone  = entry?.status === "complete";
    const rootEntry  = agents.find(a => a.agent === ROOT);
    const rootActive = rootEntry?.status === "in_progress" || rootEntry?.status === "starting";

    const edgeActive = rootActive || childActive;
    const col = edgeActive ? agentColor(n) : childDone ? "#34d399" : "#1e2d45";
    const opacity = edgeActive ? 1 : childDone ? 0.45 : 0.2;
    const strokeW = edgeActive ? 2 : 1;

    const x1 = W / 2, y1 = ROOT_Y + R;
    const x2 = cx(n),  y2 = CHILD_Y - R;
    const cpY = (y1 + y2) / 2;
    const markerId = edgeActive ? "arr-blue" : childDone ? "arr-green" : "arr";

    html += `<path d="M${x1},${y1} C${x1},${cpY} ${x2},${cpY} ${x2},${y2}"
      fill="none" stroke="${col}" stroke-width="${strokeW}" opacity="${opacity}"
      marker-end="url(#${markerId})" stroke-dasharray="${edgeActive ? '6 3' : '4 3'}">
      ${edgeActive ? `<animate attributeName="stroke-dashoffset" values="0;-18" dur="1.2s" repeatCount="indefinite"/>` : ''}
    </path>`;
  }

  // ── Handoff edges (between siblings, arc below child row) ──────────────────
  const HANDOFF_Y = CHILD_Y + R + 20; // base of arc below nodes
  for (const { from, to, done } of handoffEdges) {
    const x1 = cx(from), x2 = cx(to);
    const goingRight = x2 > x1;
    // Arc depth scales with distance
    const dist  = Math.abs(x2 - x1);
    const arcDY = 18 + dist * 0.18;
    const midX  = (x1 + x2) / 2;
    const arcY  = HANDOFF_Y + arcDY;
    const col   = done ? "#34d399" : "#6c8ef7";
    const markerId = done ? "arr-green" : "arr-blue";

    // Start/end at bottom of node circles
    html += `<path d="M${x1},${CHILD_Y + R} Q${midX},${arcY} ${x2},${CHILD_Y + R}"
      fill="none" stroke="${col}" stroke-width="1.5" opacity="${done ? 0.5 : 0.85}"
      marker-end="url(#${markerId})" stroke-dasharray="5 3">
      ${!done ? `<animate attributeName="stroke-dashoffset" values="0;-16" dur="1.4s" repeatCount="indefinite"/>` : ''}
    </path>`;
  }

  // ── Node renderer ────────────────────────────────────────────────────────────
  function nodeHtml(name, x, y, entry) {
    const col      = agentColor(name);
    const sm       = statusMeta(entry?.status || "idle");
    const isActive = entry?.status === "in_progress" || entry?.status === "starting";
    const isDone   = entry?.status === "complete";
    const isBlocked= entry?.status === "blocked" || entry?.status === "failed";
    const fill     = isActive ? `rgba(${hexToRgb(col)},0.18)` :
                     isDone   ? `rgba(52,211,153,0.1)` :
                     isBlocked? `rgba(248,113,113,0.1)` : "#111827";
    const stroke   = isActive ? col : isDone ? "#34d399" : isBlocked ? "#f87171" : "#1e2d45";
    const short    = name.replace("brain-data-retrieval","brain-ret.")
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
    g += `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle" font-size="15">${agentEmoji(name)}</text>`;
    g += `<text x="${x}" y="${y+R+LABEL_PAD}" text-anchor="middle"
      font-size="9" fill="${isActive ? col : isDone ? '#34d399' : '#64748b'}"
      font-family="system-ui,sans-serif">${short}</text>`;
    if (entry) {
      g += `<circle cx="${x+R-5}" cy="${y-R+5}" r="5" fill="${sm.color}" stroke="#0a0d14" stroke-width="1.5">
        ${isActive ? `<animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite"/>` : ''}
      </circle>`;
    }
    g += `</g>`;
    return g;
  }

  // Children first, root on top
  for (const n of childNodes) {
    html += nodeHtml(n, cx(n), CHILD_Y, agents.find(a => a.agent === n));
  }
  html += nodeHtml(ROOT, W / 2, ROOT_Y, agents.find(a => a.agent === ROOT));

  svg.innerHTML = html;
}

function hexToRgb(hex) {
  const r = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return r ? `${parseInt(r[1],16)},${parseInt(r[2],16)},${parseInt(r[3],16)}` : "108,142,247";
}

// ── Agent cards ───────────────────────────────────────────────────────────────
const STALE_MS = 5 * 60 * 1000; // 5 minutes

function isStale(isoTs) {
  try { return (Date.now() - new Date(isoTs)) > STALE_MS; } catch { return false; }
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
    return `<div class="agent-card ${isActive ? 'active' : ''} ${stale ? 'stale' : ''}"
      style="--agent-color:${col}">
      <div class="card-header">
        <div class="card-ring">${agentEmoji(a.agent)}</div>
        <div>
          <div class="card-name">${a.agent}</div>
          <div class="card-ts">${relTime(a.timestamp)}</div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px">
        <div class="card-status" style="color:${sm.color};border-color:${sm.color}33;background:${sm.color}18;margin-bottom:0">
          <span style="font-size:0.85rem">${sm.icon}</span> ${sm.label}
        </div>
        ${stale ? `<span class="stale-badge">⏱ stale</span>` : ''}
      </div>
      <div class="card-body">
        ${a.findings ? `<div class="card-findings">${escHtml(a.findings.slice(0,120))}${a.findings.length>120?'…':''}</div>` : ''}
        ${a.files ? `<div class="card-files">📄 ${escHtml(a.files.slice(0,80))}</div>` : ''}
        ${a.next && a.next !== 'none' ? `<div style="margin-top:6px;font-size:0.72rem;color:#64748b">→ ${escHtml(a.next.slice(0,80))}</div>` : ''}
      </div>
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
  const done    = agents.filter(a => a.status==="complete").length;
  const blocked = agents.filter(a => a.status==="blocked"||a.status==="failed").length;
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
    renderStmSections(data);
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


class AgentDashboardHandler(http.server.BaseHTTPRequestHandler):
    stm_path: Path | None = None
    _cache: dict = {}
    _cache_mtime: float = 0.0

    def log_message(self, *args):
        pass  # silence access logs

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/status":
            self._serve_status()
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
        stm = AgentDashboardHandler.stm_path or find_active_stm()
        if stm is None:
            payload = {"error": "No active STM found", "agents": [], "timeline": [], "meta": {}}
        else:
            mtime = stm.stat().st_mtime if stm.exists() else 0
            if mtime != AgentDashboardHandler._cache_mtime:
                AgentDashboardHandler._cache = get_dashboard_data(stm)
                AgentDashboardHandler._cache_mtime = mtime
            payload = AgentDashboardHandler._cache

        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def find_free_port(start: int = 8765) -> int:
    import socket
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port in range")


def main():
    parser = argparse.ArgumentParser(description="Agent Visibility Dashboard")
    parser.add_argument("--stm", help="Path to short-term-memory.md (default: auto-detect latest)")
    parser.add_argument("--port", type=int, default=0, help="Port (default: 8765)")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    if args.stm:
        p = Path(args.stm).expanduser().resolve()
        if not p.exists():
            print(f"STM file not found: {p}", file=sys.stderr)
            sys.exit(1)
        AgentDashboardHandler.stm_path = p
    else:
        AgentDashboardHandler.stm_path = None  # auto-detect

    port = args.port if args.port else find_free_port()
    server = http.server.HTTPServer(("", port), AgentDashboardHandler)
    url = f"http://localhost:{port}"

    print(f"⚡ Agent Dashboard running at {url}")
    print(f"   STM: {'auto-detect latest' if not args.stm else args.stm}")
    print(f"   Polls every 2 seconds · Ctrl+C to stop")

    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
