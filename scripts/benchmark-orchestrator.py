#!/usr/bin/env python3
"""Benchmark Orchestrator — drives the weekly benchmark pipeline.

Architecture: Deterministic Python handles prompt selection, file I/O, aggregation,
and reporting. Copilot CLI is called ONLY for execution (run the prompt) and grading
(score the output). This eliminates the failure mode where a single LLM agent gets
lost trying to self-orchestrate a complex multi-phase pipeline.

Usage:
    python3 benchmark-orchestrator.py [YYYY-WXX] [--dry-run] [--category CAT] [--verbose]
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

HOME = Path.home()
CONFIG = HOME / "copilot-config"
SOVEREIGN = HOME / "sovereign"
BENCHMARKS = CONFIG / "benchmarks"
PROMPTS_DIR = BENCHMARKS / "prompts"
RESULTS_DIR = BENCHMARKS / "results"
TRACES_DIR = BENCHMARKS / "traces"
REPORTS_DIR = BENCHMARKS / "reports"
COPILOT = "/opt/homebrew/bin/copilot"

# 7 scored categories with locked weights
# cwd = working directory for the copilot agent (most need the sovereign codebase)
CATEGORIES = {
    "code-generation":          {"pool_size": 4, "weight": 0.20, "executor_agent": "developer",            "cwd": SOVEREIGN},
    "context-retrieval":        {"pool_size": 4, "weight": 0.20, "executor_agent": "brain-data-retrieval",  "cwd": SOVEREIGN},
    "security-review":          {"pool_size": 4, "weight": 0.15, "executor_agent": "security",              "cwd": SOVEREIGN},
    "planning":                 {"pool_size": 4, "weight": 0.15, "executor_agent": "architect",             "cwd": SOVEREIGN},
    "hallucination-resistance": {"pool_size": 4, "weight": 0.10, "executor_agent": "brain-data-retrieval",  "cwd": SOVEREIGN},
    "error-recovery":           {"pool_size": 3, "weight": 0.05, "executor_agent": "developer",             "cwd": SOVEREIGN},
    "pipeline-compliance":      {"pool_size": 3, "weight": 0.15, "executor_agent": "orchestrator",          "cwd": SOVEREIGN},
}

# Cross-model grading: Claude executor → GPT grades, GPT executor → Claude grades
GRADING_MODELS = {
    "claude": "gpt-5.3-codex",
    "gpt": "claude-opus-4.6",
}

# Prompts requiring special environment setup — handled explicitly
SPECIAL_SETUP_PROMPTS = {
    "error-recovery/P2-empty-brain": {
        "setup": "mv ~/eroad-brain ~/eroad-brain.bak && mkdir ~/eroad-brain",
        "teardown": "rm -rf ~/eroad-brain && mv ~/eroad-brain.bak ~/eroad-brain",
    },
}

MAX_RAW_OUTPUT_FOR_GRADING = 15000  # chars — truncate longer outputs for grader context

# ── Logging ───────────────────────────────────────────────────────────────────

VERBOSE = False

def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {level}: {msg}", flush=True)

def log_verbose(msg: str):
    if VERBOSE:
        log(msg, "DEBUG")

# ── Prompt Selection (deterministic) ──────────────────────────────────────────

def select_prompt(week: str, category: str, pool_size: int) -> int:
    """SHA-256 rotation formula. Returns 0-indexed prompt number."""
    week_num = int(week.split("-W")[1])
    offset = int(hashlib.sha256(category.encode()).hexdigest()[:8], 16)
    return (week_num + offset) % pool_size

def find_prompt_file(category: str, index: int) -> Path:
    """Find P{index+1}-*.md in the category directory."""
    cat_dir = PROMPTS_DIR / category
    prefix = f"P{index + 1}-"
    for f in sorted(cat_dir.iterdir()):
        if f.name.startswith(prefix) and f.suffix == ".md":
            return f
    raise FileNotFoundError(f"No prompt matching {prefix}*.md in {cat_dir}")

# ── Prompt Parsing ────────────────────────────────────────────────────────────

def parse_prompt_file(path: Path) -> dict:
    """Parse a prompt .md file into named sections."""
    content = path.read_text()
    sections = {}
    current_section = None
    current_lines = []

    for line in content.splitlines():
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections

def extract_prompt_text(sections: dict) -> str:
    """Extract the actual prompt text, stripping code fences."""
    raw = sections.get("Prompt", "")
    lines = []
    in_fence = False
    for line in raw.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        lines.append(line)
    return "\n".join(lines).strip()

# ── Copilot CLI Execution ────────────────────────────────────────────────────

def run_copilot(prompt: str, agent: str = None, model: str = None,
                timeout: int = 300, cwd: Path = None) -> tuple:
    """Run copilot CLI, return (stdout, stderr, exit_code, duration_seconds)."""
    cmd = [COPILOT, "--allow-all"]
    if agent:
        cmd.extend(["--agent", agent])
    if model:
        cmd.extend(["--model", model])
    cmd.extend([
        "--add-dir", str(CONFIG),
        "--add-dir", str(HOME / ".copilot"),
        "--add-dir", str(HOME / "eroad-brain"),
        "-p", prompt,
    ])

    work_dir = str(cwd) if cwd else str(HOME)
    log_verbose(f"CMD: {' '.join(cmd[:8])}... (-p <{len(prompt)} chars>) cwd={work_dir}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            cwd=work_dir,
        )
        duration = time.time() - start
        return result.stdout.strip(), result.stderr.strip(), result.returncode, duration
    except subprocess.TimeoutExpired:
        duration = time.time() - start
        return f"TIMEOUT: Agent did not complete within {timeout}s", "", 124, duration
    except Exception as e:
        duration = time.time() - start
        return f"ERROR: {e}", "", 1, duration

def detect_executor_model(agent: str) -> str:
    """Read the model field from an agent's .agent.md frontmatter."""
    agent_file = HOME / ".copilot" / "agents" / f"{agent}.agent.md"
    if agent_file.exists():
        content = agent_file.read_text()
        match = re.search(r'^model:\s*(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return "claude-sonnet-4.6"

def get_grader_model(executor_model: str) -> str:
    """Cross-model grading selection."""
    if "gpt" in executor_model.lower():
        return GRADING_MODELS["gpt"]
    return GRADING_MODELS["claude"]

# ── Grading ───────────────────────────────────────────────────────────────────

def build_grading_prompt(category: str, prompt_text: str, rubric: str,
                         ground_truth: str, raw_output: str) -> str:
    """Build a structured grading prompt for the cross-model grader."""
    # Truncate raw output if too long
    if len(raw_output) > MAX_RAW_OUTPUT_FOR_GRADING:
        raw_output = raw_output[:MAX_RAW_OUTPUT_FOR_GRADING] + \
            f"\n\n[TRUNCATED — original was {len(raw_output)} chars]"

    return f"""You are a rigorous, calibrated benchmark grader for an AI agent system.
Grade the following agent output against the rubric. Be honest — do not inflate scores.

## Category: {category}

## Original Prompt Given to Agent
{prompt_text}

## Agent's Raw Output
{raw_output}

## Grading Rubric
{rubric}

## Ground Truth / Expected Behavior
{ground_truth}

## Instructions
Grade dimension by dimension. For each dimension:
1. Quote specific evidence from the agent's output
2. Score 0-100 using the rubric scale (0=fail, 50=partial, 100=excellent)
3. Brief reasoning

Output ONLY a JSON object (no markdown fences, no commentary outside the JSON):
{{
  "dimensions": {{
    "<dimension_name>": {{
      "score": <0-100>,
      "weight": <0.0-1.0>,
      "reasoning": "<brief reasoning with evidence>"
    }}
  }},
  "overall_score": <weighted_average_as_float>,
  "overall_reasoning": "<1-2 sentence summary>"
}}

Scoring calibration:
- 0-20: Fundamentally wrong or missing
- 30-50: Partial, significant gaps
- 60-70: Decent but notable issues
- 80-90: Good with minor issues
- 95-100: Near perfect, reserve for truly excellent work"""

def parse_grading_output(output: str) -> dict:
    """Extract grading JSON from grader output. Tries multiple strategies."""
    # Strategy 1: ```json ``` blocks
    match = re.search(r'```(?:json)?\s*\n(.*?)\n```', output, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 2: Find the outermost { ... } containing "dimensions"
    brace_depth = 0
    start_idx = None
    for i, ch in enumerate(output):
        if ch == '{':
            if brace_depth == 0:
                start_idx = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and start_idx is not None:
                candidate = output[start_idx:i+1]
                if '"dimensions"' in candidate:
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        pass
                start_idx = None

    # Strategy 3: Entire output as JSON
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        pass

    return {
        "parse_error": True,
        "dimensions": {},
        "overall_score": 0,
        "overall_reasoning": f"Failed to parse grading output ({len(output)} chars). First 300: {output[:300]}",
    }

# ── Special Setup Handling ────────────────────────────────────────────────────

def run_special_setup(prompt_key: str) -> bool:
    """Run special environment setup for prompts that need it. Returns True on success."""
    if prompt_key not in SPECIAL_SETUP_PROMPTS:
        return True

    setup_cmd = SPECIAL_SETUP_PROMPTS[prompt_key]["setup"]
    log(f"  Running special setup: {setup_cmd}")
    try:
        subprocess.run(setup_cmd, shell=True, check=True, capture_output=True, timeout=30)
        return True
    except Exception as e:
        log(f"  Setup failed: {e}", "ERROR")
        return False

def run_special_teardown(prompt_key: str):
    """Restore environment after special setup."""
    if prompt_key not in SPECIAL_SETUP_PROMPTS:
        return

    teardown_cmd = SPECIAL_SETUP_PROMPTS[prompt_key]["teardown"]
    log(f"  Running teardown: {teardown_cmd}")
    try:
        subprocess.run(teardown_cmd, shell=True, check=True, capture_output=True, timeout=30)
    except Exception as e:
        log(f"  CRITICAL: Teardown failed: {e} — manual intervention needed!", "ERROR")

# ── Trace Writing ─────────────────────────────────────────────────────────────

def write_trace(week: str, category: str, prompt_id: str, prompt_text: str,
                executor_model: str, grader_model: str, raw_output: str,
                grading: dict, duration: float):
    """Write a trace file following TRACE-FORMAT.md spec."""
    trace_dir = TRACES_DIR / week
    trace_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build dimension table rows
    dim_rows = []
    if "dimensions" in grading:
        for dim_name, dim_data in grading["dimensions"].items():
            weight = dim_data.get("weight", "?")
            score = dim_data.get("score", "?")
            reasoning = dim_data.get("reasoning", "")
            if isinstance(weight, (float, int)) and weight <= 1:
                weight = f"{weight*100:.0f}%"
            dim_rows.append(f"| {dim_name} | {weight} | {score} | {reasoning} |")

    overall = grading.get("overall_score", "N/A")
    overall_reasoning = grading.get("overall_reasoning", "No reasoning provided")

    trace_content = f"""# Trace: {category} — {week}

## Metadata
- Prompt ID: {prompt_id}
- Executor model: {executor_model}
- Grader model: {grader_model}
- Timestamp: {timestamp}
- Duration: {duration:.1f}s

## Prompt Sent
{prompt_text}

## Raw Output
{raw_output}

## Grading Reasoning
{overall_reasoning}

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
{chr(10).join(dim_rows)}

## Overall Score: {overall}/100
"""

    trace_file = trace_dir / f"{category}.md"
    trace_file.write_text(trace_content)
    log(f"  Trace: {trace_file.name} ({len(trace_content)} chars)")

# ── Category Execution ────────────────────────────────────────────────────────

def run_category(week: str, category: str, config: dict) -> dict:
    """Execute one benchmark category: select → execute → grade → trace."""
    log(f"━━━ {category} ━━━")

    # Phase 1: Select prompt
    index = select_prompt(week, category, config["pool_size"])
    prompt_file = find_prompt_file(category, index)
    prompt_id = prompt_file.stem
    log(f"  Prompt: {prompt_id}")

    sections = parse_prompt_file(prompt_file)
    prompt_text = extract_prompt_text(sections)
    rubric = sections.get("Grading Rubric", "No rubric provided")
    ground_truth = sections.get("Ground Truth",
                    sections.get("Expected Behavior",
                    sections.get("Expected Pipeline Steps", "No ground truth")))

    if not prompt_text:
        log(f"  ERROR: Empty prompt text in {prompt_file}", "ERROR")
        return {"score": 0, "error": "Empty prompt", "prompt_id": prompt_id}

    # Special setup if needed
    prompt_key = f"{category}/{prompt_id}"
    setup_ok = run_special_setup(prompt_key)
    if not setup_ok:
        return {"score": 0, "error": "Special setup failed", "prompt_id": prompt_id}

    try:
        return _execute_and_grade(week, category, config, prompt_id, prompt_text,
                                   rubric, ground_truth, config.get("cwd"))
    finally:
        run_special_teardown(prompt_key)

def _execute_and_grade(week, category, config, prompt_id, prompt_text,
                       rubric, ground_truth, cwd=None) -> dict:
    """Core execution + grading logic (separated for setup/teardown safety)."""
    executor_agent = config["executor_agent"]
    executor_model = detect_executor_model(executor_agent)

    # Phase 2: Execute
    log(f"  Executing: agent={executor_agent}, model={executor_model}")
    raw_output, stderr, exit_code, exec_duration = run_copilot(
        prompt=prompt_text,
        agent=executor_agent,
        timeout=600,
        cwd=cwd,
    )

    output_len = len(raw_output)
    log(f"  Done: {exec_duration:.0f}s, {output_len} chars, exit={exit_code}")

    if raw_output.startswith("TIMEOUT") or raw_output.startswith("ERROR"):
        log(f"  FAILED: {raw_output[:100]}", "ERROR")
        write_trace(week, category, prompt_id, prompt_text, executor_model,
                     "N/A", raw_output, {"overall_score": 0, "overall_reasoning": raw_output[:200]},
                     exec_duration)
        return {"score": 0, "error": raw_output[:200], "prompt_id": prompt_id,
                "executor_model": executor_model, "grader_model": "N/A", "dimensions": {}}

    # Phase 3: Grade with cross-model
    grader_model = get_grader_model(executor_model)
    log(f"  Grading: model={grader_model}")

    grading_prompt = build_grading_prompt(category, prompt_text, rubric,
                                          ground_truth, raw_output)
    grading_output, g_stderr, g_exit, grade_duration = run_copilot(
        prompt=grading_prompt,
        model=grader_model,
        timeout=300,
        cwd=cwd,
    )

    log(f"  Graded: {grade_duration:.0f}s, {len(grading_output)} chars")

    grading = parse_grading_output(grading_output)
    if grading.get("parse_error"):
        log(f"  WARNING: Grading parse failed — storing raw output in trace", "WARN")

    # Write trace
    total_duration = exec_duration + grade_duration
    write_trace(week, category, prompt_id, prompt_text, executor_model,
                grader_model, raw_output, grading, total_duration)

    # Build result
    score = round(float(grading.get("overall_score", 0)), 1)
    dimensions = {}
    if "dimensions" in grading:
        for dim_name, dim_data in grading["dimensions"].items():
            dimensions[dim_name] = dim_data.get("score", 0)

    result = {
        "score": score,
        "prompt_id": prompt_id,
        "executor_model": executor_model,
        "grader_model": grader_model,
        "dimensions": dimensions,
        "notes": grading.get("overall_reasoning", ""),
    }

    log(f"  Score: {score}/100")
    return result

# ── Results & Reports ─────────────────────────────────────────────────────────

def load_previous_results(week: str) -> dict | None:
    """Load the most recent previous week's results (up to 4 weeks back)."""
    year, wpart = week.split("-W")
    wnum = int(wpart)
    for i in range(1, 5):
        prev_week = f"{year}-W{wnum - i:02d}"
        prev_file = RESULTS_DIR / f"{prev_week}.json"
        if prev_file.exists():
            try:
                data = json.loads(prev_file.read_text())
                if data.get("system_version") == "v2":
                    return data
            except json.JSONDecodeError:
                continue
    return None

def write_results(week: str, scores: dict, prompt_rotation: dict,
                  cats_run: dict = None) -> dict:
    """Write the v2 results JSON file.
    
    When running a subset of categories (--category flag), merges new scores
    into any existing results file rather than overwriting with zeros.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cats_run = cats_run or CATEGORIES

    # Load existing results if this is a partial run (merge mode)
    results_file = RESULTS_DIR / f"{week}.json"
    existing_scores = {}
    if results_file.exists() and len(cats_run) < len(CATEGORIES):
        try:
            existing = json.loads(results_file.read_text())
            if existing.get("system_version") == "v2":
                existing_scores = existing.get("scores", {})
        except json.JSONDecodeError:
            pass

    # Merge: existing scores + new scores (new wins)
    merged_scores = {}
    for cat in CATEGORIES:
        cat_key = cat.replace("-", "_")
        if cat in scores:
            merged_scores[cat_key] = scores[cat]
        elif cat_key in existing_scores:
            merged_scores[cat_key] = existing_scores[cat_key]
        else:
            merged_scores[cat_key] = {"score": 0}

    # Calculate overall from categories that have real scores
    scored_cats = {k: v for k, v in merged_scores.items()
                   if v.get("prompt_id") or v.get("score", 0) > 0}
    if scored_cats:
        total_weight = sum(
            CATEGORIES[k.replace("_", "-")]["weight"]
            for k in scored_cats
            if k.replace("_", "-") in CATEGORIES
        )
        weighted_sum = sum(
            v.get("score", 0) * CATEGORIES[k.replace("_", "-")]["weight"]
            for k, v in scored_cats.items()
            if k.replace("_", "-") in CATEGORIES
        )
        overall = round(weighted_sum / total_weight, 1) if total_weight > 0 else 0
    else:
        overall = 0

    prev = load_previous_results(week)
    vs_previous = round(overall - prev["overall"], 1) if prev and "overall" in prev else None

    # Merge prompt rotation
    existing_rotation = {}
    if results_file.exists():
        try:
            existing_rotation = json.loads(results_file.read_text()).get("prompt_rotation", {})
        except json.JSONDecodeError:
            pass
    merged_rotation = {**existing_rotation, **prompt_rotation}

    results = {
        "week": week,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "system_version": "v2",
        "prompt_rotation": merged_rotation,
        "overall": overall,
        "vs_previous": vs_previous,
        "categories_scored": len(scored_cats),
        "categories_total": len(CATEGORIES),
        "scores": merged_scores,
    }

    results_file.write_text(json.dumps(results, indent=2))
    log(f"Results: {results_file} ({len(scored_cats)}/{len(CATEGORIES)} categories scored)")
    return results

def write_report(week: str, results: dict):
    """Write the human-readable markdown report."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    overall = results["overall"]
    vs_prev = results.get("vs_previous")
    trend = f" ({'+' if vs_prev > 0 else ''}{vs_prev} vs prev)" if vs_prev is not None else ""

    lines = [
        f"# Benchmark Report — {week}",
        f"",
        f"**Overall Score: {overall}/100{trend}**",
        f"",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## Summary",
        f"",
        f"| Category | Prompt | Score | Weight | Status |",
        f"|---|---|---|---|---|",
    ]

    for cat in CATEGORIES:
        cat_key = cat.replace("-", "_")
        cat_data = results["scores"].get(cat_key, {})
        score = cat_data.get("score", 0)
        weight = CATEGORIES[cat]["weight"]
        prompt_id = cat_data.get("prompt_id", "?")
        if score >= 70:
            status = "✅ PASS"
        elif score >= 50:
            status = "⚠️ WARN"
        else:
            status = "❌ FAIL"
        lines.append(f"| {cat} | {prompt_id} | {score} | {weight*100:.0f}% | {status} |")

    lines.extend(["", "## Category Details", ""])

    for cat in CATEGORIES:
        cat_key = cat.replace("-", "_")
        cat_data = results["scores"].get(cat_key, {})
        score = cat_data.get("score", 0)
        notes = cat_data.get("notes", "")
        dims = cat_data.get("dimensions", {})
        executor = cat_data.get("executor_model", "?")
        grader = cat_data.get("grader_model", "?")

        lines.append(f"### {cat} — {score}/100")
        lines.append(f"Executor: {executor} | Grader: {grader}")
        if dims:
            lines.append(f"Dimensions: {', '.join(f'{k}={v}' for k, v in dims.items())}")
        if notes:
            lines.append(f"Notes: {notes}")
        error = cat_data.get("error")
        if error:
            lines.append(f"**Error:** {error}")
        lines.append("")

    report_file = REPORTS_DIR / f"{week}.md"
    report_file.write_text("\n".join(lines))
    log(f"Report: {report_file}")

# ── Git Commit ────────────────────────────────────────────────────────────────

def git_commit(week: str):
    """Stage, commit, and push benchmark results."""
    git_cwd = str(CONFIG)
    subprocess.run(["git", "add", "benchmarks/"], capture_output=True, cwd=git_cwd)

    status = subprocess.run(["git", "status", "--porcelain", "benchmarks/"],
                            capture_output=True, text=True, cwd=git_cwd)
    if not status.stdout.strip():
        log("Nothing to commit — no changes in benchmarks/")
        return

    msg = f"benchmark: {week} results\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
    commit = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True, cwd=git_cwd)
    if commit.returncode != 0:
        log(f"Git commit failed: {commit.stderr[:200]}", "WARN")
        return

    push = subprocess.run(["git", "push"], capture_output=True, text=True, timeout=60, cwd=git_cwd)
    if push.returncode == 0:
        log("Committed and pushed to git")
    else:
        log(f"Git push failed: {push.stderr[:200]}", "WARN")

# ── Main Pipeline ─────────────────────────────────────────────────────────────

def main():
    global VERBOSE

    # Parse args
    args = sys.argv[1:]
    week = None
    dry_run = False
    single_category = None

    i = 0
    while i < len(args):
        if args[i] == "--dry-run":
            dry_run = True
        elif args[i] == "--verbose":
            VERBOSE = True
        elif args[i] == "--category" and i + 1 < len(args):
            single_category = args[i + 1]
            i += 1
        elif not args[i].startswith("-"):
            week = args[i]
        i += 1

    if not week:
        week = datetime.now().strftime("%G-W%V")

    log(f"╔══════════════════════════════════════════════════╗")
    log(f"║  Benchmark Orchestrator — {week:<23} ║")
    log(f"╚══════════════════════════════════════════════════╝")

    # Determine which categories to run
    cats_to_run = CATEGORIES
    if single_category:
        if single_category not in CATEGORIES:
            log(f"Unknown category: {single_category}", "ERROR")
            log(f"Valid: {', '.join(CATEGORIES.keys())}")
            sys.exit(1)
        cats_to_run = {single_category: CATEGORIES[single_category]}

    # Phase 1: Compute prompt rotation
    prompt_rotation = {}
    for cat, config in cats_to_run.items():
        index = select_prompt(week, cat, config["pool_size"])
        prompt_file = find_prompt_file(cat, index)
        prompt_rotation[cat.replace("-", "_")] = prompt_file.stem

    log(f"Prompt rotation:")
    for cat_key, prompt_id in prompt_rotation.items():
        log(f"  {cat_key}: {prompt_id}")

    if dry_run:
        log("DRY RUN — stopping before execution")
        print(json.dumps(prompt_rotation, indent=2))
        return

    # Phase 2-3: Execute and grade each category
    scores = {}
    total_start = time.time()

    for cat, config in cats_to_run.items():
        cat_start = time.time()
        try:
            scores[cat] = run_category(week, cat, config)
        except Exception as e:
            log(f"EXCEPTION in {cat}: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            scores[cat] = {"score": 0, "error": str(e), "prompt_id": "unknown"}

        cat_elapsed = time.time() - cat_start
        log(f"  Category time: {cat_elapsed:.0f}s")
        log("")

    total_elapsed = time.time() - total_start

    # Phase 4: Write results and report
    results = write_results(week, scores, prompt_rotation, cats_to_run)
    write_report(week, results)

    # Phase 5: Git commit
    try:
        git_commit(week)
    except Exception as e:
        log(f"Git commit failed: {e}", "WARN")

    # Summary
    log(f"")
    log(f"╔══════════════════════════════════════════════════╗")
    log(f"║  Benchmark Complete — {total_elapsed:.0f}s total{' '*18}║")
    log(f"║  Overall: {results['overall']}/100{' '*32}║")
    log(f"╚══════════════════════════════════════════════════╝")

    for cat in cats_to_run:
        cat_key = cat.replace("-", "_")
        score = results["scores"].get(cat_key, {}).get("score", 0)
        status = "✅" if score >= 70 else "⚠️" if score >= 50 else "❌"
        log(f"  {status} {cat}: {score}/100")

    # Exit with non-zero if overall < 50 (failure threshold)
    if results["overall"] < 50:
        sys.exit(1)


if __name__ == "__main__":
    main()
