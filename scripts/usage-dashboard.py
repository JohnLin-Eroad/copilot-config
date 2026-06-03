#!/usr/bin/env python3
"""
Copilot Usage Dashboard Generator

Reads ~/.copilot/logs/usage-stats.json and generates a self-contained HTML
dashboard with interactive charts. Opens in the default browser.

Usage:
  python3 ~/.copilot/scripts/usage-dashboard.py          # open in browser
  python3 ~/.copilot/scripts/usage-dashboard.py --out ~/Desktop/dashboard.html
  python3 ~/.copilot/scripts/usage-dashboard.py --no-open  # generate but don't open
"""

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from datetime import datetime

STATS_FILE = Path.home() / ".copilot" / "logs" / "usage-stats.json"
DEFAULT_OUT = Path.home() / ".copilot" / "logs" / "usage-dashboard.html"
AGENTS_DIR  = Path.home() / ".copilot" / "agents"
SKILLS_DIR  = Path.home() / "copilot-config" / "skills"


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def fmt_duration(ms):
    if ms >= 60_000:
        return f"{ms//60000}m {(ms%60000)//1000}s"
    if ms >= 1_000:
        return f"{ms/1000:.0f}s"
    return f"{ms}ms"


def all_agent_names() -> list[str]:
    """Scan agents dir for every defined agent, sorted."""
    if not AGENTS_DIR.exists():
        return []
    names = sorted(
        p.name.replace(".agent.md", "")
        for p in AGENTS_DIR.glob("*.agent.md")
    )
    return names


def all_skill_names() -> list[str]:
    """Scan skills dir for every defined skill (sub-dirs with SKILL.md)."""
    names = []
    for d in [SKILLS_DIR, Path.home() / ".copilot" / "skills"]:
        if d.exists():
            for p in d.iterdir():
                if p.is_dir() and (p / "SKILL.md").exists():
                    if p.name not in names:
                        names.append(p.name)
    return sorted(set(names))


def build_html(stats: dict) -> str:
    at = stats["all_time"]
    by_week = stats.get("by_week", {})
    weeks_sorted = sorted(by_week.keys())
    generated_at = stats.get("generated_at", "")[:16].replace("T", " ")

    # ── Filesystem inventory ──────────────────────────────────────────────────
    all_agents = all_agent_names()
    all_skills = all_skill_names()

    # ── Data prep ─────────────────────────────────────────────────────────────

    # Models (exclude 'unknown')
    models_raw = {k: v for k, v in at["by_model"].items() if k != "unknown" and v["calls"] > 0}
    models_sorted = sorted(models_raw.items(), key=lambda x: -x[1]["tokens"])
    model_labels = [m[0] for m in models_sorted]
    model_tokens = [m[1]["tokens"] for m in models_sorted]
    model_calls  = [m[1]["calls"]  for m in models_sorted]
    model_colors = ["#6366f1","#f59e0b","#10b981","#3b82f6","#ec4899","#8b5cf6"]

    # All agents — invoked sorted by calls desc, then uninvoked alphabetically
    invoked_agents = sorted(
        [(n, at["agents"].get(n, {})) for n in all_agents if at["agents"].get(n, {}).get("calls", 0) > 0],
        key=lambda x: -x[1]["calls"]
    )
    uninvoked_agents = [(n, {}) for n in all_agents if at["agents"].get(n, {}).get("calls", 0) == 0]
    agent_rows_all = invoked_agents + uninvoked_agents

    # Top-10 invoked for charts
    agents_sorted = invoked_agents[:10]
    agent_labels  = [a[0] for a in agents_sorted]
    agent_calls_d = [a[1]["calls"] for a in agents_sorted]
    agent_tokens_d= [round(a[1]["tokens"]/1_000_000, 2) for a in agents_sorted]

    # Agent failures
    agent_failures = at.get("agent_failures", {})
    failed_agents_sorted = sorted(agent_failures.items(), key=lambda x: -x[1]["count"])
    fail_labels = [a[0] for a in failed_agents_sorted]
    fail_counts = [a[1]["count"] for a in failed_agents_sorted]
    fail_tokens_lost = [round(a[1].get("tokens_lost", 0)/1_000_000, 2) for a in failed_agents_sorted]

    # Error category breakdown
    err_by_type = at.get("session_errors_by_type", {})
    err_labels = list(err_by_type.keys())
    err_counts = [err_by_type[k] for k in err_labels]

    # All skills — invoked sorted by count desc, then uninvoked alphabetically
    invoked_skills = sorted(
        [(n, at["skills"].get(n, 0)) for n in all_skills if at["skills"].get(n, 0) > 0],
        key=lambda x: -x[1]
    )
    uninvoked_skills = [(n, 0) for n in all_skills if at["skills"].get(n, 0) == 0]
    skill_rows_all = invoked_skills + uninvoked_skills

    # Chart data: all invoked skills
    skill_labels = [s[0] for s in invoked_skills]
    skill_counts = [s[1] for s in invoked_skills]

    # Tools (top 15, exclude report_intent)
    tools_filtered = {k: v for k, v in at["tools"].items() if k != "report_intent"}
    tools_sorted = sorted(tools_filtered.items(), key=lambda x: -x[1])[:15]
    tool_labels = [t[0] for t in tools_sorted]
    tool_counts = [t[1] for t in tools_sorted]

    # Weekly trend
    week_labels  = weeks_sorted
    week_sub_tok = [by_week[w].get("subagent_tokens", 0)/1_000_000 for w in weeks_sorted]
    week_main_tok= [by_week[w].get("main_session_tokens_heuristic", 0)/1_000_000 for w in weeks_sorted]
    week_sessions= [by_week[w].get("session_count", 0) for w in weeks_sorted]

    # Weekly agent breakdown (stacked bar — top 6 invoked agents)
    top_agents_global = agent_labels[:6]
    week_agent_data = {}
    for agent in top_agents_global:
        week_agent_data[agent] = []
        for w in weeks_sorted:
            calls = by_week[w].get("agents", {}).get(agent, {}).get("calls", 0)
            week_agent_data[agent].append(calls)

    # Summary cards
    total_tok   = at.get("total_tokens_estimated", 0)
    sub_tok     = at.get("subagent_tokens", 0)
    main_tok    = at.get("main_session_tokens_heuristic", 0)
    sessions    = at.get("session_count", 0)
    total_tools = at.get("total_tool_calls", 0)
    total_agents_calls = at.get("total_subagent_calls", 0)
    total_failures = at.get("total_agent_failures", 0)
    abort_count = at.get("abort_count", 0)
    session_errors = at.get("session_error_count", 0)
    top_model   = model_labels[0] if model_labels else "—"
    top_model_pct = f"{models_sorted[0][1]['token_pct']}%" if models_sorted else "—"

    # Credits + USD cost (added with credit-pricing model)
    total_credits  = at.get("total_credits", 0)
    total_cost_usd = at.get("total_cost_usd", 0)
    usd_per_credit = at.get("usd_per_credit", 0.04)
    avg_credits_per_session = (total_credits / sessions) if sessions else 0
    avg_cost_per_session    = (total_cost_usd / sessions) if sessions else 0

    # JSON blobs for JS
    def j(x): return json.dumps(x)

    # ── HTML helpers ─────────────────────────────────────────────────────────

    def agent_table_rows() -> str:
        rows = []
        for name, av in agent_rows_all:
            calls = av.get("calls", 0)
            tokens = av.get("tokens", 0)
            failures = av.get("failure_count", agent_failures.get(name, {}).get("count", 0))
            success_rate = av.get("success_rate", 100.0 if calls == 0 else None)
            avg_dur = av.get("avg_duration_ms", 0)

            if calls == 0 and failures == 0:
                calls_cell = '<span style="color:#475569">—</span>'
                tokens_cell = '<span style="color:#475569">—</span>'
                dur_cell = '<span style="color:#475569">—</span>'
                rate_cell = '<span style="color:#475569">never invoked</span>'
                row_style = 'style="opacity:0.5"'
            else:
                calls_cell = f'<strong>{calls}</strong>'
                tokens_cell = fmt_tokens(tokens) if tokens else "—"
                dur_cell = fmt_duration(avg_dur) if avg_dur else "—"
                if success_rate is None:
                    success_rate = round(calls / (calls + failures) * 100, 1) if (calls + failures) else 100.0
                if success_rate >= 99:
                    rate_badge = f'<span class="badge badge-green">{success_rate:.0f}%</span>'
                elif success_rate >= 80:
                    rate_badge = f'<span class="badge badge-yellow">{success_rate:.0f}%</span>'
                else:
                    rate_badge = f'<span class="badge badge-red">{success_rate:.0f}%</span>'
                rate_cell = rate_badge
                row_style = ''

            fail_cell = f'<span style="color:#ef4444;font-weight:600">{failures}</span>' if failures > 0 else '<span style="color:#475569">0</span>'

            rows.append(f"""<tr {row_style}>
              <td style="font-family:monospace;font-size:12px">{name}</td>
              <td style="text-align:right">{calls_cell}</td>
              <td style="text-align:right">{tokens_cell}</td>
              <td style="text-align:right">{dur_cell}</td>
              <td style="text-align:right">{fail_cell}</td>
              <td style="text-align:right">{rate_cell}</td>
            </tr>""")
        return "\n".join(rows)

    def skill_table_rows() -> str:
        rows = []
        for name, count in skill_rows_all:
            if count == 0:
                count_cell = '<span style="color:#475569">—</span>'
                row_style = 'style="opacity:0.5"'
            else:
                count_cell = f'<strong>{count}</strong>'
                row_style = ''
            rows.append(f"""<tr {row_style}>
              <td style="font-family:monospace;font-size:12px">{name}</td>
              <td style="text-align:right">{count_cell}</td>
            </tr>""")
        return "\n".join(rows)

    def failure_detail_rows() -> str:
        if not failed_agents_sorted:
            return '<tr><td colspan="5" style="color:#475569;text-align:center">No agent failures recorded</td></tr>'
        rows = []
        for name, fv in failed_agents_sorted:
            count = fv["count"]
            tokens_lost = fv.get("tokens_lost", 0)
            errors = fv.get("errors", [])
            cats = {}
            for e in errors:
                c = e.get("category", "other")
                cats[c] = cats.get(c, 0) + 1
            cats_str = ", ".join(f"{c}×{n}" for c, n in cats.items())
            last_ts = errors[-1]["timestamp"][:10] if errors else "—"
            rows.append(f"""<tr>
              <td style="font-family:monospace;font-size:12px">{name}</td>
              <td style="text-align:right;color:#ef4444;font-weight:600">{count}</td>
              <td style="text-align:right;color:#f59e0b">{fmt_tokens(tokens_lost)}</td>
              <td style="color:#94a3b8;font-size:12px">{cats_str}</td>
              <td style="color:#64748b;font-size:11px">{last_ts}</td>
            </tr>""")
        return "\n".join(rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Copilot Usage Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:       #0f1117;
    --surface:  #1a1d27;
    --border:   #2a2d3a;
    --text:     #e2e8f0;
    --muted:    #64748b;
    --accent:   #6366f1;
    --green:    #10b981;
    --yellow:   #f59e0b;
    --red:      #ef4444;
    --blue:     #3b82f6;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; min-height: 100vh; }}

  .topbar {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 28px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }}
  .topbar h1 {{ font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }}
  .topbar h1 span {{ color: var(--accent); }}
  .topbar small {{ color: var(--muted); font-size: 12px; }}

  .main {{ padding: 24px 28px; max-width: 1400px; margin: 0 auto; }}

  /* ── Section headers ── */
  .section-header {{ font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 1.2px; margin: 32px 0 14px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
  .section-header:first-child {{ margin-top: 0; }}

  /* ── Cards ── */
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(165px, 1fr)); gap: 14px; margin-bottom: 28px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }}
  .card .label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }}
  .card .value {{ font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }}
  .card .sub {{ color: var(--muted); font-size: 11px; margin-top: 4px; }}
  .card.accent {{ border-color: var(--accent); }}
  .card.green  {{ border-color: var(--green); }}
  .card.red    {{ border-color: var(--red); }}
  .card.yellow {{ border-color: var(--yellow); }}

  /* ── Charts grid ── */
  .grid {{ display: grid; gap: 20px; margin-bottom: 20px; }}
  .grid-2   {{ grid-template-columns: 1fr 1fr; }}
  .grid-3   {{ grid-template-columns: 1fr 1fr 1fr; }}
  .grid-3-1 {{ grid-template-columns: 2fr 1fr; }}

  .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px 24px; }}
  .panel h2 {{ font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 18px; }}
  .chart-wrap {{ position: relative; }}

  /* ── Tables ── */
  .table-scroll {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ color: var(--muted); font-weight: 600; text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; }}
  td {{ padding: 9px 12px; border-bottom: 1px solid #1e2130; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #1e2130; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 20px; font-size: 11px; font-weight: 600; }}
  .badge-indigo {{ background: #312e81; color: #a5b4fc; }}
  .badge-green  {{ background: #064e3b; color: #6ee7b7; }}
  .badge-yellow {{ background: #451a03; color: #fcd34d; }}
  .badge-red    {{ background: #450a0a; color: #fca5a5; }}

  /* ── Note ── */
  .note {{ color: var(--muted); font-size: 11px; margin-top: 10px; padding: 10px 14px; background: #141720; border-left: 3px solid var(--border); border-radius: 4px; }}

  @media (max-width: 900px) {{
    .grid-2, .grid-3, .grid-3-1 {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="topbar">
  <h1>📊 Copilot <span>Usage Dashboard</span></h1>
  <small>Updated {generated_at} UTC</small>
</div>

<div class="main">

  <!-- ══════════════ OVERVIEW ══════════════ -->
  <div class="section-header">Overview</div>
  <div class="cards">
    <div class="card accent">
      <div class="label">Total Tokens (est.)</div>
      <div class="value">{fmt_tokens(total_tok)}</div>
      <div class="sub">{fmt_tokens(sub_tok)} exact + {fmt_tokens(main_tok)} heuristic</div>
    </div>
    <div class="card green">
      <div class="label">💰 Total Cost (USD)</div>
      <div class="value">${total_cost_usd:,.2f}</div>
      <div class="sub">${avg_cost_per_session:.3f} / session · @ ${usd_per_credit:.3f}/credit</div>
    </div>
    <div class="card accent">
      <div class="label">AI Credits Used</div>
      <div class="value">{total_credits:,.1f}</div>
      <div class="sub">{avg_credits_per_session:.2f} avg / session</div>
    </div>
    <div class="card">
      <div class="label">Sessions</div>
      <div class="value">{sessions}</div>
      <div class="sub">all time</div>
    </div>
    <div class="card">
      <div class="label">Agent Calls</div>
      <div class="value">{total_agents_calls}</div>
      <div class="sub">across all sessions</div>
    </div>
    <div class="card">
      <div class="label">Tool Calls</div>
      <div class="value">{fmt_tokens(total_tools)}</div>
      <div class="sub">all tools, all sessions</div>
    </div>
    <div class="card green">
      <div class="label">Top Model</div>
      <div class="value" style="font-size:16px;margin-top:4px">{top_model.replace("claude-","").replace("gpt-","gpt-")}</div>
      <div class="sub">{top_model_pct} of sub-agent tokens</div>
    </div>
    <div class="card red">
      <div class="label">Agent Failures</div>
      <div class="value">{total_failures}</div>
      <div class="sub">{session_errors} session errors · {abort_count} aborts</div>
    </div>
    <div class="card">
      <div class="label">Weeks Tracked</div>
      <div class="value">{len(weeks_sorted)}</div>
      <div class="sub">{weeks_sorted[0] if weeks_sorted else "—"} → {weeks_sorted[-1] if weeks_sorted else "—"}</div>
    </div>
  </div>

  <!-- ══════════════ TOKENS & MODELS ══════════════ -->
  <div class="section-header">Tokens &amp; Models</div>
  <div class="grid grid-3-1" style="margin-bottom:20px">
    <div class="panel">
      <h2>Weekly Token Usage</h2>
      <div class="chart-wrap" style="height:260px">
        <canvas id="weeklyTrend"></canvas>
      </div>
    </div>
    <div class="panel">
      <h2>Model Distribution</h2>
      <div class="chart-wrap" style="height:260px">
        <canvas id="modelDonut"></canvas>
      </div>
    </div>
  </div>

  <!-- ══════════════ AGENTS ══════════════ -->
  <div class="section-header">Agents — {len(all_agents)} defined · {len(invoked_agents)} invoked</div>

  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="panel">
      <h2>Top 10 Agent Calls</h2>
      <div class="chart-wrap" style="height:280px">
        <canvas id="agentCalls"></canvas>
      </div>
    </div>
    <div class="panel">
      <h2>Top 10 Agent Token Usage (M)</h2>
      <div class="chart-wrap" style="height:280px">
        <canvas id="agentTokens"></canvas>
      </div>
    </div>
  </div>

  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="panel">
      <h2>Weekly Agent Activity (stacked calls)</h2>
      <div class="chart-wrap" style="height:240px">
        <canvas id="weeklyAgents"></canvas>
      </div>
    </div>
    <div class="panel" style="overflow:auto;max-height:300px">
      <h2>All Agents — Calls, Tokens &amp; Health</h2>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th style="text-align:right">Calls</th>
              <th style="text-align:right">Tokens</th>
              <th style="text-align:right">Avg Duration</th>
              <th style="text-align:right">Failures</th>
              <th style="text-align:right">Success Rate</th>
            </tr>
          </thead>
          <tbody>
            {agent_table_rows()}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ══════════════ AGENT FAILURES ══════════════ -->
  <div class="section-header">Agent Failures &amp; Errors</div>

  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="panel">
      <h2>Failures by Agent</h2>
      <div class="chart-wrap" style="height:{'220px' if fail_labels else '80px'}">
        {'<canvas id="failureChart"></canvas>' if fail_labels else '<p style="color:#475569;text-align:center;padding:20px">No agent failures recorded ✓</p>'}
      </div>
    </div>
    <div class="panel">
      <h2>Session Error Types</h2>
      <div class="chart-wrap" style="height:{'220px' if err_labels else '80px'}">
        {'<canvas id="errorTypeChart"></canvas>' if err_labels else '<p style="color:#475569;text-align:center;padding:20px">No session errors recorded ✓</p>'}
      </div>
    </div>
  </div>

  <div class="panel" style="margin-bottom:20px">
    <h2>Failure Detail — Agent × Error Category</h2>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th style="text-align:right">Failures</th>
            <th style="text-align:right">Tokens Lost</th>
            <th>Error Categories</th>
            <th>Last Failure</th>
          </tr>
        </thead>
        <tbody>
          {failure_detail_rows()}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ══════════════ SKILLS ══════════════ -->
  <div class="section-header">Skills — {len(all_skills)} defined · {len(invoked_skills)} invoked</div>

  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="panel">
      <h2>Skill Invocations (invoked only)</h2>
      <div class="chart-wrap" style="height:{'240px' if skill_labels else '80px'}">
        {'<canvas id="skillCalls"></canvas>' if skill_labels else '<p style="color:#475569;text-align:center;padding:20px">No skill invocations recorded</p>'}
      </div>
    </div>
    <div class="panel">
      <h2>All Skills — Full Inventory</h2>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Skill</th>
              <th style="text-align:right">Calls</th>
            </tr>
          </thead>
          <tbody>
            {skill_table_rows()}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ══════════════ TOOLS ══════════════ -->
  <div class="section-header">Tools</div>
  <div class="panel" style="margin-bottom:20px">
    <h2>Top Tool Calls (all time, excl. report_intent)</h2>
    <div class="chart-wrap" style="height:220px">
      <canvas id="toolCalls"></canvas>
    </div>
  </div>

  <!-- ══════════════ WEEKLY TABLE ══════════════ -->
  <div class="section-header">Weekly Breakdown</div>
  <div class="panel" style="margin-bottom:20px">
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Week</th>
            <th>Sessions</th>
            <th>Sub-agent Tokens</th>
            <th>Main (est.)</th>
            <th>Total (est.)</th>
            <th>Top Model</th>
            <th>Agent Calls</th>
            <th>Failures</th>
            <th>Tool Calls</th>
          </tr>
        </thead>
        <tbody>
          {''.join(_week_row(w, by_week[w]) for w in reversed(weeks_sorted))}
        </tbody>
      </table>
    </div>
  </div>

  <div class="note">⚠ Sub-agent tokens are exact (from <code>subagent.completed</code> events). Main session tokens are estimated from <code>session.compaction_complete.preCompactionTokens</code>. <code>report_intent</code> excluded from tool chart. Aborts counted across all nested events.</div>

</div><!-- /main -->

<script>
Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = '#2a2d3a';
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
Chart.defaults.font.size = 12;

const PALETTE = {j(model_colors)};

// ── Model donut ──────────────────────────────────────────────────────────────
new Chart(document.getElementById('modelDonut'), {{
  type: 'doughnut',
  data: {{
    labels: {j(model_labels)},
    datasets: [{{ data: {j(model_tokens)}, backgroundColor: {j(model_colors[:len(model_labels)])}, borderWidth: 2, borderColor: '#1a1d27', hoverOffset: 6 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false, cutout: '68%',
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 14, font: {{ size: 11 }} }} }},
      tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.label}}: ${{(ctx.raw/1e6).toFixed(1)}}M tokens (${{ctx.dataset.data.reduce((a,b)=>a+b,0) > 0 ? (ctx.raw/ctx.dataset.data.reduce((a,b)=>a+b,0)*100).toFixed(1) : 0}}%)` }} }}
    }}
  }}
}});

// ── Weekly trend ─────────────────────────────────────────────────────────────
new Chart(document.getElementById('weeklyTrend'), {{
  type: 'bar',
  data: {{
    labels: {j(week_labels)},
    datasets: [
      {{ label: 'Sub-agent tokens (M)', data: {j([round(x,2) for x in week_sub_tok])}, backgroundColor: '#6366f177', borderColor: '#6366f1', borderWidth: 2, borderRadius: 4, yAxisID: 'y' }},
      {{ label: 'Main session est. (M)', data: {j([round(x,2) for x in week_main_tok])}, backgroundColor: '#f59e0b55', borderColor: '#f59e0b', borderWidth: 2, borderRadius: 4, yAxisID: 'y' }},
      {{ label: 'Sessions', data: {j(week_sessions)}, type: 'line', borderColor: '#10b981', backgroundColor: '#10b98122', borderWidth: 2, pointRadius: 4, tension: 0.3, yAxisID: 'y2' }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }} }},
      y: {{ stacked: true, title: {{ display: true, text: 'Tokens (M)' }}, grid: {{ color: '#2a2d3a' }} }},
      y2: {{ position: 'right', title: {{ display: true, text: 'Sessions' }}, grid: {{ display: false }}, ticks: {{ stepSize: 1 }} }}
    }},
    plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 12 }} }} }}
  }}
}});

// ── Agent calls ──────────────────────────────────────────────────────────────
new Chart(document.getElementById('agentCalls'), {{
  type: 'bar',
  data: {{
    labels: {j(agent_labels)},
    datasets: [{{ label: 'Calls', data: {j(agent_calls_d)}, backgroundColor: '#6366f199', borderColor: '#6366f1', borderWidth: 1, borderRadius: 4 }}]
  }},
  options: {{
    indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    scales: {{ x: {{ grid: {{ color: '#2a2d3a' }} }}, y: {{ grid: {{ display: false }} }} }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});

// ── Agent tokens ─────────────────────────────────────────────────────────────
new Chart(document.getElementById('agentTokens'), {{
  type: 'bar',
  data: {{
    labels: {j(agent_labels)},
    datasets: [{{ label: 'Tokens (M)', data: {j(agent_tokens_d)}, backgroundColor: '#10b98199', borderColor: '#10b981', borderWidth: 1, borderRadius: 4 }}]
  }},
  options: {{
    indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    scales: {{ x: {{ grid: {{ color: '#2a2d3a' }}, title: {{ display: true, text: 'Millions' }} }}, y: {{ grid: {{ display: false }} }} }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});

// ── Weekly agent stacked ──────────────────────────────────────────────────────
new Chart(document.getElementById('weeklyAgents'), {{
  type: 'bar',
  data: {{
    labels: {j(week_labels)},
    datasets: {j([{"label": a, "data": week_agent_data[a], "backgroundColor": model_colors[i % len(model_colors)] + "bb", "borderColor": model_colors[i % len(model_colors)], "borderWidth": 1, "borderRadius": 2} for i, a in enumerate(top_agents_global)])}
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }} }},
      y: {{ stacked: true, grid: {{ color: '#2a2d3a' }}, title: {{ display: true, text: 'Calls' }} }}
    }},
    plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 10, font: {{ size: 11 }} }} }} }}
  }}
}});

{'// ── Agent failures ──────────────────────────────────────────────────────────' if fail_labels else ''}
{f"""new Chart(document.getElementById('failureChart'), {{
  type: 'bar',
  data: {{
    labels: {j(fail_labels)},
    datasets: [
      {{ label: 'Failures', data: {j(fail_counts)}, backgroundColor: '#ef444499', borderColor: '#ef4444', borderWidth: 1, borderRadius: 4, yAxisID: 'y' }},
      {{ label: 'Tokens Lost (M)', data: {j(fail_tokens_lost)}, type: 'line', borderColor: '#f59e0b', backgroundColor: '#f59e0b22', borderWidth: 2, pointRadius: 4, tension: 0.3, yAxisID: 'y2' }}
    ]
  }},
  options: {{
    indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    scales: {{
      x: {{ grid: {{ color: '#2a2d3a' }} }},
      y: {{ grid: {{ display: false }} }},
      y2: {{ position: 'right', title: {{ display: true, text: 'M tokens' }}, grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 10 }} }} }}
  }}
}});""" if fail_labels else ""}

{'// ── Error types ─────────────────────────────────────────────────────────────' if err_labels else ''}
{f"""new Chart(document.getElementById('errorTypeChart'), {{
  type: 'doughnut',
  data: {{
    labels: {j(err_labels)},
    datasets: [{{ data: {j(err_counts)}, backgroundColor: ['#ef4444','#f59e0b','#8b5cf6','#3b82f6'], borderWidth: 2, borderColor: '#1a1d27' }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false, cutout: '60%',
    plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 12 }} }} }}
  }}
}});""" if err_labels else ""}

{'// ── Skill calls ───────────────────────────────────────────────────────────────' if skill_labels else ''}
{f"""new Chart(document.getElementById('skillCalls'), {{
  type: 'bar',
  data: {{
    labels: {j(skill_labels)},
    datasets: [{{ label: 'Calls', data: {j(skill_counts)}, backgroundColor: {j([model_colors[i % len(model_colors)] + '99' for i in range(len(skill_labels))])}, borderColor: {j([model_colors[i % len(model_colors)] for i in range(len(skill_labels))])}, borderWidth: 1, borderRadius: 4 }}]
  }},
  options: {{
    indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    scales: {{ x: {{ grid: {{ color: '#2a2d3a' }}, ticks: {{ stepSize: 1 }} }}, y: {{ grid: {{ display: false }} }} }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});""" if skill_labels else ""}

// ── Tool calls ────────────────────────────────────────────────────────────────
new Chart(document.getElementById('toolCalls'), {{
  type: 'bar',
  data: {{
    labels: {j(tool_labels)},
    datasets: [{{ label: 'Calls', data: {j(tool_counts)}, backgroundColor: '#3b82f677', borderColor: '#3b82f6', borderWidth: 1, borderRadius: 4 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{ x: {{ grid: {{ display: false }} }}, y: {{ grid: {{ color: '#2a2d3a' }} }} }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});
</script>
</body>
</html>
"""
    return html


def _week_row(week: str, w: dict) -> str:
    sub    = fmt_tokens(w.get("subagent_tokens", 0))
    main   = fmt_tokens(w.get("main_session_tokens_heuristic", 0))
    total  = fmt_tokens(w.get("total_tokens_estimated", 0))
    sess   = w.get("session_count", 0)
    tools  = fmt_tokens(w.get("total_tool_calls", 0))
    agents_total = w.get("total_subagent_calls", 0)
    failures = w.get("total_agent_failures", 0)
    models = {k: v for k, v in w.get("by_model", {}).items() if k != "unknown" and v["calls"] > 0}
    top_model = max(models.items(), key=lambda x: x[1]["tokens"])[0] if models else "—"
    top_model_short = top_model.replace("claude-", "").replace("gpt-", "gpt-")
    pct = models[top_model]["token_pct"] if top_model in models else 0
    fail_cell = f'<span style="color:#ef4444;font-weight:600">{failures}</span>' if failures > 0 else '<span style="color:#475569">0</span>'
    return f"""<tr>
      <td><span class="badge badge-indigo">{week}</span></td>
      <td>{sess}</td>
      <td>{sub}</td>
      <td style="color:#f59e0b">{main}</td>
      <td style="font-weight:600">{total}</td>
      <td><span class="badge badge-green">{top_model_short} {pct}%</span></td>
      <td>{agents_total}</td>
      <td>{fail_cell}</td>
      <td>{tools}</td>
    </tr>"""


def main():
    parser = argparse.ArgumentParser(description="Generate Copilot usage dashboard")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output HTML path")
    parser.add_argument("--no-open", action="store_true", help="Don't open in browser")
    args = parser.parse_args()

    if not STATS_FILE.exists():
        print("⚠  No usage-stats.json found. Run: python3 ~/.copilot/scripts/usage-stats.py")
        sys.exit(1)

    stats = json.loads(STATS_FILE.read_text())
    html  = build_html(stats)



    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"✅ Dashboard written to {out}")

    if not args.no_open:
        webbrowser.open(f"file://{out}")
        print("🌐 Opened in browser")


if __name__ == "__main__":
    main()
