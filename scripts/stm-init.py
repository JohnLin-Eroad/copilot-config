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
DASHBOARD_SCRIPT = Path.home() / ".copilot" / "scripts" / "stm-dashboard.py"


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:40]


def main():
    if len(sys.argv) < 2:
        print("Usage: stm-init.py <task-description> [--port PORT]", file=sys.stderr)
        sys.exit(1)

    # Parse optional --port flag
    args = sys.argv[1:]
    port_override = None
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

    # Write template
    stm_path.write_text(
        f"""---
task: "{slug}"
created: "{created_iso}"
---

# Short-Term Memory — {slug}

This file is the shared in-session context for all agents working on this task.
**Do not delete sections. Only append.**

---

## [STM] Task Brief
<!-- Written by Orchestrator at task start -->

Task: {task_desc}

Classification:
  Domain:     —
  Type:       —
  Blast:      —
  Pipeline:   —
  BRAIN_TYPE: —

---

## [STM] Fetch Manifest

---

## [STM] Brain Data

---

## [STM] Negative Context
<!-- Topics searched in brain but NOT found. All agents: do NOT speculate on these. -->
<!-- Raise PIPELINE_SIGNAL: NEED_DATA if any listed topic is critical to your work. -->

---

## [STM] Retrieval Log

---

## [STM] Agent Contributions
""",
        encoding="utf-8",
    )

    # Write .active symlink atomically so agent-dashboard picks up new task instantly
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
