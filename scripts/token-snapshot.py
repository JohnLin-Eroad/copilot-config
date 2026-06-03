#!/usr/bin/env python3
"""
token-snapshot.py — measure context-cost surface of the Copilot CLI setup.

Captures everything that gets loaded into the model context:
  - per-turn:     copilot-instructions.md (reloads every turn)
  - per-session:  MCP tool schemas, system prompt
  - per-pipeline: agent files (loaded when invoked)
  - per-task:     skill files (loaded when invoked)
  - bootstrap:    hook injections

Writes a JSON snapshot + human-readable markdown to ~/.copilot/snapshots/.
Future snapshots diff against the latest baseline.

Usage:
  token-snapshot.py                 # take snapshot, print summary, save
  token-snapshot.py --diff          # compare current vs latest saved snapshot
  token-snapshot.py --label "X"     # tag the snapshot with a name
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
ROOT = HOME / ".copilot"
SNAPSHOT_DIR = ROOT / "snapshots"
CHARS_PER_TOKEN = 4  # standard rough estimate

# --- what to measure --------------------------------------------------------

CATEGORIES = {
    "per_turn": [
        ("copilot-instructions.md",        ROOT / "copilot-instructions.md"),
    ],
    "per_session_static": [
        ("config.json",                    ROOT / "config.json"),
        ("settings.json",                  ROOT / "settings.json"),
        ("governance-rules.json",          ROOT / "governance-rules.json"),
    ],
    "hook_injections": [
        ("pipeline-bootstrap.sh",          ROOT / "hooks" / "pipeline-bootstrap.sh"),
    ],
    "agents":   [],   # populated from glob
    "skills":   [],   # populated from glob
    "hooks":    [],   # populated from glob
}

def populate_globs():
    for p in sorted((ROOT / "agents").glob("*.agent.md")):
        CATEGORIES["agents"].append((p.name, p))
    skills_dir = ROOT / "skills"
    if skills_dir.exists():
        for p in sorted(skills_dir.glob("*/SKILL.md")):
            CATEGORIES["skills"].append((f"{p.parent.name}/SKILL.md", p))
    for p in sorted((ROOT / "hooks").glob("*.sh")):
        if p.name == "pipeline-bootstrap.sh":
            continue
        CATEGORIES["hooks"].append((p.name, p))

# --- MCP schema cost --------------------------------------------------------

def mcp_cost():
    cfg_path = ROOT / "mcp-config.json"
    if not cfg_path.exists():
        return {"enabled": [], "disabled": [], "estimated_tokens_per_session": 0}
    cfg = json.loads(cfg_path.read_text())
    enabled = list(cfg.get("mcpServers", {}).keys())
    disabled = list(cfg.get("_disabled", {}).keys())
    # rough: ~2-3k tokens of schema per typical server. Most heavy ones (atlassian, notion, teams, mail, calendar) are heavier.
    HEAVY = {"atlassian": 5000, "notion": 4000, "microsoft-teams": 4000,
             "microsoft-mail": 3500, "microsoft-calendar": 3000, "slack": 2000, "figma": 1500}
    est = sum(HEAVY.get(n, 2000) for n in enabled)
    return {
        "enabled": enabled,
        "disabled": disabled,
        "estimated_tokens_per_session": est,
        "estimation_basis": "heuristic per-server schema sizes; recalibrate with real measurements",
    }

# --- measurement ------------------------------------------------------------

def measure_file(path: Path):
    if not path.exists():
        return None
    data = path.read_bytes()
    return {
        "path": str(path.relative_to(HOME)),
        "bytes": len(data),
        "chars": len(data.decode("utf-8", errors="replace")),
        "tokens_est": len(data.decode("utf-8", errors="replace")) // CHARS_PER_TOKEN,
        "sha256": hashlib.sha256(data).hexdigest()[:12],
    }

def measure_category(items):
    out = []
    for name, path in items:
        m = measure_file(path)
        if m:
            out.append({"name": name, **m})
    return out

def snapshot():
    populate_globs()
    snap = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": os.uname().nodename,
        "chars_per_token": CHARS_PER_TOKEN,
        "categories": {k: measure_category(v) for k, v in CATEGORIES.items()},
        "mcp": mcp_cost(),
    }
    # totals per category
    snap["totals"] = {}
    grand_tok = 0
    for cat, files in snap["categories"].items():
        toks = sum(f["tokens_est"] for f in files)
        chars = sum(f["chars"] for f in files)
        snap["totals"][cat] = {"files": len(files), "chars": chars, "tokens_est": toks}
        grand_tok += toks
    snap["totals"]["mcp_per_session"] = {
        "files": len(snap["mcp"]["enabled"]),
        "chars": snap["mcp"]["estimated_tokens_per_session"] * CHARS_PER_TOKEN,
        "tokens_est": snap["mcp"]["estimated_tokens_per_session"],
    }
    grand_tok += snap["mcp"]["estimated_tokens_per_session"]
    snap["totals"]["grand_total_tokens_est"] = grand_tok
    # cost models for a typical session
    inst_tok = snap["totals"]["per_turn"]["tokens_est"]
    static_session_tok = (
        snap["totals"]["per_session_static"]["tokens_est"]
        + snap["totals"]["hook_injections"]["tokens_est"]
        + snap["totals"]["mcp_per_session"]["tokens_est"]
        + inst_tok  # loaded at session start too
    )
    snap["session_cost_model"] = {
        "per_turn_tokens": inst_tok,
        "session_start_tokens": static_session_tok,
        "20_turn_session_tokens": static_session_tok + (inst_tok * 19),
        "notes": "per_turn = instructions reloaded. Agents/skills additional when invoked.",
    }
    return snap

# --- I/O --------------------------------------------------------------------

def save(snap, label=None):
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = snap["timestamp"].replace(":", "").replace("-", "")[:15]
    tag = f"-{label}" if label else ""
    json_path = SNAPSHOT_DIR / f"snapshot-{ts}{tag}.json"
    md_path = SNAPSHOT_DIR / f"snapshot-{ts}{tag}.md"
    json_path.write_text(json.dumps(snap, indent=2))
    md_path.write_text(render_markdown(snap))
    # also update "latest" symlinks
    for sym, target in [("latest.json", json_path), ("latest.md", md_path)]:
        link = SNAPSHOT_DIR / sym
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target.name)
    return json_path, md_path

def render_markdown(snap):
    L = []
    L.append(f"# Token Snapshot — {snap['timestamp']}")
    L.append(f"\n_chars/token estimate: {snap['chars_per_token']}_\n")
    L.append("## Cost Model (one typical session)\n")
    cm = snap["session_cost_model"]
    L.append(f"| Metric | Tokens |\n|---|---:|")
    L.append(f"| Per user turn (instructions reload) | {cm['per_turn_tokens']:,} |")
    L.append(f"| Session start (everything static loaded) | {cm['session_start_tokens']:,} |")
    L.append(f"| 20-turn session total | {cm['20_turn_session_tokens']:,} |")
    L.append("")
    L.append("## Totals by Category\n")
    L.append("| Category | Files | Chars | Tokens (est) |\n|---|---:|---:|---:|")
    for cat, t in snap["totals"].items():
        if cat == "grand_total_tokens_est":
            continue
        L.append(f"| {cat} | {t['files']} | {t['chars']:,} | {t['tokens_est']:,} |")
    L.append(f"| **GRAND TOTAL (static + MCP)** | | | **{snap['totals']['grand_total_tokens_est']:,}** |")
    L.append("")
    L.append("## MCP Servers\n")
    L.append(f"- **Enabled** ({len(snap['mcp']['enabled'])}): {', '.join(snap['mcp']['enabled']) or '(none)'}")
    L.append(f"- **Disabled** ({len(snap['mcp']['disabled'])}): {', '.join(snap['mcp']['disabled']) or '(none)'}")
    L.append(f"- Estimated session cost: **{snap['mcp']['estimated_tokens_per_session']:,} tokens**")
    L.append("")
    for cat, files in snap["categories"].items():
        if not files:
            continue
        L.append(f"## {cat}\n")
        L.append("| File | Chars | Tokens (est) | sha256 |\n|---|---:|---:|---|")
        for f in sorted(files, key=lambda x: -x["tokens_est"]):
            L.append(f"| {f['name']} | {f['chars']:,} | {f['tokens_est']:,} | `{f['sha256']}` |")
        L.append("")
    return "\n".join(L)

# --- diff -------------------------------------------------------------------

def diff_against_latest(current):
    latest = SNAPSHOT_DIR / "latest.json"
    if not latest.exists():
        print("(no previous snapshot to diff)")
        return
    old = json.loads(latest.read_text())
    print(f"Comparing current vs {old['timestamp']}\n")
    print(f"{'Category':<25}{'old tok':>12}{'new tok':>12}{'Δ':>10}")
    print("-" * 60)
    for cat in current["totals"]:
        if cat == "grand_total_tokens_est":
            continue
        o = old["totals"].get(cat, {}).get("tokens_est", 0)
        n = current["totals"][cat]["tokens_est"]
        d = n - o
        marker = " ✓" if d < 0 else (" ⚠" if d > 0 else "")
        print(f"{cat:<25}{o:>12,}{n:>12,}{d:>+10,}{marker}")
    print("-" * 60)
    o = old["totals"]["grand_total_tokens_est"]
    n = current["totals"]["grand_total_tokens_est"]
    print(f"{'GRAND TOTAL':<25}{o:>12,}{n:>12,}{n-o:>+10,}")
    # per-file changes
    print("\nFile-level changes:")
    old_files = {f"{cat}/{f['name']}": f for cat, files in old["categories"].items() for f in files}
    new_files = {f"{cat}/{f['name']}": f for cat, files in current["categories"].items() for f in files}
    changes = 0
    for key in sorted(set(old_files) | set(new_files)):
        o = old_files.get(key)
        n = new_files.get(key)
        if o and not n:
            print(f"  - REMOVED  {key} (-{o['tokens_est']:,} tok)"); changes += 1
        elif n and not o:
            print(f"  + ADDED    {key} (+{n['tokens_est']:,} tok)"); changes += 1
        elif o["sha256"] != n["sha256"]:
            d = n["tokens_est"] - o["tokens_est"]
            print(f"  ~ CHANGED  {key} ({d:+,} tok)"); changes += 1
    if not changes:
        print("  (no file content changes)")

# --- main -------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", action="store_true", help="diff vs latest snapshot, don't save")
    ap.add_argument("--label", help="tag for the snapshot file name")
    ap.add_argument("--no-save", action="store_true", help="print only, don't save")
    args = ap.parse_args()

    snap = snapshot()
    if args.diff:
        diff_against_latest(snap)
        return

    print(render_markdown(snap))
    if not args.no_save:
        jp, mp = save(snap, label=args.label)
        print(f"\nsaved: {jp.relative_to(HOME)}")
        print(f"saved: {mp.relative_to(HOME)}")
        print(f"latest -> {jp.name}")

if __name__ == "__main__":
    main()
