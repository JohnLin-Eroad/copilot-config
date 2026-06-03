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

    for scope in ("all_time", "weeks"):
        if scope == "weeks":
            continue  # weeks change; comparing all-time is the meaningful trend
        o = old.get(scope, old)
        n = new.get(scope, new)
        print(f"── {scope.upper().replace('_',' ')} ──")
        diff_section("sessions",          get(o, "sessions"),                      get(n, "sessions"))
        diff_section("tokens (subagent)", get(o, "tokens", "subagent_exact"),      get(n, "tokens", "subagent_exact"))
        diff_section("tokens (main est)", get(o, "tokens", "main_heuristic"),      get(n, "tokens", "main_heuristic"))
        diff_section("tokens (TOTAL)",    get(o, "tokens", "total_estimated"),     get(n, "tokens", "total_estimated"))
        # tool totals
        o_tools = sum(get(o, "tools", default={}).values()) if isinstance(get(o, "tools", default={}), dict) else 0
        n_tools = sum(get(n, "tools", default={}).values()) if isinstance(get(n, "tools", default={}), dict) else 0
        diff_section("total tool calls",  o_tools, n_tools)
        # per-session normalisation (the real efficiency metric)
        os_, ns_ = max(get(o, "sessions"), 1), max(get(n, "sessions"), 1)
        ot = get(o, "tokens", "total_estimated")
        nt = get(n, "tokens", "total_estimated")
        diff_section("avg tokens/session", ot // os_, nt // ns_)
        diff_section("avg tool calls/session", o_tools // os_, n_tools // ns_)
        print()

    print("(✓ = decrease / improvement, ⚠ = increase, · = no change)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
