#!/usr/bin/env python3
"""
STM Live Dashboard

Watches a Short-Term Memory (STM) .md file and renders it as a live-updating
HTML dashboard in the browser. Sections are colour-coded by type.

Usage:
  python3 ~/.copilot/scripts/stm-dashboard.py <path-to-short-term-memory.md>
  python3 ~/.copilot/scripts/stm-dashboard.py --latest   # opens most recent STM
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
from datetime import datetime
from pathlib import Path

STM_DIR = Path.home() / ".copilot" / "stm"

# ─────────────────────────────────────────────
# Model context window sizes (tokens)
# ─────────────────────────────────────────────
MODEL_CONTEXT_WINDOWS = {
    "claude-sonnet-4.6": 200_000,
    "claude-sonnet-4.5": 200_000,
    "claude-opus-4.7":   200_000,
    "claude-opus-4.6":   200_000,
    "claude-haiku-4.5":  200_000,
    "gpt-5.3-codex":     128_000,
    "gpt-5.2-codex":     128_000,
    "gpt-5.4":           128_000,
    "gpt-5.2":           128_000,
    "gpt-4.1":           128_000,
    "gpt-5-mini":        128_000,
    "gpt-5.4-mini":      128_000,
}
DEFAULT_CONTEXT_WINDOW = 200_000

# Default tool budgets by role keyword in agent name
ROLE_TOOL_BUDGETS = {
    "explore":    999,  # unlimited
    "discovery":  999,
    "developer":    8,
    "architect":    6,
    "planner":      3,
    "critiquer":    3,
    "reviewer":     5,
    "default":      5,
}

MODEL_SHORT = {
    "claude-sonnet-4.6": "Sonnet 4.6",
    "claude-sonnet-4.5": "Sonnet 4.5",
    "claude-opus-4.7":   "Opus 4.7",
    "claude-opus-4.6":   "Opus 4.6",
    "claude-haiku-4.5":  "Haiku 4.5",
    "gpt-5.3-codex":     "Codex 5.3",
    "gpt-5.2-codex":     "Codex 5.2",
    "gpt-5.4":           "GPT-5.4",
    "gpt-5.2":           "GPT-5.2",
    "gpt-4.1":           "GPT-4.1",
    "gpt-5-mini":        "GPT-5 mini",
    "gpt-5.4-mini":      "GPT-5.4 mini",
}


def find_latest_stm() -> Path | None:
    if not STM_DIR.exists():
        return None
    candidates = sorted(
        [p for p in STM_DIR.rglob("short-term-memory.md")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def parse_stm(content: str) -> dict:
    """Parse STM markdown into sections dict."""
    sections = {}
    frontmatter = {}

    # Extract YAML frontmatter
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                frontmatter[k.strip()] = v.strip().strip('"')
        content = content[fm_match.end():]

    # Split on ## [STM] headers
    parts = re.split(r"\n## \[STM\] (.+?)(?:\n|$)", content)

    # parts[0] is the title block
    title_block = parts[0].strip()

    i = 1
    while i < len(parts) - 1:
        section_name = parts[i].strip()
        section_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        # Strip HTML comments that are just placeholders
        body = re.sub(r"<!--.*?-->", "", section_body, flags=re.DOTALL).strip()
        sections[section_name] = body
        i += 2

    return {
        "frontmatter": frontmatter,
        "title_block": title_block,
        "sections": sections,
    }


def extract_classification(task_brief: str) -> dict:
    """Pull Classification block out of Task Brief."""
    fields = {}
    block_match = re.search(r"Classification:(.*?)(?:\n\n|\Z)", task_brief, re.DOTALL)
    if block_match:
        for line in block_match.group(1).splitlines():
            m = re.match(r"\s+(\w+):\s+(.+)", line)
            if m:
                fields[m.group(1)] = m.group(2).strip()
    return fields


def extract_metrics(body: str) -> dict:
    """Extract tool call budget and context window usage from agent body text."""
    metrics = {
        "tool_used": None, "tool_max": None,
        "context_tokens": None, "context_pct": None,
        "model": None,
    }

    # TOOL_CALLS: 3/5 or TOOL_CALLS: 3 / 5
    m = re.search(r"TOOL[_\s]CALLS?:\s*(\d+)\s*/\s*(\d+)", body, re.IGNORECASE)
    if m:
        metrics["tool_used"] = int(m.group(1))
        metrics["tool_max"]  = int(m.group(2))

    # CONTEXT: ~45k tokens (22%) or CONTEXT: 22% or CONTEXT_TOKENS: 45000
    m = re.search(r"CONTEXT[_\s]TOKENS?:\s*~?(\d+)k?\b", body, re.IGNORECASE)
    if m:
        raw = int(m.group(1))
        metrics["context_tokens"] = raw * 1000 if raw < 10000 else raw

    m = re.search(r"CONTEXT:\s*~?(\d+)k\s*tokens?", body, re.IGNORECASE)
    if m:
        metrics["context_tokens"] = int(m.group(1)) * 1000

    m = re.search(r"CONTEXT:\s*(\d+)%", body, re.IGNORECASE)
    if m:
        metrics["context_pct"] = int(m.group(1))

    # MODEL: claude-sonnet-4.6
    m = re.search(r"MODEL:\s*([\w.\-]+)", body, re.IGNORECASE)
    if m:
        metrics["model"] = m.group(1).lower()

    # Compute pct from tokens if we have both
    if metrics["context_tokens"] and not metrics["context_pct"] and metrics["model"]:
        limit = MODEL_CONTEXT_WINDOWS.get(metrics["model"], DEFAULT_CONTEXT_WINDOW)
        metrics["context_pct"] = min(100, int(metrics["context_tokens"] / limit * 100))

    return metrics


def infer_tool_budget(name: str) -> int:
    """Infer default tool budget from agent name."""
    name_lower = name.lower()
    for role, budget in ROLE_TOOL_BUDGETS.items():
        if role in name_lower:
            return budget
    return ROLE_TOOL_BUDGETS["default"]


def extract_agents(contributions: str) -> list[dict]:
    """Parse agent contribution entries."""
    agents = []
    blocks = re.split(r"\n###\s+", contributions)
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        name = lines[0].strip() if lines else "Unknown"
        body = "\n".join(lines[1:]).strip()
        # Detect status
        status = "running"
        if re.search(r"status.*?✅|complete|done", body, re.IGNORECASE):
            status = "done"
        elif re.search(r"status.*?❌|failed|error", body, re.IGNORECASE):
            status = "failed"
        elif re.search(r"status.*?⚠️|warning|blocked", body, re.IGNORECASE):
            status = "warning"
        metrics = extract_metrics(body)
        # Fill tool_max from inferred budget if not explicit
        if metrics["tool_max"] is None:
            metrics["tool_max"] = infer_tool_budget(name)
        agents.append({"name": name, "body": body, "status": status, "metrics": metrics})
    return agents


def build_gauge_html(label: str, used, maximum, unit: str = "", warn: int = 60, danger: int = 80) -> str:
    """Build a mini progress bar gauge."""
    if used is None:
        return f"""<div class="gauge-row">
          <span class="gauge-label">{label}</span>
          <span class="gauge-unknown">—</span>
        </div>"""
    pct = min(100, int(used / maximum * 100)) if maximum else 0
    color = "#34d399"  # green
    if pct >= danger:
        color = "#f87171"   # red
    elif pct >= warn:
        color = "#fb923c"   # orange
    elif pct >= warn - 20:
        color = "#facc15"   # yellow
    label_str = f"{used}/{maximum} {unit}".strip() if maximum else f"{used} {unit}".strip()
    return f"""<div class="gauge-row">
      <span class="gauge-label">{label}</span>
      <div class="gauge-bar-wrap">
        <div class="gauge-bar-fill" style="width:{pct}%;background:{color}"></div>
      </div>
      <span class="gauge-value" style="color:{color}">{label_str}</span>
    </div>"""


def md_to_html(text: str) -> str:
    """Minimal markdown → HTML converter for dashboard display."""
    if not text:
        return "<em class='empty'>—</em>"

    lines = text.split("\n")
    output = []
    in_code = False
    code_lines = []
    in_list = False

    for line in lines:
        if line.startswith("```"):
            if in_code:
                output.append(
                    "<pre><code>"
                    + "\n".join(html_escape(l) for l in code_lines)
                    + "</code></pre>"
                )
                code_lines = []
                in_code = False
            else:
                in_code = True
                if in_list:
                    output.append("</ul>")
                    in_list = False
            continue

        if in_code:
            code_lines.append(line)
            continue

        # Headings
        hm = re.match(r"^(#{1,4})\s+(.+)", line)
        if hm:
            if in_list:
                output.append("</ul>")
                in_list = False
            lvl = len(hm.group(1)) + 1  # shift h1→h2 etc
            output.append(f"<h{lvl}>{inline_md(hm.group(2))}</h{lvl}>")
            continue

        # List items
        lm = re.match(r"^[-*]\s+(.+)", line)
        if lm:
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{inline_md(lm.group(1))}</li>")
            continue

        # Numbered list
        nlm = re.match(r"^\d+\.\s+(.+)", line)
        if nlm:
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{inline_md(nlm.group(1))}</li>")
            continue

        # End list on blank line
        if not line.strip() and in_list:
            output.append("</ul>")
            in_list = False

        if line.strip():
            output.append(f"<p>{inline_md(line)}</p>")
        else:
            output.append("<br>")

    if in_list:
        output.append("</ul>")
    if in_code and code_lines:
        output.append(
            "<pre><code>"
            + "\n".join(html_escape(l) for l in code_lines)
            + "</code></pre>"
        )

    return "\n".join(output)


def inline_md(text: str) -> str:
    text = html_escape(text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Inline code
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    # Emoji status markers kept as-is
    return text


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_html(stm_path: Path, parsed: dict, last_modified: float) -> str:
    fm = parsed["frontmatter"]
    sections = parsed["sections"]
    task_name = fm.get("task", stm_path.parent.name)
    created = fm.get("created", "—")
    mod_str = datetime.fromtimestamp(last_modified).strftime("%H:%M:%S")

    task_brief = sections.get("Task Brief", "")
    classification = extract_classification(task_brief)
    contributions = sections.get("Agent Contributions", "")
    agents = extract_agents(contributions)

    # Filter out meta/wrapper entries — keep only real agent blocks
    agents = [a for a in agents if not re.match(
        r"(task brief|fetch manifest|brain data|negative context|retrieval log|agent contributions)\s*[—–-]",
        a["name"], re.IGNORECASE
    )]

    brain_type = classification.get("BRAIN_TYPE", "—")
    domain     = classification.get("Domain", "—")
    blast      = classification.get("Blast", "—")
    pipeline   = classification.get("Pipeline", "—")
    task_type  = classification.get("Type", "—")

    blast_colors = {"LOW": "#34d399", "MEDIUM": "#facc15", "HIGH": "#fb923c", "CRITICAL": "#f87171"}
    brain_colors = {"eroad": "#4f9cf9", "personal": "#a78bfa"}
    phase_colors = {"done": "#34d399", "failed": "#f87171", "warning": "#fb923c", "running": "#facc15"}
    phase_icons  = {"done": "✅", "failed": "❌", "warning": "⚠️", "running": "⏳"}

    blast_color = blast_colors.get(blast, "#94a3b8")
    brain_color = brain_colors.get(brain_type, "#94a3b8")

    # ── Summary stats ──
    n_done    = sum(1 for a in agents if a["status"] == "done")
    n_running = sum(1 for a in agents if a["status"] == "running")
    n_warn    = sum(1 for a in agents if a["status"] in ("warning", "failed"))
    n_total   = len(agents)

    # ── Agent Timeline (sidebar, compact) ──
    timeline_html = ""
    if agents:
        for ag in agents:
            sc = phase_colors.get(ag["status"], "#94a3b8")
            ic = phase_icons.get(ag["status"], "❓")
            model_raw = ag["metrics"].get("model") or ""
            model_label = MODEL_SHORT.get(model_raw, model_raw) if model_raw else ""
            model_pill = f'<span class="model-pill">{html_escape(model_label)}</span>' if model_label else ""
            timeline_html += f"""
            <div class="timeline-item">
              <div class="timeline-dot" style="background:{sc}">{ic}</div>
              <div class="timeline-info">
                <div class="timeline-name">{html_escape(ag['name'])}</div>
                {model_pill}
              </div>
            </div>"""
    else:
        timeline_html = "<div class='empty-state'>No agents dispatched yet</div>"

    # ── Resource Monitor (sidebar) ──
    resource_html = ""
    if agents:
        for ag in agents:
            m  = ag["metrics"]
            sc = phase_colors.get(ag["status"], "#94a3b8")
            ctx_pct    = m["context_pct"]
            ctx_tokens = m["context_tokens"]
            model      = m["model"] or "unknown"
            ctx_limit  = MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)

            tool_gauge = build_gauge_html("tools", m["tool_used"], m["tool_max"], "calls", warn=60, danger=90)

            if ctx_tokens:
                ctx_gauge = build_gauge_html("ctx", ctx_tokens, ctx_limit, f"~{ctx_tokens//1000}k", warn=50, danger=75)
            elif ctx_pct is not None:
                ctx_gauge = build_gauge_html("ctx", int(ctx_pct/100*ctx_limit), ctx_limit, f"{ctx_pct}%", warn=50, danger=75)
            else:
                ctx_gauge = build_gauge_html("ctx", None, None)

            warn_badge = ""
            eff_pct = ctx_pct or (int(ctx_tokens/ctx_limit*100) if ctx_tokens else None)
            if eff_pct and eff_pct >= 75:
                badge_color = "#f87171" if eff_pct >= 90 else "#fb923c"
                warn_badge = f'<span class="ctx-warning-badge" style="background:{badge_color}22;color:{badge_color}">{"🔴 CRIT" if eff_pct >= 90 else "⚠ HIGH"}</span>'

            resource_html += f"""
            <div class="resource-agent">
              <div class="resource-agent-name">
                <div class="resource-status-dot" style="background:{sc}"></div>
                {html_escape(ag['name'][:28])}{'…' if len(ag['name'])>28 else ''}
                {warn_badge}
              </div>
              {tool_gauge}{ctx_gauge}
            </div>"""
    else:
        resource_html = "<div class='empty-state'>No agents yet</div>"

    # ── Agent Detail Cards (main area) ──
    agent_cards_html = ""
    if agents:
        for ag in agents:
            sc  = phase_colors.get(ag["status"], "#94a3b8")
            ic  = phase_icons.get(ag["status"], "❓")
            m   = ag["metrics"]
            ctx_pct    = m["context_pct"]
            ctx_tokens = m["context_tokens"]
            model      = m["model"] or "unknown"
            ctx_limit  = MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)
            model_label = MODEL_SHORT.get(model, model)

            tool_gauge = build_gauge_html("tools", m["tool_used"], m["tool_max"], "calls", warn=60, danger=90)
            if ctx_tokens:
                ctx_gauge = build_gauge_html("ctx", ctx_tokens, ctx_limit, f"~{ctx_tokens//1000}k tokens", warn=50, danger=75)
            elif ctx_pct is not None:
                ctx_gauge = build_gauge_html("ctx", int(ctx_pct/100*ctx_limit), ctx_limit, f"{ctx_pct}%", warn=50, danger=75)
            else:
                ctx_gauge = build_gauge_html("ctx", None, None)

            model_badge = f'<span class="model-badge">{html_escape(model_label)}</span>' if model_label and model_label != "unknown" else ""

            agent_cards_html += f"""
            <div class="agent-card" style="border-left: 4px solid {sc}">
              <div class="agent-header">
                <span class="agent-icon">{ic}</span>
                <span class="agent-name">{html_escape(ag['name'])}</span>
                {model_badge}
                <span class="agent-status-badge" style="background:{sc}22;color:{sc}">{ag['status'].upper()}</span>
              </div>
              <div class="agent-gauges">
                {tool_gauge}
                {ctx_gauge}
              </div>
              <div class="agent-body">{md_to_html(ag['body'])}</div>
            </div>"""
    else:
        agent_cards_html = """
        <div class="empty-agents">
          <div style="font-size:48px;margin-bottom:16px">🤖</div>
          <div style="font-size:16px;color:var(--text-dim)">Waiting for agents to be dispatched…</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agents — {html_escape(task_name)}</title>
  <meta http-equiv="refresh" content="3">
  <style>
    :root {{
      --bg: #0f1117;
      --surface: #1a1d27;
      --surface2: #22263a;
      --border: #2e3347;
      --text: #e2e8f0;
      --text-dim: #94a3b8;
      --text-bright: #f8fafc;
      --green: #34d399;
      --blue: #4f9cf9;
      --purple: #a78bfa;
      --yellow: #facc15;
      --orange: #fb923c;
      --red: #f87171;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.6;
    }}

    /* ── Header ── */
    .header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    .header-logo {{ font-size: 22px; }}
    .header-title {{
      flex: 1;
      font-size: 15px;
      font-weight: 600;
      color: var(--text-bright);
    }}
    .header-title span {{
      color: var(--text-dim);
      font-weight: 400;
      font-size: 12px;
      margin-left: 8px;
    }}
    .header-stats {{
      display: flex;
      gap: 12px;
      align-items: center;
    }}
    .stat-pill {{
      font-size: 12px;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 20px;
    }}
    .live-badge {{
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--green);
      font-size: 12px;
      font-weight: 600;
    }}
    .live-dot {{
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--green);
      animation: pulse 1.5s infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.3; }}
    }}
    .last-updated {{ color: var(--text-dim); font-size: 12px; }}

    /* ── Layout ── */
    .container {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 20px 24px;
      display: grid;
      grid-template-columns: 300px 1fr;
      gap: 20px;
      align-items: start;
    }}
    .sidebar {{ display: flex; flex-direction: column; gap: 14px; position: sticky; top: 60px; }}
    .main {{ display: flex; flex-direction: column; gap: 14px; }}

    /* ── Cards ── */
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
    }}
    .card-header {{
      padding: 10px 14px;
      background: var(--surface2);
      border-bottom: 1px solid var(--border);
      font-size: 11px;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .card-header-count {{
      margin-left: auto;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1px 7px;
      font-size: 11px;
      color: var(--text-dim);
    }}
    .card-body {{ padding: 14px; }}

    /* ── Classification ── */
    .meta-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }}
    .meta-item {{
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 7px;
      padding: 8px 10px;
    }}
    .meta-item.full {{ grid-column: span 2; }}
    .meta-label {{
      font-size: 10px;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 3px;
    }}
    .meta-value {{
      font-size: 13px;
      font-weight: 600;
      color: var(--text-bright);
    }}

    /* ── Timeline ── */
    .timeline-item {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
    }}
    .timeline-item:last-child {{ border-bottom: none; }}
    .timeline-dot {{
      width: 28px; height: 28px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
      flex-shrink: 0;
    }}
    .timeline-info {{ flex: 1; min-width: 0; }}
    .timeline-name {{
      font-size: 12px;
      color: var(--text-bright);
      font-family: monospace;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .model-pill {{
      font-size: 10px;
      color: var(--text-dim);
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 1px 5px;
      display: inline-block;
      margin-top: 2px;
      font-family: monospace;
    }}

    /* ── Agent Cards (main) ── */
    .agent-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
    }}
    .agent-header {{
      padding: 12px 16px;
      background: var(--surface2);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .agent-icon {{ font-size: 18px; flex-shrink: 0; }}
    .agent-name {{
      flex: 1;
      font-weight: 700;
      font-size: 14px;
      color: var(--text-bright);
      font-family: monospace;
    }}
    .model-badge {{
      font-size: 11px;
      color: var(--purple);
      background: #a78bfa18;
      border: 1px solid #a78bfa44;
      border-radius: 5px;
      padding: 2px 8px;
      font-family: monospace;
      flex-shrink: 0;
    }}
    .agent-status-badge {{
      font-size: 10px;
      font-weight: 700;
      padding: 3px 10px;
      border-radius: 20px;
      letter-spacing: 0.06em;
      flex-shrink: 0;
    }}
    .agent-gauges {{
      padding: 8px 16px;
      background: #0f111788;
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .agent-body {{
      padding: 16px;
    }}

    /* ── Empty agents state ── */
    .empty-agents {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 80px 20px;
      color: var(--text-dim);
    }}

    /* ── Gauges ── */
    .gauge-row {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 2px 0;
    }}
    .gauge-label {{
      font-size: 10px;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      width: 38px;
      flex-shrink: 0;
    }}
    .gauge-bar-wrap {{
      flex: 1;
      height: 5px;
      background: var(--surface2);
      border-radius: 3px;
      overflow: hidden;
      border: 1px solid var(--border);
    }}
    .gauge-bar-fill {{
      height: 100%;
      border-radius: 3px;
      transition: width 0.4s ease, background 0.4s ease;
    }}
    .gauge-value {{
      font-size: 11px;
      font-family: monospace;
      width: 100px;
      text-align: right;
      flex-shrink: 0;
      color: var(--text-dim);
    }}
    .gauge-unknown {{
      font-size: 11px;
      color: var(--border);
      font-style: italic;
    }}
    .resource-agent {{
      padding: 8px 0;
      border-bottom: 1px solid var(--border);
    }}
    .resource-agent:last-child {{ border-bottom: none; }}
    .resource-agent-name {{
      font-size: 11px;
      font-family: monospace;
      color: var(--text);
      margin-bottom: 5px;
      display: flex;
      align-items: center;
      gap: 5px;
    }}
    .resource-status-dot {{
      width: 6px; height: 6px;
      border-radius: 50%;
      flex-shrink: 0;
    }}
    .ctx-warning-badge {{
      font-size: 9px;
      padding: 1px 5px;
      border-radius: 8px;
      font-weight: 700;
      margin-left: auto;
    }}

    /* ── Markdown ── */
    code {{
      background: var(--surface2);
      padding: 1px 5px;
      border-radius: 4px;
      font-family: "SF Mono", "Fira Code", monospace;
      font-size: 12px;
      color: var(--purple);
    }}
    pre {{
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      overflow-x: auto;
      margin: 8px 0;
    }}
    pre code {{ background: none; padding: 0; color: var(--text); font-size: 12px; }}
    p {{ margin: 4px 0; color: var(--text); }}
    h2 {{ font-size: 15px; color: var(--text-bright); margin: 12px 0 6px; }}
    h3 {{ font-size: 13px; color: var(--text-bright); margin: 10px 0 4px; }}
    h4 {{ font-size: 12px; color: var(--text-dim); margin: 8px 0 4px; }}
    ul {{ padding-left: 18px; margin: 4px 0; }}
    li {{ margin: 2px 0; }}
    strong {{ color: var(--text-bright); }}
    em {{ color: var(--text-dim); font-style: italic; }}
    .empty {{ color: var(--text-dim); font-style: italic; }}
    .empty-state {{
      color: var(--text-dim);
      font-style: italic;
      text-align: center;
      padding: 16px;
      font-size: 12px;
    }}
    ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
    ::-webkit-scrollbar-track {{ background: var(--surface); }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
  </style>
</head>
<body>
  <div class="header">
    <div class="header-logo">🤖</div>
    <div class="header-title">
      {html_escape(task_name)}
      <span>started {html_escape(created)}</span>
    </div>
    <div class="header-stats">
      {f'<span class="stat-pill" style="background:#34d39922;color:#34d399">{n_done} done</span>' if n_done else ''}
      {f'<span class="stat-pill" style="background:#facc1522;color:#facc15">{n_running} running</span>' if n_running else ''}
      {f'<span class="stat-pill" style="background:#f8717122;color:#f87171">{n_warn} issues</span>' if n_warn else ''}
      {f'<span class="stat-pill" style="background:#2e334722;color:#94a3b8">{n_total} agents</span>' if n_total else ''}
    </div>
    <div class="live-badge"><div class="live-dot"></div>LIVE</div>
    <div class="last-updated">{mod_str}</div>
  </div>

  <div class="container">
    <div class="sidebar">

      <div class="card">
        <div class="card-header">🏷️ Task</div>
        <div class="card-body">
          <div class="meta-grid">
            <div class="meta-item">
              <div class="meta-label">Brain</div>
              <div class="meta-value" style="color:{brain_color}">{html_escape(brain_type)}</div>
            </div>
            <div class="meta-item">
              <div class="meta-label">Blast</div>
              <div class="meta-value" style="color:{blast_color}">{html_escape(blast)}</div>
            </div>
            <div class="meta-item">
              <div class="meta-label">Domain</div>
              <div class="meta-value">{html_escape(domain)}</div>
            </div>
            <div class="meta-item">
              <div class="meta-label">Type</div>
              <div class="meta-value">{html_escape(task_type)}</div>
            </div>
            <div class="meta-item full">
              <div class="meta-label">Pipeline</div>
              <div class="meta-value">{html_escape(pipeline)}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">⚡ Pipeline
          <span class="card-header-count">{n_total}</span>
        </div>
        <div class="card-body" style="padding:8px 14px">
          {timeline_html}
        </div>
      </div>

      <div class="card">
        <div class="card-header">🔬 Resources</div>
        <div class="card-body" style="padding:8px 14px">
          {resource_html}
        </div>
      </div>

    </div>

    <div class="main">
      {agent_cards_html}
    </div>
  </div>
</body>
</html>"""






class DashboardHandler(http.server.BaseHTTPRequestHandler):
    stm_path: Path = None
    html_cache: str = ""
    cache_mtime: float = 0

    def log_message(self, format, *args):
        pass  # suppress server logs

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return

        stm_path = DashboardHandler.stm_path
        if not stm_path or not stm_path.exists():
            body = b"<html><body><h2>STM file not found.</h2></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            return

        mtime = stm_path.stat().st_mtime
        if mtime != DashboardHandler.cache_mtime:
            content = stm_path.read_text(encoding="utf-8")
            parsed = parse_stm(content)
            DashboardHandler.html_cache = build_html(stm_path, parsed, mtime)
            DashboardHandler.cache_mtime = mtime

        body = DashboardHandler.html_cache.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def find_free_port(start=7700) -> int:
    import socket
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found")


def main():
    parser = argparse.ArgumentParser(description="STM Live Dashboard")
    parser.add_argument("stm_file", nargs="?", help="Path to short-term-memory.md")
    parser.add_argument("--latest", action="store_true", help="Open most recent STM")
    parser.add_argument("--port", type=int, default=0, help="Port (default: auto)")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    if args.latest or not args.stm_file:
        stm_path = find_latest_stm()
        if not stm_path:
            print("No STM files found in ~/.copilot/stm/", file=sys.stderr)
            sys.exit(1)
    else:
        stm_path = Path(args.stm_file).expanduser().resolve()
        if not stm_path.exists():
            print(f"STM file not found: {stm_path}", file=sys.stderr)
            sys.exit(1)

    port = args.port if args.port else find_free_port()
    DashboardHandler.stm_path = stm_path

    server = http.server.HTTPServer(("", port), DashboardHandler)
    url = f"http://localhost:{port}"

    print(f"🧠 STM Dashboard — {stm_path.parent.name}")
    print(f"   Serving: {url}")
    print(f"   Watching: {stm_path}")
    print(f"   Auto-refreshes every 3 seconds")
    print(f"   Ctrl+C to stop")

    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
