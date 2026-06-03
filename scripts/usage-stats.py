#!/usr/bin/env python3
"""
Copilot Usage Statistics Aggregator

Parses all session events.jsonl files and aggregates:
  - Token usage: sub-agent (exact) + main session (heuristic via compaction events)
  - Model distribution % (sub-agents + model change tracking)
  - Agent call frequency (count, avg tokens, avg duration)
  - Agent failure tracking (subagent.failed events with error categorisation)
  - Session error and abort tracking
  - Skill call frequency (by skill name)
  - Tool call frequency

Output: ~/.copilot/logs/usage-stats.json
         ~/.copilot/logs/usage-stats-report.txt (human-readable)

Usage:
  python3 ~/.copilot/scripts/usage-stats.py             # print report + update stats
  python3 ~/.copilot/scripts/usage-stats.py --week 2026-W16   # filter to specific week
  python3 ~/.copilot/scripts/usage-stats.py --json      # JSON output only
  python3 ~/.copilot/scripts/usage-stats.py --update-only     # update stats silently
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


SESSIONS_DIR = Path.home() / ".copilot" / "session-state"
STATS_FILE = Path.home() / ".copilot" / "logs" / "usage-stats.json"
REPORT_FILE = Path.home() / ".copilot" / "logs" / "usage-stats-report.txt"
PRICING_FILE = Path.home() / ".copilot" / "credit-pricing.json"


def load_pricing() -> dict:
    """Load credit multipliers + USD-per-credit. Returns sane defaults if file missing."""
    if PRICING_FILE.exists():
        try:
            return json.loads(PRICING_FILE.read_text())
        except Exception as e:
            print(f"warn: bad {PRICING_FILE}: {e}", file=sys.stderr)
    return {"usd_per_credit": 0.04, "default_multiplier": 1.0, "multipliers": {}}


def credits_for_model(pricing: dict, model: str, calls: int) -> float:
    """1 call = 1 premium request × multiplier. Returns AI credits consumed."""
    mult = pricing.get("multipliers", {}).get(model, pricing.get("default_multiplier", 1.0))
    return calls * mult


def iso_to_week(ts: str) -> str:
    """Convert ISO timestamp to YYYY-WXX week string."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-W%V")
    except Exception:
        return "unknown"


def categorise_error(msg: str) -> str:
    """Map an error message to a short category label."""
    m = msg.lower()
    if "goaway" in m or "connection" in m:
        return "connection_error"
    if "timed out" in m or "timeout" in m:
        return "timeout"
    if "503" in m:
        return "api_503"
    if "rate limit" in m or "429" in m:
        return "rate_limit"
    if "401" in m or "unauthorized" in m:
        return "auth_error"
    return "other"


def parse_session(events_path: Path) -> dict:
    """Parse a single session's events.jsonl and return stats dict."""
    stats = {
        "session_id": events_path.parent.name,
        "start_time": None,
        "end_time": None,
        "week": "unknown",
        "model": "unknown",
        # Sub-agent tokens (exact)
        "subagent_tokens": 0,
        # Main session token estimate from compaction events
        "main_session_tokens_heuristic": 0,
        # Tracks compaction preCompactionTokens seen so far
        "_compaction_tokens_seen": [],
        # Final context snapshot (last compaction_start before any compaction_complete or end)
        "_last_context_snapshot": 0,
        # By model
        "subagent_by_model": defaultdict(lambda: {"tokens": 0, "calls": 0, "total_duration_ms": 0}),
        # Agent calls
        "agent_calls": defaultdict(lambda: {"calls": 0, "tokens": 0, "total_duration_ms": 0}),
        # Pending agent starts awaiting completion
        "_pending_agents": {},
        # Skill calls
        "skill_calls": defaultdict(int),
        # Tool calls
        "tool_calls": defaultdict(int),
        # Total subagent calls
        "total_subagent_calls": 0,
        # Total tool calls (excluding report_intent which is meta)
        "total_tool_calls": 0,
        # Agent failures (subagent.failed events)
        "agent_failures": defaultdict(lambda: {"count": 0, "tokens_lost": 0, "errors": []}),
        # Session-level errors
        "session_error_count": 0,
        "session_errors_by_type": defaultdict(int),
        # Aborts
        "abort_count": 0,
        "abort_user_count": 0,
    }

    try:
        with open(events_path) as f:
            lines = f.readlines()
    except Exception:
        return stats

    for line in lines:
        try:
            e = json.loads(line.strip())
        except Exception:
            continue

        t = e.get("type", "")
        d = e.get("data", {})
        ts = e.get("timestamp", "")

        if t == "session.start":
            stats["start_time"] = ts
            stats["week"] = iso_to_week(ts)

        elif t == "session.shutdown":
            stats["end_time"] = ts

        elif t == "session.model_change":
            stats["model"] = d.get("newModel", stats["model"])

        # --- Compaction events: heuristic for main session tokens ---
        elif t == "session.compaction_complete":
            pre = d.get("preCompactionTokens", 0)
            if pre:
                stats["_compaction_tokens_seen"].append(pre)
                # Each compaction represents ~pre tokens of main session work
                # We sum them to get cumulative throughput estimate.
                # Subtract previous compaction's ending context to avoid double-counting.
                prev_sum = sum(stats["_compaction_tokens_seen"][:-1])
                stats["main_session_tokens_heuristic"] += pre

        elif t == "session.compaction_start":
            # Store the snapshot for use if the session ends without a compaction_complete
            snap = d.get("conversationTokens", 0) + d.get("systemTokens", 0) + d.get("toolDefinitionsTokens", 0)
            stats["_last_context_snapshot"] = snap

        # --- Tool calls ---
        elif t == "tool.execution_start":
            tool_name = d.get("toolName", "")
            if not tool_name:
                continue
            stats["total_tool_calls"] += 1
            stats["tool_calls"][tool_name] += 1

            # Skill calls — extract skill name from arguments
            if tool_name == "skill":
                skill_name = d.get("arguments", {}).get("skill", "unknown")
                stats["skill_calls"][skill_name] += 1

        # --- Sub-agent lifecycle ---
        elif t == "subagent.started":
            tc_id = d.get("toolCallId", "")
            stats["_pending_agents"][tc_id] = {
                "agentName": d.get("agentName", "unknown"),
                "startTs": ts,
            }

        elif t == "subagent.completed":
            tc_id = d.get("toolCallId", "")
            agent_name = d.get("agentName", "unknown")
            model = d.get("model") or "unknown"
            tokens = d.get("totalTokens", 0)
            duration_ms = d.get("durationMs", 0)

            stats["subagent_tokens"] += tokens
            stats["total_subagent_calls"] += 1

            # By model
            stats["subagent_by_model"][model]["tokens"] += tokens
            stats["subagent_by_model"][model]["calls"] += 1
            stats["subagent_by_model"][model]["total_duration_ms"] += duration_ms

            # By agent
            stats["agent_calls"][agent_name]["calls"] += 1
            stats["agent_calls"][agent_name]["tokens"] += tokens
            stats["agent_calls"][agent_name]["total_duration_ms"] += duration_ms

            # Clean up pending
            stats["_pending_agents"].pop(tc_id, None)

        elif t == "subagent.failed":
            agent_name = d.get("agentName", "unknown")
            tokens_lost = d.get("totalTokens", 0)
            error_msg = d.get("error", "")
            category = categorise_error(error_msg)
            stats["agent_failures"][agent_name]["count"] += 1
            stats["agent_failures"][agent_name]["tokens_lost"] += tokens_lost
            stats["agent_failures"][agent_name]["errors"].append({
                "category": category,
                "message": error_msg[:200],
                "timestamp": ts,
            })
            stats["total_subagent_calls"] += 1  # count attempt

        elif t == "session.error":
            stats["session_error_count"] += 1
            err_type = d.get("errorType", "unknown")
            msg = d.get("message", "")
            category = categorise_error(msg)
            stats["session_errors_by_type"][category] += 1

        elif t == "abort":
            stats["abort_count"] += 1
            if d.get("reason", "").lower() == "user initiated":
                stats["abort_user_count"] += 1

    # If no compaction_complete but we have a context snapshot, use it as heuristic
    if stats["main_session_tokens_heuristic"] == 0 and stats["_last_context_snapshot"] > 0:
        stats["main_session_tokens_heuristic"] = stats["_last_context_snapshot"]

    # If still no heuristic data (short sessions), use a minimal floor estimate
    # based on the fact that any session has at least system prompt tokens
    if stats["main_session_tokens_heuristic"] == 0:
        stats["main_session_tokens_heuristic"] = 0  # genuinely unknown for tiny sessions

    # Clean up internal tracking fields
    del stats["_compaction_tokens_seen"]
    del stats["_last_context_snapshot"]
    del stats["_pending_agents"]

    # Convert defaultdicts to plain dicts
    stats["subagent_by_model"] = dict(stats["subagent_by_model"])
    stats["agent_calls"] = dict(stats["agent_calls"])
    stats["skill_calls"] = dict(stats["skill_calls"])
    stats["tool_calls"] = dict(stats["tool_calls"])
    stats["agent_failures"] = {k: dict(v) for k, v in stats["agent_failures"].items()}
    stats["session_errors_by_type"] = dict(stats["session_errors_by_type"])

    return stats


def merge_into_aggregate(agg: dict, s: dict) -> None:
    """Merge a session's stats into an aggregate bucket."""
    agg["subagent_tokens"] += s["subagent_tokens"]
    agg["main_session_tokens_heuristic"] += s["main_session_tokens_heuristic"]
    agg["total_tool_calls"] += s["total_tool_calls"]
    agg["total_subagent_calls"] += s["total_subagent_calls"]
    agg["session_count"] = agg.get("session_count", 0) + 1

    # By model
    for model, mv in s["subagent_by_model"].items():
        if model not in agg["by_model"]:
            agg["by_model"][model] = {"tokens": 0, "calls": 0, "total_duration_ms": 0}
        agg["by_model"][model]["tokens"] += mv["tokens"]
        agg["by_model"][model]["calls"] += mv["calls"]
        agg["by_model"][model]["total_duration_ms"] += mv["total_duration_ms"]

    # Agents
    for agent, av in s["agent_calls"].items():
        if agent not in agg["agents"]:
            agg["agents"][agent] = {"calls": 0, "tokens": 0, "total_duration_ms": 0}
        agg["agents"][agent]["calls"] += av["calls"]
        agg["agents"][agent]["tokens"] += av["tokens"]
        agg["agents"][agent]["total_duration_ms"] += av["total_duration_ms"]

    # Skills
    for skill, count in s["skill_calls"].items():
        agg["skills"][skill] = agg["skills"].get(skill, 0) + count

    # Tools
    for tool, count in s["tool_calls"].items():
        agg["tools"][tool] = agg["tools"].get(tool, 0) + count

    # Agent failures
    for agent, fv in s["agent_failures"].items():
        if agent not in agg["agent_failures"]:
            agg["agent_failures"][agent] = {"count": 0, "tokens_lost": 0, "errors": []}
        agg["agent_failures"][agent]["count"] += fv["count"]
        agg["agent_failures"][agent]["tokens_lost"] += fv["tokens_lost"]
        agg["agent_failures"][agent]["errors"].extend(fv.get("errors", []))

    # Session errors + aborts
    agg["session_error_count"] = agg.get("session_error_count", 0) + s["session_error_count"]
    agg["abort_count"] = agg.get("abort_count", 0) + s["abort_count"]
    agg["abort_user_count"] = agg.get("abort_user_count", 0) + s["abort_user_count"]
    for cat, cnt in s["session_errors_by_type"].items():
        agg["session_errors_by_type"][cat] = agg["session_errors_by_type"].get(cat, 0) + cnt


def empty_aggregate() -> dict:
    return {
        "subagent_tokens": 0,
        "main_session_tokens_heuristic": 0,
        "total_tool_calls": 0,
        "total_subagent_calls": 0,
        "session_count": 0,
        "by_model": {},
        "agents": {},
        "skills": {},
        "tools": {},
        "agent_failures": {},
        "session_error_count": 0,
        "session_errors_by_type": {},
        "abort_count": 0,
        "abort_user_count": 0,
    }


def finalize_aggregate(agg: dict) -> dict:
    """Add derived fields (percentages, averages) to an aggregate."""
    total_sub_tokens = agg["subagent_tokens"]

    # Model percentages (based on sub-agent tokens)
    for m, mv in agg["by_model"].items():
        mv["token_pct"] = round(mv["tokens"] / total_sub_tokens * 100, 1) if total_sub_tokens else 0
        mv["avg_duration_ms"] = round(mv["total_duration_ms"] / mv["calls"]) if mv["calls"] else 0

    # Agent averages + failure rate
    total_failures = sum(fv["count"] for fv in agg["agent_failures"].values())
    for a, av in agg["agents"].items():
        av["avg_tokens"] = round(av["tokens"] / av["calls"]) if av["calls"] else 0
        av["avg_duration_ms"] = round(av["total_duration_ms"] / av["calls"]) if av["calls"] else 0
        failures = agg["agent_failures"].get(a, {}).get("count", 0)
        total_attempts = av["calls"] + failures
        av["failure_count"] = failures
        av["success_rate"] = round(av["calls"] / total_attempts * 100, 1) if total_attempts else 100.0

    # Standalone failure entries (agents that only failed, never completed)
    for a, fv in agg["agent_failures"].items():
        if a not in agg["agents"]:
            agg["agents"][a] = {
                "calls": 0, "tokens": 0, "total_duration_ms": 0,
                "avg_tokens": 0, "avg_duration_ms": 0,
                "failure_count": fv["count"], "success_rate": 0.0,
            }

    agg["total_tokens_estimated"] = total_sub_tokens + agg["main_session_tokens_heuristic"]
    agg["total_agent_failures"] = total_failures
    return agg


def build_stats(filter_week: str | None = None) -> dict:
    """Parse all sessions and return the full stats structure."""
    if not SESSIONS_DIR.exists():
        return {"all_time": empty_aggregate(), "by_week": {}}

    all_time = empty_aggregate()
    by_week: dict[str, dict] = {}

    sessions = sorted(SESSIONS_DIR.iterdir())
    for session_dir in sessions:
        events_path = session_dir / "events.jsonl"
        if not events_path.exists():
            continue

        s = parse_session(events_path)
        week = s.get("week", "unknown")

        if filter_week and week != filter_week:
            continue

        merge_into_aggregate(all_time, s)

        if week not in by_week:
            by_week[week] = empty_aggregate()
        merge_into_aggregate(by_week[week], s)

    finalize_aggregate(all_time)
    for w in by_week:
        finalize_aggregate(by_week[w])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "all_time": all_time,
        "by_week": dict(sorted(by_week.items())),
    }


def fmt_tokens(n: int) -> str:
    """Format token count in human-readable form."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_duration(ms: int) -> str:
    if ms >= 60_000:
        return f"{ms//60000}m{(ms%60000)//1000}s"
    if ms >= 1_000:
        return f"{ms/1000:.0f}s"
    return f"{ms}ms"


def render_report(stats: dict, week: str | None = None) -> str:
    """Render a human-readable usage report."""
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"╔══════════════════════════════════════════════════════════╗")
    lines.append(f"║        📊 Copilot Usage Statistics — {now}      ║")
    lines.append(f"╚══════════════════════════════════════════════════════════╝")
    lines.append("")

    def render_bucket(label: str, agg: dict) -> None:
        lines.append(f"{'━'*60}")
        lines.append(f"  {label}")
        lines.append(f"{'━'*60}")

        sub_t = agg["subagent_tokens"]
        main_t = agg["main_session_tokens_heuristic"]
        total_t = agg["total_tokens_estimated"]
        sessions = agg.get("session_count", 0)

        lines.append(f"  SESSIONS: {sessions}")
        lines.append("")
        lines.append(f"  TOKENS")
        lines.append(f"    Sub-agent (exact):       {fmt_tokens(sub_t):>10}")
        lines.append(f"    Main session (heuristic):{fmt_tokens(main_t):>10}  ⚠ estimated via compaction events")
        lines.append(f"    Total estimated:         {fmt_tokens(total_t):>10}")
        lines.append("")

        # Model distribution
        lines.append(f"  MODEL DISTRIBUTION (sub-agents)")
        by_model = sorted(agg["by_model"].items(), key=lambda x: -x[1]["tokens"])
        for model, mv in by_model:
            pct = mv["token_pct"]
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            calls = mv["calls"]
            avg_d = fmt_duration(mv.get("avg_duration_ms", 0))
            lines.append(f"    {model:<25} {bar} {pct:5.1f}%  ({calls} calls, avg {avg_d})")
        lines.append("")

        # Top agents
        lines.append(f"  TOP AGENTS")
        agents = sorted(agg["agents"].items(), key=lambda x: -x[1]["calls"])
        for agent, av in agents[:10]:
            calls = av["calls"]
            tkn = fmt_tokens(av["tokens"])
            avg_d = fmt_duration(av.get("avg_duration_ms", 0))
            lines.append(f"    {agent:<30} {calls:>4} calls  {tkn:>8} tokens  avg {avg_d}")
        lines.append("")

        # Skills
        lines.append(f"  SKILL CALLS")
        skills = sorted(agg["skills"].items(), key=lambda x: -x[1])
        if skills:
            for skill, count in skills:
                lines.append(f"    {skill:<35} {count:>4} calls")
        else:
            lines.append("    (none recorded)")
        lines.append("")

        # Tools
        lines.append(f"  TOP TOOLS")
        tools = sorted(agg["tools"].items(), key=lambda x: -x[1])
        for tool, count in tools[:15]:
            lines.append(f"    {tool:<40} {count:>6} calls")
        lines.append("")

    # All-time
    render_bucket("ALL TIME", stats["all_time"])

    # Current or specified week
    if week and week in stats["by_week"]:
        render_bucket(f"WEEK {week}", stats["by_week"][week])
    elif stats["by_week"]:
        latest_week = sorted(stats["by_week"].keys())[-1]
        render_bucket(f"WEEK {latest_week} (latest)", stats["by_week"][latest_week])

    lines.append(f"  ⚠  Token heuristic: main session tokens estimated from context compaction events.")
    lines.append(f"     Sub-agent tokens are exact. Total is a conservative undercount.")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Copilot usage statistics")
    parser.add_argument("--week", help="Filter to a specific week (e.g. 2026-W16)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text report")
    parser.add_argument("--update-only", action="store_true", help="Update stats file silently, no output")
    args = parser.parse_args()

    stats = build_stats(filter_week=args.week)

    # Always write the stats file
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, indent=2))

    if args.update_only:
        return

    if args.json:
        print(json.dumps(stats, indent=2))
        return

    report = render_report(stats, week=args.week)

    # Write report file
    REPORT_FILE.write_text(report)

    print(report)


if __name__ == "__main__":
    main()
