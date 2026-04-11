#!/usr/bin/env python3
"""
Copilot Config Auto-Sync
Checks if ~/.copilot setup (agents, skills, scripts, mcp-config) has changed
vs ~/copilot-config repo. If so, redacts secrets, commits, and pushes to GitHub.

Called automatically by the zsh copilot() wrapper after gh copilot exits.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

COPILOT_DIR = Path.home() / ".copilot"
REPO_DIR = Path.home() / "copilot-config"

# Secrets to redact: (regex_pattern, replacement)
REDACTIONS = [
    (r'ntn_[A-Za-z0-9]+', 'YOUR_NOTION_TOKEN'),
    (r'figd_[A-Za-z0-9_\-]+', 'YOUR_FIGMA_ACCESS_TOKEN'),
    (r'YOUR_TENANT_ID', 'YOUR_TENANT_ID'),
]


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = re.sub(pattern, replacement, text)
    return text


def sync_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(redact(src.read_text()))


def sync_agents() -> None:
    dst_dir = REPO_DIR / "agents"
    dst_dir.mkdir(parents=True, exist_ok=True)
    # Remove stale agents no longer in source
    existing = {p.name for p in dst_dir.glob("*.agent.md")}
    current = {p.name for p in (COPILOT_DIR / "agents").glob("*.agent.md")}
    for stale in existing - current:
        (dst_dir / stale).unlink()
    for src in (COPILOT_DIR / "agents").glob("*.agent.md"):
        sync_file(src, dst_dir / src.name)


def sync_skills() -> None:
    src_dir = COPILOT_DIR / "skills"
    dst_dir = REPO_DIR / "skills"
    if not src_dir.exists():
        return
    # Remove stale skill dirs
    existing = {p.name for p in dst_dir.iterdir() if p.is_dir()} if dst_dir.exists() else set()
    current = {p.name for p in src_dir.iterdir() if p.is_dir()}
    for stale in existing - current:
        import shutil
        shutil.rmtree(dst_dir / stale)
    for skill_dir in src_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        for src in skill_dir.glob("*.md"):
            sync_file(src, dst_dir / skill_dir.name / src.name)


def sync_scripts() -> None:
    src_dir = COPILOT_DIR / "scripts"
    dst_dir = REPO_DIR / "scripts"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src in src_dir.glob("*.py"):
        sync_file(src, dst_dir / src.name)


def sync_mcp_config() -> None:
    src = COPILOT_DIR / "mcp-config.json"
    if src.exists():
        sync_file(src, REPO_DIR / "mcp-config.json")


def git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )


def main() -> None:
    if not REPO_DIR.exists():
        print("⚠️  ~/copilot-config repo not found — skipping config sync.", file=sys.stderr)
        sys.exit(0)

    # Sync all components
    sync_agents()
    sync_skills()
    sync_scripts()
    sync_mcp_config()

    # Stage everything
    git(["add", "."])

    # Check if anything actually changed
    status = git(["diff", "--cached", "--quiet"])
    if status.returncode == 0:
        print("ℹ️  Copilot config unchanged — nothing to sync.")
        return

    # Show what changed
    diff = git(["diff", "--cached", "--stat"])
    print("📦 Config changes detected:")
    print(diff.stdout.strip())

    # Commit
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit_msg = (
        f"Auto-sync: {timestamp}\n\n"
        "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
    )
    result = git(["commit", "-m", commit_msg])
    if result.returncode != 0:
        print(f"⚠️  Git commit failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Push
    result = git(["push"])
    if result.returncode != 0:
        print(f"⚠️  Git push failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    print("✅ Copilot config synced to GitHub.")


if __name__ == "__main__":
    main()
