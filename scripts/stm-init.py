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

import os
import re
import subprocess
import sys
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

    # Kill any existing dashboard on port before starting a new one
    DASHBOARD_PORT = port_override if port_override else 7700
    if not port_override:
        # Only kill existing dashboard if using default port (don't kill parallel sessions)
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{DASHBOARD_PORT}"],
                capture_output=True, text=True
            )
            for pid in result.stdout.strip().splitlines():
                subprocess.run(["kill", "-9", pid], capture_output=True)
            import time; time.sleep(0.3)  # brief pause for port to free up
        except Exception:
            pass

    # Launch dashboard on fixed port 7700 + open in browser
    # Use start_new_session=True so it survives shell session end (equivalent to nohup)
    if DASHBOARD_SCRIPT.exists():
        subprocess.Popen(
            [
                "python3", str(DASHBOARD_SCRIPT),
                str(stm_path),
                "--port", str(DASHBOARD_PORT),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        import time; time.sleep(0.8)
        subprocess.Popen(["open", f"http://localhost:{DASHBOARD_PORT}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Print paths for orchestrator to capture
    print(f"STM_PATH={stm_path}")
    print(f"STM_DIR={stm_dir}")


if __name__ == "__main__":
    main()
