#!/usr/bin/env python3
"""Tests for the brain-sleep-cron.sh launchd wrapper."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

WRAPPER = os.path.expanduser("~/.copilot/scripts/brain-sleep-cron.sh")
LOG = os.path.expanduser("~/.copilot/logs/brain-sleep.log")
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.johnlin.brain-sleep.plist")
LOCK = "/tmp/brain-sleep.lock"

PASS = FAIL = 0


def check(name: str, cond: bool, got=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}" + (f"  — {got}" if got is not None else ""))
    else:
        FAIL += 1
        print(f"  ✗ {name}  — got {got}")


def run_wrapper(env_overrides: dict | None = None) -> int:
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(["bash", WRAPPER], capture_output=True, text=True, env=env)
    return proc.returncode


def tail(n: int = 50) -> str:
    if not os.path.exists(LOG):
        return ""
    with open(LOG) as f:
        return "".join(f.readlines()[-n:])


def test_wrapper_executable():
    print("\nwrapper exists and is executable")
    p = Path(WRAPPER)
    check("script exists", p.exists())
    check("script executable", os.access(WRAPPER, os.X_OK))


def test_plist_present_and_valid():
    print("\nlaunchd plist exists and parses")
    check("plist exists", os.path.exists(PLIST))
    rc = subprocess.run(["plutil", "-lint", PLIST], capture_output=True).returncode
    check("plutil -lint passes", rc == 0, f"rc={rc}")


def test_dry_run_succeeds():
    print("\nwrapper exits 0 in dry-run mode and logs both job blocks")
    # Ensure no stale lock from a previous failed test
    if os.path.exists(LOCK):
        os.remove(LOCK)
    before = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    rc = run_wrapper({"BRAIN_SLEEP_DRY_RUN": "1"})
    check("wrapper exit 0", rc == 0, rc)
    after = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    check("log file grew", after > before, f"{before}→{after}")

    new = tail(60)
    check('"mark_stale" block logged', '"mark_stale"' in new or '"job": "mark-stale"' in new)
    check('"prune_access_log" block logged',
          '"prune_access_log"' in new or '"job": "prune-access-log"' in new)
    check("dry_run=true reported in log", '"dry_run": true' in new)
    check("start/end markers present",
          "brain-sleep start" in new and "brain-sleep end" in new)


def test_lockfile_prevents_concurrent_run():
    print("\nlockfile causes a 2nd concurrent invocation to skip")
    # Simulate a live previous run by writing our own PID to the lock
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))
    try:
        before = os.path.getsize(LOG) if os.path.exists(LOG) else 0
        rc = run_wrapper({"BRAIN_SLEEP_DRY_RUN": "1"})
        check("wrapper exits 0 (skip is non-error)", rc == 0, rc)
        new = tail(20)
        check("log says 'skip] previous run'", "[skip] previous run" in new,
              "logged" if "[skip]" in new else "not logged")
    finally:
        # Wrapper exits without touching the lock when it skips — clean up manually
        if os.path.exists(LOCK):
            os.remove(LOCK)


def test_stale_lock_is_reclaimed():
    print("\nstale lock (PID not alive) is removed and wrapper proceeds")
    # Use a PID very unlikely to exist
    with open(LOCK, "w") as f:
        f.write("9999999")
    rc = run_wrapper({"BRAIN_SLEEP_DRY_RUN": "1"})
    check("wrapper exit 0", rc == 0, rc)
    check("lockfile removed after run", not os.path.exists(LOCK))


def test_launchd_job_registered():
    print("\nlaunchd job is registered")
    out = subprocess.run(
        ["launchctl", "list"], capture_output=True, text=True
    ).stdout
    check("com.johnlin.brain-sleep in launchctl list",
          "com.johnlin.brain-sleep" in out)


def main() -> int:
    test_wrapper_executable()
    test_plist_present_and_valid()
    test_dry_run_succeeds()
    test_lockfile_prevents_concurrent_run()
    test_stale_lock_is_reclaimed()
    test_launchd_job_registered()
    print("\n" + "=" * 48)
    print(f"{PASS}/{PASS+FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
