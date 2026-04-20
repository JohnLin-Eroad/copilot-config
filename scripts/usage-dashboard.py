#!/usr/bin/env python3
"""
Copilot Usage Dashboard Generator

Reads ~/.copilot/logs/usage-stats.json and generates a self-contained HTML
dashboard with interactive charts. Opens in the default browser.

Usage:
  python3 ~/.copilot/scripts/usage-dashboard.py          # open in browser
  python3 ~/.copilot/scripts/usage-dashboard.py --out ~/Desktop/dashboard.html
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


def build_html(stats: dict) -> str:
    at = stats["all_time"]
    by_week = stats.get("by_week", {})
    weeks_sorted = sorted(by_week.keys())
    generated_at = stats.get("generated_at", "")[:16].replace("T", " ")

    # ── Data prep ─────────────────────────────────────────────────────────────

    # Models (exclude 'unknown')
    models_raw = {k: v for k, v in at["by_model"].items() if k != "unknown" and v["calls"] > 0}
    models_sorted = sorted(models_raw.items(), key=lambda x: -x[1]["tokens"])
    model_labels = [m[0] for m in models_sorted]
    model_tokens = [m[1]["tokens"] for m in models_sorted]
    model_calls  = [m[1]["calls"]  for m in models_sorted]
    model_colors = ["#6366f1","#f59e0b","#10b981","#3b82f6","#ec4899","#8b5cf6"]

    # Agents sorted by calls
    agents_sorted = sorted(at["agents"].items(), key=lambda x: -x[1]["calls"])[:10]
    agent_labels  = [a[0] for a in agents_sorted]
    agent_calls_d = [a[1]["calls"] for a in agents_sorted]
    agent_tokens_d= [round(a[1]["tokens"]/1_000_000, 2) for a in agents_sorted]
    agent_avgdur  = [a[1].get("avg_duration_ms", 0)//1000 for a in agents_sorted]

    # Skills
    skills_sorted = sorted(at["skills"].items(), key=lambda x: -x[1])
    skill_labels  = [s[0] for s in skills_sorted]
    skill_counts  = [s[1] for s in skills_sorted]

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

    # Weekly agent breakdown (stacked bar — top 5 agents per week)
    top_agents_global = [a[0] for a in agents_sorted[:6]]
    week_agent_data = {}
    for agent in top_agents_global:
        week_agent_data[agent] = []
        for w in weeks_sorted:
            calls = by_week[w].get("agents", {}).get(agent, {}).get("calls", 0)
            week_agent_data[agent].append(calls)

    # Summary cards
    total_tok  = at.get("total_tokens_estimated", 0)
    sub_tok    = at.get("subagent_tokens", 0)
    main_tok   = at.get("main_session_tokens_heuristic", 0)
    sessions   = at.get("session_count", 0)
    total_tools= at.get("total_tool_calls", 0)
    total_agents= at.get("total_subagent_calls", 0)
    top_model  = model_labels[0] if model_labels else "—"
    top_model_pct = f"{models_sorted[0][1]['token_pct']}%" if models_sorted else "—"

    # JSON blobs for JS
    def j(x): return json.dumps(x)

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

  .topbar {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 28px; display: flex; align-items: center; justify-content: space-between; }}
  .topbar h1 {{ font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }}
  .topbar h1 span {{ color: var(--accent); }}
  .topbar small {{ color: var(--muted); font-size: 12px; }}

  .main {{ padding: 24px 28px; max-width: 1400px; margin: 0 auto; }}

  /* ── Cards ── */
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px; margin-bottom: 28px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }}
  .card .label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }}
  .card .value {{ font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }}
  .card .sub {{ color: var(--muted); font-size: 11px; margin-top: 4px; }}
  .card.accent {{ border-color: var(--accent); }}
  .card.green {{ border-color: var(--green); }}

  /* ── Charts grid ── */
  .grid {{ display: grid; gap: 20px; margin-bottom: 20px; }}
  .grid-2   {{ grid-template-columns: 1fr 1fr; }}
  .grid-3   {{ grid-template-columns: 1fr 1fr 1fr; }}
  .grid-3-1 {{ grid-template-columns: 2fr 1fr; }}

  .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px 24px; }}
  .panel h2 {{ font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 18px; }}
  .chart-wrap {{ position: relative; }}

  /* ── Weekly table ── */
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ color: var(--muted); font-weight: 600; text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #1e2130; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #1e2130; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 20px; font-size: 11px; font-weight: 600; }}
  .badge-indigo {{ background: #312e81; color: #a5b4fc; }}
  .badge-green  {{ background: #064e3b; color: #6ee7b7; }}

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

  <!-- ── Summary cards ── -->
  <div class="cards">
    <div class="card accent">
      <div class="label">Total Tokens (est.)</div>
      <div class="value">{fmt_tokens(total_tok)}</div>
      <div class="sub">{fmt_tokens(sub_tok)} exact + {fmt_tokens(main_tok)} heuristic</div>
    </div>
    <div class="card">
      <div class="label">Sessions</div>
      <div class="value">{sessions}</div>
      <div class="sub">all time</div>
    </div>
    <div class="card">
      <div class="label">Sub-agent Calls</div>
      <div class="value">{total_agents}</div>
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
    <div class="card">
      <div class="label">Weeks Tracked</div>
      <div class="value">{len(weeks_sorted)}</div>
      <div class="sub">{weeks_sorted[0] if weeks_sorted else "—"} → {weeks_sorted[-1] if weeks_sorted else "—"}</div>
    </div>
  </div>

  <!-- ── Row 1: Model donut + Weekly trend ── -->
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

  <!-- ── Row 2: Agents calls + Agent tokens ── -->
  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="panel">
      <h2>Agent Calls (count)</h2>
      <div class="chart-wrap" style="height:280px">
        <canvas id="agentCalls"></canvas>
      </div>
    </div>
    <div class="panel">
      <h2>Agent Token Usage (M)</h2>
      <div class="chart-wrap" style="height:280px">
        <canvas id="agentTokens"></canvas>
      </div>
    </div>
  </div>

  <!-- ── Row 3: Skills + Weekly agent stacked ── -->
  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="panel">
      <h2>Skill Invocations</h2>
      <div class="chart-wrap" style="height:240px">
        <canvas id="skillCalls"></canvas>
      </div>
    </div>
    <div class="panel">
      <h2>Weekly Agent Activity (stacked calls)</h2>
      <div class="chart-wrap" style="height:240px">
        <canvas id="weeklyAgents"></canvas>
      </div>
    </div>
  </div>

  <!-- ── Row 4: Tool calls ── -->
  <div class="panel" style="margin-bottom:20px">
    <h2>Top Tool Calls (all time, excl. report_intent)</h2>
    <div class="chart-wrap" style="height:220px">
      <canvas id="toolCalls"></canvas>
    </div>
  </div>

  <!-- ── Weekly breakdown table ── -->
  <div class="panel" style="margin-bottom:20px">
    <h2>Weekly Breakdown</h2>
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
          <th>Tool Calls</th>
        </tr>
      </thead>
      <tbody>
        {''.join(_week_row(w, by_week[w]) for w in reversed(weeks_sorted))}
      </tbody>
    </table>
  </div>

  <div class="note">⚠ Sub-agent tokens are exact (from <code>subagent.completed</code> events). Main session tokens are estimated from <code>session.compaction_complete.preCompactionTokens</code> — a conservative undercount for sessions without compaction. <code>report_intent</code> excluded from tool chart.</div>

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

// ── Skill calls ───────────────────────────────────────────────────────────────
new Chart(document.getElementById('skillCalls'), {{
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
}});

// ── Weekly agent stacked ──────────────────────────────────────────────────────
const agentColors = ['#6366f1','#10b981','#f59e0b','#3b82f6','#ec4899','#8b5cf6'];
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
    sub   = fmt_tokens(w.get("subagent_tokens", 0))
    main  = fmt_tokens(w.get("main_session_tokens_heuristic", 0))
    total = fmt_tokens(w.get("total_tokens_estimated", 0))
    sess  = w.get("session_count", 0)
    tools = fmt_tokens(w.get("total_tool_calls", 0))
    agents_total = w.get("total_subagent_calls", 0)
    # top model
    models = {k: v for k, v in w.get("by_model", {}).items() if k != "unknown" and v["calls"] > 0}
    top_model = max(models.items(), key=lambda x: x[1]["tokens"])[0] if models else "—"
    top_model_short = top_model.replace("claude-", "").replace("gpt-", "gpt-")
    pct = models[top_model]["token_pct"] if top_model in models else 0
    return f"""<tr>
      <td><span class="badge badge-indigo">{week}</span></td>
      <td>{sess}</td>
      <td>{sub}</td>
      <td style="color:#f59e0b">{main}</td>
      <td style="font-weight:600">{total}</td>
      <td><span class="badge badge-green">{top_model_short} {pct}%</span></td>
      <td>{agents_total}</td>
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
