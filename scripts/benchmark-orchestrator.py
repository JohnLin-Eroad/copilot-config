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
import math
import os
import random
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
# timeout = max seconds for execution (default 600, override per category)
CATEGORIES = {
    "code-generation":          {"pool_size": 6, "weight": 0.20, "executor_agent": "developer",            "cwd": SOVEREIGN},
    "context-retrieval":        {"pool_size": 4, "weight": 0.20, "executor_agent": "brain-data-retrieval",  "cwd": SOVEREIGN},
    "security-review":          {"pool_size": 4, "weight": 0.15, "executor_agent": "security",              "cwd": SOVEREIGN},
    "planning":                 {"pool_size": 6, "weight": 0.15, "executor_agent": "architect",             "cwd": SOVEREIGN},
    "hallucination-resistance": {"pool_size": 4, "weight": 0.10, "executor_agent": "brain-data-retrieval",  "cwd": SOVEREIGN},
    "error-recovery":           {"pool_size": 3, "weight": 0.05, "executor_agent": "developer",             "cwd": SOVEREIGN},
    "pipeline-compliance":      {"pool_size": 3, "weight": 0.15, "executor_agent": "orchestrator",          "cwd": SOVEREIGN, "timeout": 1200},
}

# Cross-model grading: Claude executor → GPT grades, GPT executor → Claude grades
GRADING_MODELS = {
    "claude": "gpt-5.3-codex",
    "gpt": "claude-opus-4.6",
}

# Prompts requiring special environment setup — handled explicitly
SPECIAL_SETUP_PROMPTS = {
    "error-recovery/P2-empty-brain": {
        "setup": "mv ~/eroad-brain /tmp/.eroad-brain-bench-backup && mkdir ~/eroad-brain",
        "teardown": "rm -rf ~/eroad-brain && mv /tmp/.eroad-brain-bench-backup ~/eroad-brain",
    },
}

MAX_RAW_OUTPUT_FOR_GRADING = 15000  # chars — truncate longer outputs for grader context

# ── P3: Cost & Token Estimation ───────────────────────────────────────────────

# Per-million-token pricing (USD). Conservative public-list prices.
PRICING_USD_PER_M_TOKENS = {
    "claude-opus-4.7":   {"prompt": 15.0, "completion": 75.0},
    "claude-opus-4.6":   {"prompt": 15.0, "completion": 75.0},
    "claude-sonnet-4.6": {"prompt": 3.0,  "completion": 15.0},
    "claude-haiku-4.5":  {"prompt": 1.0,  "completion": 5.0},
    "gpt-5.5":           {"prompt": 10.0, "completion": 30.0},
    "gpt-5.4":           {"prompt": 5.0,  "completion": 15.0},
    "gpt-5.4-mini":      {"prompt": 0.5,  "completion": 1.5},
    "gpt-5-mini":        {"prompt": 0.5,  "completion": 1.5},
    "gpt-5.3-codex":     {"prompt": 5.0,  "completion": 15.0},
    "gpt-4.1":           {"prompt": 2.0,  "completion": 8.0},
}

def estimate_tokens(text: str) -> int:
    """Rough estimate: 4 chars per token (English-skewed)."""
    return max(0, len(text or "") // 4)

def estimate_cost_usd(model: str, prompt_chars: int, completion_chars: int) -> float:
    """Approx USD cost for a single call."""
    price = PRICING_USD_PER_M_TOKENS.get(model)
    if not price:
        return 0.0
    p_tok = prompt_chars // 4
    c_tok = completion_chars // 4
    return (p_tok / 1_000_000) * price["prompt"] + (c_tok / 1_000_000) * price["completion"]

def count_tool_calls(raw_output: str) -> int:
    """Heuristic tool-call counter: regex over rendered CLI output patterns."""
    if not raw_output:
        return 0
    patterns = [
        r"●\s*(bash|view|edit|create|grep|glob|web_fetch|task|skill|sql|report_intent)",
        r"Tool call:\s*\w+",
        r"Running tool:\s*\w+",
    ]
    n = 0
    for p in patterns:
        n += len(re.findall(p, raw_output))
    return n

# ── P1: Deterministic Auto-Checks ─────────────────────────────────────────────

def parse_auto_checks(sections: dict) -> list:
    """Parse the `## Auto-Checks` section from a prompt file.

    Format inside the section is a fenced ```yaml block with a list of checks.
    Each check supports keys:
      - name (required)
      - must_contain_any / must_contain_all / must_not_contain (list of strings)
      - regex / regex_not (string)
      - case_insensitive (bool, default false)
    """
    section = sections.get("Auto-Checks") or sections.get("Auto Checks")
    if not section:
        return []
    # Strip ```yaml ... ``` fence
    m = re.search(r"```(?:yaml|yml)?\s*\n(.*?)\n```", section, re.DOTALL)
    body = m.group(1) if m else section
    # Fast path: PyYAML if available
    try:
        import yaml  # type: ignore
        parsed = yaml.safe_load(body)
        if isinstance(parsed, list):
            return [c for c in parsed if isinstance(c, dict) and c.get("name")]
    except Exception:
        pass
    # Fallback: tiny line-based parser (handles only what we generate)
    checks = []
    current = None
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- name:"):
            if current:
                checks.append(current)
            current = {"name": line.split(":", 1)[1].strip().strip('"').strip("'")}
            continue
        if current is None:
            continue
        if ":" not in line:
            continue
        key, _, val = line.lstrip().partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            items = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
            current[key] = items
        elif val.lower() in ("true", "false"):
            current[key] = (val.lower() == "true")
        else:
            current[key] = val.strip('"').strip("'")
    if current:
        checks.append(current)
    return checks

def run_auto_check(check: dict, text: str) -> dict:
    """Execute a single auto-check; returns {name, result, type, detail}."""
    name = check.get("name", "unnamed")
    haystack = text or ""
    ci = bool(check.get("case_insensitive", False))
    if ci:
        haystack_cmp = haystack.lower()
    else:
        haystack_cmp = haystack

    def _norm(needles):
        if isinstance(needles, str):
            needles = [needles]
        return [n.lower() if ci else n for n in (needles or [])]

    if "must_contain_any" in check:
        needles = _norm(check["must_contain_any"])
        hit = next((n for n in needles if n in haystack_cmp), None)
        return {"name": name, "type": "must_contain_any",
                "result": "PASS" if hit else "FAIL",
                "detail": f"matched: {hit!r}" if hit else f"none of {len(needles)} found"}
    if "must_contain_all" in check:
        needles = _norm(check["must_contain_all"])
        missing = [n for n in needles if n not in haystack_cmp]
        return {"name": name, "type": "must_contain_all",
                "result": "PASS" if not missing else "FAIL",
                "detail": "all matched" if not missing else f"missing: {missing}"}
    if "must_not_contain" in check:
        needles = _norm(check["must_not_contain"])
        hit = next((n for n in needles if n in haystack_cmp), None)
        return {"name": name, "type": "must_not_contain",
                "result": "PASS" if not hit else "FAIL",
                "detail": "no forbidden strings present" if not hit else f"forbidden hit: {hit!r}"}
    if "regex" in check:
        flags = re.IGNORECASE if ci else 0
        m = re.search(check["regex"], haystack, flags)
        return {"name": name, "type": "regex",
                "result": "PASS" if m else "FAIL",
                "detail": f"matched: {m.group(0)[:80]!r}" if m else "no match"}
    if "regex_not" in check:
        flags = re.IGNORECASE if ci else 0
        m = re.search(check["regex_not"], haystack, flags)
        return {"name": name, "type": "regex_not",
                "result": "PASS" if not m else "FAIL",
                "detail": "no forbidden match" if not m else f"forbidden match: {m.group(0)[:80]!r}"}
    return {"name": name, "type": "unknown", "result": "FAIL", "detail": "no check key recognised"}

def run_auto_checks(checks: list, text: str) -> dict:
    """Run all checks, return aggregate result."""
    if not checks:
        return {"present": False, "total": 0, "passed": 0, "pass_rate": None, "results": []}
    results = [run_auto_check(c, text) for c in checks]
    passed = sum(1 for r in results if r["result"] == "PASS")
    return {
        "present": True,
        "total": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results) * 100, 1),
        "results": results,
    }

# ── P7: Bootstrap Confidence Interval ─────────────────────────────────────────

def bootstrap_ci(values, confidence=0.90, resamples=1000, seed=42):
    """Percentile-method bootstrap CI for the mean of `values`."""
    if not values:
        return (None, None)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = (1 - confidence) / 2
    lo_idx = int(alpha * resamples)
    hi_idx = int((1 - alpha) * resamples) - 1
    return (round(means[lo_idx], 2), round(means[max(hi_idx, 0)], 2))

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
                grading: dict, duration: float, cost: dict = None,
                auto_checks: dict = None, run_index: int = None):
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

    # P3: cost + token metadata block
    cost_lines = ""
    if cost:
        et = cost.get("executor_tokens", {})
        gt = cost.get("grader_tokens", {})
        cost_lines = (
            f"- Estimated cost (USD): {cost.get('total_usd', 0.0):.4f}\n"
            f"- Executor tokens (est.): prompt={et.get('prompt',0)} / completion={et.get('completion',0)} / total={et.get('total',0)}\n"
            f"- Grader tokens (est.):   prompt={gt.get('prompt',0)} / completion={gt.get('completion',0)} / total={gt.get('total',0)}\n"
            f"- Tool calls (heuristic): {cost.get('tool_calls', 0)}\n"
        )
    run_line = f"- Run index: {run_index}\n" if run_index else ""

    # P1: deterministic checks block
    auto_block = ""
    if auto_checks and auto_checks.get("present"):
        rows = []
        for r in auto_checks.get("results", []):
            rows.append(f"| {r['name']} | {r['type']} | {r['result']} | {r['detail']} |")
        auto_block = (
            "\n## Deterministic Checks\n\n"
            f"Aggregate: {auto_checks['passed']}/{auto_checks['total']} PASS "
            f"({auto_checks['pass_rate']}%)\n\n"
            "| Check name | Type | Result | Detail |\n"
            "|---|---|---|---|\n"
            + "\n".join(rows) + "\n"
        )

    trace_content = f"""# Trace: {category} — {week}

## Metadata
- Prompt ID: {prompt_id}
- Executor model: {executor_model}
- Grader model: {grader_model}
- Timestamp: {timestamp}
- Duration: {duration:.1f}s
{run_line}{cost_lines}
## Prompt Sent
{prompt_text}

## Raw Output
{raw_output}
{auto_block}
## Grading Reasoning
{overall_reasoning}

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
{chr(10).join(dim_rows)}

## Overall Score: {overall}/100
"""

    fname = f"{category}.md" if not run_index else f"{category}.run{run_index}.md"
    trace_file = trace_dir / fname
    trace_file.write_text(trace_content)
    log(f"  Trace: {trace_file.name} ({len(trace_content)} chars)")

# ── Category Execution ────────────────────────────────────────────────────────

def run_category(week: str, category: str, config: dict, reliability_n: int = 1) -> dict:
    """Execute one benchmark category: select → execute → grade → trace.

    If reliability_n > 1, runs N times and aggregates score_mean/stddev/pass_rate.
    """
    log(f"━━━ {category} ━━━")

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
    auto_checks_spec = parse_auto_checks(sections)
    if auto_checks_spec:
        log(f"  Auto-checks declared: {len(auto_checks_spec)}")

    if not prompt_text:
        log(f"  ERROR: Empty prompt text in {prompt_file}", "ERROR")
        return {"score": 0, "error": "Empty prompt", "prompt_id": prompt_id}

    prompt_key = f"{category}/{prompt_id}"
    runs = []
    for run_i in range(1, max(1, reliability_n) + 1):
        if reliability_n > 1:
            log(f"  ── reliability run {run_i}/{reliability_n} ──")
        if not run_special_setup(prompt_key):
            runs.append({"score": 0, "error": "Special setup failed",
                         "prompt_id": prompt_id})
            continue
        try:
            r = _execute_and_grade(week, category, config, prompt_id, prompt_text,
                                   rubric, ground_truth, auto_checks_spec,
                                   config.get("cwd"),
                                   run_index=(run_i if reliability_n > 1 else None))
            runs.append(r)
        finally:
            run_special_teardown(prompt_key)

    if reliability_n <= 1:
        return runs[0]

    # Aggregate reliability runs
    scores = [r.get("score", 0) for r in runs]
    pass_threshold = 75
    pass_n = sum(1 for s in scores if s >= pass_threshold)
    mean = round(sum(scores) / len(scores), 1)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    stddev = round(math.sqrt(variance), 2)
    base = runs[0].copy()
    base["score"] = mean
    base["reliability"] = {
        "n": len(runs),
        "score_mean": mean,
        "score_min": min(scores),
        "score_max": max(scores),
        "score_stddev": stddev,
        "pass_at_n": pass_n,
        "pass_rate": round(pass_n / len(runs) * 100, 1),
        "pass_threshold": pass_threshold,
        "per_run_scores": scores,
    }
    return base

def _execute_and_grade(week, category, config, prompt_id, prompt_text,
                       rubric, ground_truth, auto_checks_spec=None,
                       cwd=None, run_index=None) -> dict:
    """Core execution + grading logic (separated for setup/teardown safety)."""
    executor_agent = config["executor_agent"]
    executor_model = detect_executor_model(executor_agent)

    log(f"  Executing: agent={executor_agent}, model={executor_model}")
    raw_output, stderr, exit_code, exec_duration = run_copilot(
        prompt=prompt_text,
        agent=executor_agent,
        timeout=config.get("timeout", 600),
        cwd=cwd,
    )

    output_len = len(raw_output)
    log(f"  Done: {exec_duration:.0f}s, {output_len} chars, exit={exit_code}")

    tool_calls = count_tool_calls(raw_output)
    auto_checks = run_auto_checks(auto_checks_spec or [], raw_output)
    if auto_checks.get("present"):
        log(f"  Auto-checks: {auto_checks['passed']}/{auto_checks['total']} "
            f"PASS ({auto_checks['pass_rate']}%)")

    if raw_output.startswith("TIMEOUT") or raw_output.startswith("ERROR"):
        log(f"  FAILED: {raw_output[:100]}", "ERROR")
        exec_cost = estimate_cost_usd(executor_model, len(prompt_text), output_len)
        cost = {
            "executor_tokens": {
                "prompt": estimate_tokens(prompt_text),
                "completion": estimate_tokens(raw_output),
                "total": estimate_tokens(prompt_text) + estimate_tokens(raw_output),
            },
            "grader_tokens": {"prompt": 0, "completion": 0, "total": 0},
            "total_usd": round(exec_cost, 4),
            "tool_calls": tool_calls,
        }
        write_trace(week, category, prompt_id, prompt_text, executor_model,
                     "N/A", raw_output,
                     {"overall_score": 0, "overall_reasoning": raw_output[:200]},
                     exec_duration, cost=cost, auto_checks=auto_checks,
                     run_index=run_index)
        return {"score": 0, "error": raw_output[:200], "prompt_id": prompt_id,
                "executor_model": executor_model, "grader_model": "N/A",
                "dimensions": {}, "cost": cost, "auto_checks": auto_checks}

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

    exec_cost = estimate_cost_usd(executor_model, len(prompt_text), output_len)
    grader_cost = estimate_cost_usd(grader_model, len(grading_prompt), len(grading_output))
    cost = {
        "executor_tokens": {
            "prompt": estimate_tokens(prompt_text),
            "completion": estimate_tokens(raw_output),
            "total": estimate_tokens(prompt_text) + estimate_tokens(raw_output),
        },
        "grader_tokens": {
            "prompt": estimate_tokens(grading_prompt),
            "completion": estimate_tokens(grading_output),
            "total": estimate_tokens(grading_prompt) + estimate_tokens(grading_output),
        },
        "total_usd": round(exec_cost + grader_cost, 4),
        "tool_calls": tool_calls,
    }

    total_duration = exec_duration + grade_duration
    write_trace(week, category, prompt_id, prompt_text, executor_model,
                grader_model, raw_output, grading, total_duration,
                cost=cost, auto_checks=auto_checks, run_index=run_index)

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
        "cost": cost,
        "auto_checks": auto_checks,
    }

    log(f"  Score: {score}/100  Cost: ${cost['total_usd']:.4f}  ToolCalls: {tool_calls}")
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

    # P7: bootstrap CI from all dimension scores
    all_dim_scores = []
    for cat_data in scored_cats.values():
        dims = cat_data.get("dimensions", {}) or {}
        for v in dims.values():
            try:
                all_dim_scores.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(all_dim_scores) >= 5:
        ci_low, ci_high = bootstrap_ci(all_dim_scores, confidence=0.90)
        ci_half_width = (ci_high - ci_low) / 2
        significant = (vs_previous is not None
                       and abs(vs_previous) > 1.5 * ci_half_width)
    else:
        ci_low, ci_high, significant = None, None, None

    # P3: cost summary
    total_usd = 0.0
    cost_by_cat = {}
    total_tool_calls = 0
    for cat_key, cat_data in scored_cats.items():
        c = cat_data.get("cost", {}) or {}
        usd = float(c.get("total_usd", 0.0) or 0.0)
        cost_by_cat[cat_key] = round(usd, 4)
        total_usd += usd
        total_tool_calls += int(c.get("tool_calls", 0) or 0)
    most_expensive = max(cost_by_cat.items(), key=lambda kv: kv[1])[0] if cost_by_cat else None

    # P1: deterministic check aggregate
    det_passed = 0
    det_total = 0
    det_present_cats = 0
    for cat_data in scored_cats.values():
        ac = cat_data.get("auto_checks", {}) or {}
        if ac.get("present"):
            det_present_cats += 1
            det_passed += ac.get("passed", 0)
            det_total += ac.get("total", 0)
    det_pass_rate = round(det_passed / det_total * 100, 1) if det_total else None

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
        "confidence_interval_90": [ci_low, ci_high] if ci_low is not None else None,
        "significant_vs_previous": significant,
        "deterministic_checks": {
            "categories_with_checks": det_present_cats,
            "checks_passed": det_passed,
            "checks_total": det_total,
            "pass_rate": det_pass_rate,
        },
        "cost_summary": {
            "total_usd": round(total_usd, 4),
            "by_category": cost_by_cat,
            "most_expensive_category": most_expensive,
            "total_tool_calls": total_tool_calls,
        },
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

    ci = results.get("confidence_interval_90")
    sig = results.get("significant_vs_previous")
    ci_line = ""
    if ci:
        ci_line = f"**90% CI on dimension mean:** [{ci[0]}, {ci[1]}]"
        if sig is True:
            ci_line += "  — week-over-week delta is **significant** (>1.5× CI half-width)"
        elif sig is False:
            ci_line += "  — week-over-week delta is within noise floor"

    cost = results.get("cost_summary", {}) or {}
    det = results.get("deterministic_checks", {}) or {}

    lines = [
        f"# Benchmark Report — {week}",
        f"",
        f"**Overall Score: {overall}/100{trend}**",
        f"",
        ci_line,
        f"",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## Summary",
        f"",
        f"| Category | Prompt | Score | Weight | Auto-Checks | Cost | Status |",
        f"|---|---|---|---|---|---|---|",
    ]

    for cat in CATEGORIES:
        cat_key = cat.replace("-", "_")
        cat_data = results["scores"].get(cat_key, {})
        score = cat_data.get("score", 0)
        weight = CATEGORIES[cat]["weight"]
        prompt_id = cat_data.get("prompt_id", "?")
        ac = cat_data.get("auto_checks", {}) or {}
        ac_cell = f"{ac['passed']}/{ac['total']} ({ac['pass_rate']}%)" if ac.get("present") else "—"
        c = cat_data.get("cost", {}) or {}
        cost_cell = f"${c.get('total_usd', 0.0):.4f}" if c else "—"
        if score >= 70:
            status = "✅ PASS"
        elif score >= 50:
            status = "⚠️ WARN"
        else:
            status = "❌ FAIL"
        lines.append(f"| {cat} | {prompt_id} | {score} | {weight*100:.0f}% | {ac_cell} | {cost_cell} | {status} |")

    if cost.get("total_usd"):
        lines.extend([
            "",
            f"## Cost This Week",
            f"",
            f"- **Total:** ${cost.get('total_usd', 0.0):.4f}",
            f"- **Tool calls:** {cost.get('total_tool_calls', 0)}",
            f"- **Most expensive category:** {cost.get('most_expensive_category', '—')}",
        ])
    if det and det.get("checks_total"):
        lines.extend([
            "",
            f"## Deterministic Checks",
            f"",
            f"- Categories with declared `## Auto-Checks`: **{det['categories_with_checks']}/{len(CATEGORIES)}**",
            f"- Overall pass rate: **{det['checks_passed']}/{det['checks_total']}** ({det['pass_rate']}%)",
        ])

    lines.extend(["", "## Category Details", ""])

    for cat in CATEGORIES:
        cat_key = cat.replace("-", "_")
        cat_data = results["scores"].get(cat_key, {})
        score = cat_data.get("score", 0)
        notes = cat_data.get("notes", "")
        dims = cat_data.get("dimensions", {})
        executor = cat_data.get("executor_model", "?")
        grader = cat_data.get("grader_model", "?")
        rel = cat_data.get("reliability")

        lines.append(f"### {cat} — {score}/100")
        lines.append(f"Executor: {executor} | Grader: {grader}")
        if dims:
            lines.append(f"Dimensions: {', '.join(f'{k}={v}' for k, v in dims.items())}")
        if rel:
            lines.append(
                f"**Reliability ({rel['n']} runs):** mean={rel['score_mean']} "
                f"min={rel['score_min']} max={rel['score_max']} σ={rel['score_stddev']} "
                f"pass@{rel['n']}={rel['pass_at_n']}/{rel['n']} ({rel['pass_rate']}%) "
                f"@ threshold {rel['pass_threshold']}"
            )
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
    reliability_n = 1

    i = 0
    while i < len(args):
        if args[i] == "--dry-run":
            dry_run = True
        elif args[i] == "--verbose":
            VERBOSE = True
        elif args[i] == "--category" and i + 1 < len(args):
            single_category = args[i + 1]
            i += 1
        elif args[i] == "--reliability" and i + 1 < len(args):
            try:
                reliability_n = max(1, int(args[i + 1]))
            except ValueError:
                print(f"Invalid --reliability value: {args[i+1]}", file=sys.stderr)
                sys.exit(1)
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
