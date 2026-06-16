#!/usr/bin/env python3
"""
STM Init — Creates a new STM file and launches the live dashboard.

Called by the orchestrator at pipeline start.

Usage:
  python3 ~/.copilot/scripts/stm-init.py <task-description>
  
Output (stdout):
  STM_PATH=/path/to/short-term-memory.md
  STM_DIR=/path/to/dir
"""

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

STM_ROOT = Path.home() / ".copilot" / "stm"
STM_FILENAME = "short-term-memory.md"
DASHBOARD_SCRIPT = Path.home() / ".copilot" / "scripts" / "stm-dashboard.py"
DIGEST_MAX_BYTES = 2048  # ~2KB cap for prior-session digest
PRUNE_AGE_DAYS = 7      # prune STM dirs older than this


def _prune_old_stm_dirs():
    """Remove STM directories older than PRUNE_AGE_DAYS (by file mtime)."""
    if not STM_ROOT.exists():
        return
    cutoff = datetime.now().timestamp() - (PRUNE_AGE_DAYS * 86400)
    for entry in os.scandir(str(STM_ROOT)):
        if not entry.is_dir(follow_symlinks=False) or entry.name.startswith("."):
            continue
        stm_file = Path(entry.path) / STM_FILENAME
        try:
            mtime = stm_file.stat().st_mtime if stm_file.exists() else entry.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            # Remove files inside the dir, then the dir itself
            try:
                for f in os.scandir(entry.path):
                    try:
                        os.unlink(f.path)
                    except OSError:
                        pass
                os.rmdir(entry.path)
            except OSError:
                pass  # partially cleaned — next run will finish


def _build_daily_digest(today_prefix: str, exclude_dir: Path) -> str:
    """Scan today's prior STM files, extract key knowledge, compress to ~2KB."""
    if not STM_ROOT.exists():
        return ""
    digests = []
    for entry in sorted(os.scandir(str(STM_ROOT)), key=lambda e: e.name):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if not entry.name.startswith(today_prefix):
            continue
        stm_path = Path(entry.path) / STM_FILENAME
        if not stm_path.exists() or stm_path.parent == exclude_dir:
            continue
        try:
            content = stm_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Extract decisions, findings, file paths
        lines = content.splitlines()
        slug = entry.name[len(today_prefix):]  # strip date prefix
        extracted = []
        for line in lines:
            ls = line.strip()
            # Capture decision/finding/file lines from agent contributions
            if any(ls.startswith(k) for k in ("Decisions:", "Findings:", "Files:", "Next:", "Status:")):
                extracted.append(ls)
        if extracted:
            digests.append(f"### {slug}\n" + "\n".join(extracted))
    if not digests:
        return ""
    # Assemble and cap at DIGEST_MAX_BYTES
    full = "\n\n".join(digests)
    if len(full.encode("utf-8")) > DIGEST_MAX_BYTES:
        # Truncate to fit, preserving complete lines
        cut = full.encode("utf-8")[:DIGEST_MAX_BYTES]
        full = cut.decode("utf-8", errors="ignore").rsplit("\n", 1)[0] + "\n…(truncated)"
    return full


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:40]


# ── Heuristic classifier ──────────────────────────────────────────────────
# Goal: provide a sensible default Classification block so the dashboard isn't
# empty when an orchestrator skips step 2. The agent can overwrite these later
# via write-stm.sh — values here are best-guess from the user's prompt text.

EROAD_KEYWORDS = (
    "eroad", "sovereign", "rucus", "media-service", "media service",
    "nz-au", "drp-", "ehb-", "tpr-", "vehiclecontroller", "media_service",
    "transport", "ezeta", "ezt", "vehicle-service",
)
PERSONAL_KEYWORDS = (
    "copilot", ".copilot", "agent dashboard", "stm", "brain-graph",
    "obsidian", "benchmark", "ai-learning", "session-state", "orchestration",
    "agent factory", "skill", "hook",
)
ARCH_KEYWORDS = ("architecture", "design", "adr", "refactor", "redesign", "decompose")
DOC_KEYWORDS = ("document", "readme", "spec", "confluence", "write up", "summary")
RESEARCH_KEYWORDS = ("research", "investigate", "explore", "analyse", "analyze", "look into", "find out")
DISCOVERY_KEYWORDS = ("map", "inventory", "what is in", "discover", "list all")
OPS_KEYWORDS = ("deploy", "rollout", "rollback", "migration", "infra", "ci/cd", "pipeline run")
CODE_KEYWORDS = (
    "fix", "implement", "add ", "build ", "write ", "create ", "patch",
    "update ", "modify", "change", "refactor", "tackle", "apply",
    "edit", "bug", "wire ", "extend ", "ticket", "do this",
)
HIGH_BLAST_KEYWORDS = ("production", "prod ", "schema", "drop ", "force push", "delete table", "shared branch")
MEDIUM_BLAST_KEYWORDS = ("migration", "api break", "across services", "multiple repos", "deploy", "infra")
QUESTION_PREFIXES = ("what ", "why ", "how ", "when ", "where ", "is there", "are there", "can ", "could ", "should ", "?")


def classify_prompt(text: str) -> dict:
    """Best-effort heuristic classification. Returns dict with Domain/Type/Blast/Pipeline/BRAIN_TYPE."""
    t = text.lower().strip()

    # Domain
    domain = "personal"
    if any(k in t for k in EROAD_KEYWORDS):
        domain = "eroad"
    elif any(k in t for k in PERSONAL_KEYWORDS):
        domain = "personal"

    # Type
    if t.endswith("?") or any(t.startswith(p) for p in QUESTION_PREFIXES):
        ttype = "question"
    elif any(k in t for k in ARCH_KEYWORDS):
        ttype = "architecture"
    elif any(k in t for k in DOC_KEYWORDS):
        ttype = "documentation"
    elif any(k in t for k in DISCOVERY_KEYWORDS):
        ttype = "discovery"
    elif any(k in t for k in RESEARCH_KEYWORDS):
        ttype = "research"
    elif any(k in t for k in OPS_KEYWORDS):
        ttype = "ops"
    elif any(k in t for k in CODE_KEYWORDS):
        ttype = "code-change"
    else:
        ttype = "general"

    # Blast radius — conservative default
    if any(k in t for k in HIGH_BLAST_KEYWORDS):
        blast = "HIGH"
    elif any(k in t for k in MEDIUM_BLAST_KEYWORDS):
        blast = "MEDIUM"
    elif ttype in ("question", "research", "discovery", "documentation"):
        blast = "LOW"
    else:
        blast = "MEDIUM"

    # Pipeline
    if ttype == "question" or blast == "LOW" and domain == "personal":
        pipeline = "minimal"
    elif domain == "eroad" and blast in ("HIGH", "CRITICAL"):
        pipeline = "full-transformation"
    else:
        pipeline = "standard"

    return {
        "Domain": domain,
        "Type": ttype,
        "Blast": blast,
        "Pipeline": pipeline,
        "BRAIN_TYPE": domain,  # mirrors Domain by convention
        "_auto": True,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: stm-init.py <task-description> [--port PORT]", file=sys.stderr)
        sys.exit(1)

    # Parse optional flags
    args = sys.argv[1:]
    port_override = None
    no_open = False
    if "--no-open" in args:
        no_open = True
        args = [a for a in args if a != "--no-open"]
    if "--port" in args:
        idx = args.index("--port")
        try:
            port_override = int(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        except (IndexError, ValueError):
            print("Error: --port requires an integer value", file=sys.stderr)
            sys.exit(1)

    task_desc = " ".join(args)
    slug = slugify(task_desc)
    date_str = datetime.now().strftime("%Y-%m-%d")
    created_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Heuristic classification — agent should verify/correct via write-stm.sh
    cls = classify_prompt(task_desc)

    # Housekeeping: prune old STM directories (>7 days)
    try:
        _prune_old_stm_dirs()
    except Exception:
        pass  # non-fatal

    stm_dir = STM_ROOT / f"{date_str}-{slug}"
    stm_dir.mkdir(parents=True, exist_ok=True)

    # Write .dashboard-id sidecar — stable UUID4 identity for agent-dashboard
    # Uses O_CREAT|O_EXCL for atomic create (no race with concurrent sessions)
    dashboard_id_path = stm_dir / ".dashboard-id"
    if not dashboard_id_path.exists():
        try:
            fd = os.open(str(dashboard_id_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, str(uuid.uuid4()).encode("utf-8"))
            finally:
                os.close(fd)
        except FileExistsError:
            pass  # another process beat us — fine, they wrote theirs
        except OSError:
            pass  # disk full / permissions — non-fatal; dashboard creates fallback

    stm_path = stm_dir / "short-term-memory.md"

    # Build daily digest from prior sessions today
    daily_digest = _build_daily_digest(date_str + "-", stm_dir)
    digest_section = ""
    if daily_digest:
        digest_section = f"""
---

## [STM] Prior Sessions Today
<!-- Auto-injected by stm-init.py — knowledge from earlier sessions today -->

{daily_digest}
"""

    # Write template
    stm_path.write_text(
        f"""---
task: "{slug}"
created: "{created_iso}"
---

# STM — {slug}

Shared in-session context. Append only; do not delete sections.

---

## [STM] Task Brief

Task: {task_desc}

Classification: (auto-classified by stm-init heuristic — orchestrator should verify/correct)
  Domain:     {cls['Domain']}
  Type:       {cls['Type']}
  Blast:      {cls['Blast']}
  Pipeline:   {cls['Pipeline']}
  BRAIN_TYPE: {cls['BRAIN_TYPE']}
{digest_section}
---

## [STM] Fetch Manifest

---

## [STM] Brain Data

---

## [STM] Negative Context
<!-- Brain searches that returned nothing. No speculation on these topics — raise NEED_DATA. -->

---

## [STM] Retrieval Log

---

## [STM] Agent Contributions
""",
        encoding="utf-8",
    )

    # Write .active symlink — optional hint for agent-dashboard (auto-selects this workflow).
    # Dashboard uses WorkflowRegistry for discovery and does NOT require .active to function.
    active_link = STM_ROOT / ".active"
    tmp_link = STM_ROOT / f".active.tmp.{os.getpid()}"
    try:
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        os.symlink(stm_dir, tmp_link)
        os.replace(str(tmp_link), str(active_link))
    except Exception:
        pass  # non-fatal; dashboard falls back to mtime scan

    # Open the persistent agent-dashboard (port 8765, always running via launchd).
    # Use /health for accurate readiness — TCP connect only proves socket is open, not serving.
    import time
    import urllib.request
    AGENT_DASHBOARD_PORT = 8765

    dashboard_up = False
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://localhost:{AGENT_DASHBOARD_PORT}/health", timeout=1
            ) as resp:
                health = json.loads(resp.read())
                if health.get("status") == "ok":
                    dashboard_up = True
                    break
        except Exception:
            pass
        time.sleep(0.5)

    if dashboard_up:
        if not no_open:
            subprocess.Popen(
                ["open", f"http://localhost:{AGENT_DASHBOARD_PORT}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    else:
        # Fallback: launch the old per-task STM dashboard if agent-dashboard isn't available
        BASE_PORT = 7700
        MAX_PARALLEL = 10
        DASHBOARD_PORT = port_override or BASE_PORT
        if not port_override:
            for p in range(BASE_PORT, BASE_PORT + MAX_PARALLEL):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    if s.connect_ex(("localhost", p)) != 0:
                        DASHBOARD_PORT = p
                        break
        if DASHBOARD_SCRIPT.exists():
            subprocess.Popen(
                [
                    "python3", str(DASHBOARD_SCRIPT),
                    str(stm_path),
                    "--port", str(DASHBOARD_PORT),
                    "--no-open",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            time.sleep(0.8)
            subprocess.Popen(
                ["open", f"http://localhost:{DASHBOARD_PORT}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    # Print paths for orchestrator to capture
    print(f"STM_PATH={stm_path}")
    print(f"STM_DIR={stm_dir}")


if __name__ == "__main__":
    main()
