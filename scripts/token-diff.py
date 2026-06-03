#!/usr/bin/env python3
"""
token-diff.py — compare current usage-stats.json against the latest saved snapshot.

Snapshots live in ~/.copilot/snapshots/ and are created by usage-snapshot.sh.

Usage:
  token-diff.py              # diff current usage vs latest snapshot
  token-diff.py --against usage-20260603T034812Z-post-tier2-optimization.json
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

SNAP_DIR = Path.home() / ".copilot" / "snapshots"
LIVE     = Path.home() / ".copilot" / "logs" / "usage-stats.json"

def fmt(n):
    if not isinstance(n, (int, float)): return str(n)
    if abs(n) >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if abs(n) >= 1_000:     return f"{n/1_000:.1f}K"
    return str(int(n))

def get(d, *keys, default=0):
    for k in keys:
        if not isinstance(d, dict): return default
        d = d.get(k, default)
    return d if d is not None else default

def diff_section(label, old, new):
    delta = new - old
    arrow = "✓" if delta < 0 else ("⚠" if delta > 0 else "·")
    sign = "+" if delta > 0 else ""
    print(f"  {arrow} {label:<32}{fmt(old):>10} → {fmt(new):>10}  ({sign}{fmt(delta)})")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--against", help="snapshot filename in ~/.copilot/snapshots/")
    args = ap.parse_args()

    if not LIVE.exists():
        print(f"missing {LIVE} — run usage-stats.py first"); return 1

    if args.against:
        old_path = SNAP_DIR / args.against
    else:
        old_path = SNAP_DIR / "latest-usage.json"
    if not old_path.exists():
        print(f"missing snapshot: {old_path}"); return 1

    old = json.loads(old_path.read_text())
    new = json.loads(LIVE.read_text())

    old_lbl = old.get("generated_at", str(old_path.name))
    new_lbl = new.get("generated_at", "now")
    print(f"\nDIFF  baseline: {old_lbl}\n      current:  {new_lbl}\n")

    for scope in ("all_time",):
        o = old.get(scope, {})
        n = new.get(scope, {})
        print(f"── {scope.upper().replace('_',' ')} ──")
        diff_section("sessions",          get(o, "session_count"),                  get(n, "session_count"))
        diff_section("tokens (subagent)", get(o, "subagent_tokens"),                get(n, "subagent_tokens"))
        diff_section("tokens (main est)", get(o, "main_session_tokens_heuristic"),  get(n, "main_session_tokens_heuristic"))
        diff_section("tokens (TOTAL)",    get(o, "total_tokens_estimated"),         get(n, "total_tokens_estimated"))
        diff_section("total tool calls",  get(o, "total_tool_calls"),               get(n, "total_tool_calls"))
        diff_section("subagent calls",    get(o, "total_subagent_calls"),           get(n, "total_subagent_calls"))
        os_ = max(get(o, "session_count"), 1)
        ns_ = max(get(n, "session_count"), 1)
        ot  = get(o, "total_tokens_estimated")
        nt  = get(n, "total_tokens_estimated")
        otc = get(o, "total_tool_calls")
        ntc = get(n, "total_tool_calls")
        print("  ── per-session averages (the real efficiency signal) ──")
        diff_section("avg tokens/session",     ot // os_,   nt // ns_)
        diff_section("avg tool calls/session", otc // os_,  ntc // ns_)
        print()

    print("(✓ = decrease / improvement, ⚠ = increase, · = no change)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
