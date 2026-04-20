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
        print("Usage: stm-init.py <task-description>", file=sys.stderr)
        sys.exit(1)

    task_desc = " ".join(sys.argv[1:])
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

    # Launch dashboard in background (new terminal window on macOS)
    if DASHBOARD_SCRIPT.exists():
        try:
            # Try to open in a new Terminal window
            script = f'tell application "Terminal" to do script "python3 {DASHBOARD_SCRIPT} \\"{stm_path}\\" && exit"'
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            # Fallback: launch headlessly in background
            subprocess.Popen(
                ["python3", str(DASHBOARD_SCRIPT), str(stm_path), "--no-open"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    # Print paths for orchestrator to capture
    print(f"STM_PATH={stm_path}")
    print(f"STM_DIR={stm_dir}")


if __name__ == "__main__":
    main()
