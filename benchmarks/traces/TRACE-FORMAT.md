# Benchmark Trace Format Specification

## Overview

Every benchmark run MUST produce a trace file for each category tested. **No trace = score of 0.**

## Directory Structure

```
benchmarks/traces/
├── TRACE-FORMAT.md          ← This file
└── YYYY-WXX/
    ├── code-generation.md
    ├── context-retrieval.md
    ├── security-review.md
    ├── planning.md
    ├── hallucination-resistance.md
    ├── error-recovery.md
    ├── pipeline-compliance.md
    └── config-health.json
```

## Trace File Format (All Sections Mandatory)

```markdown
# Trace: <category> — <YYYY-WXX>

## Metadata
- Prompt ID: <PX-slug>
- Executor model: <model-id>
- Grader model: <model-id>
- Timestamp: <ISO 8601 UTC>
- Duration: <seconds>
- Run index: <N | omitted>            # only present in reliability mode (multi-run)
- Estimated cost (USD): <0.0000>      # total executor + grader, P3
- Executor tokens (est.): <prompt/completion/total>
- Grader tokens (est.):   <prompt/completion/total>
- Tool calls (heuristic): <N>

## Prompt Sent
<exact text sent to the agent — verbatim, no edits>

## Raw Output
<full unedited output from the agent — NO truncation>

## Deterministic Checks (optional)
<Present only if the prompt declares an `## Auto-Checks` section. Each check has a
result PASS/FAIL with the matched (or missing) substring/pattern. The aggregate
pass-rate is also surfaced in the weekly results JSON under `deterministic_checks`.>

| Check name | Type | Result | Detail |
|---|---|---|---|
| <name> | must_contain_any \| must_not_contain \| regex | PASS \| FAIL | <evidence> |

## Grading Reasoning
<grader dimension-by-dimension analysis with explicit reasoning>

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| <dim1> | <weight%> | <score> | <one-line reasoning> |

## Overall Score: <N>/100

Weighted average: <calculation showing work>
```

## Reliability Mode

When `benchmark-orchestrator.py ... --reliability N` is used (N > 1), each
category is run N times and the trace files are named `run1.md`, `run2.md`, ... per
prompt. The weekly results JSON gains a `reliability` block per category:

```json
"reliability": {
  "n": 3,
  "score_mean": 88.3,
  "score_min": 84,
  "score_max": 92,
  "score_stddev": 3.27,
  "pass_at_n": 3,
  "pass_rate": 100.0,
  "pass_threshold": 75,
  "per_run_scores": [92, 89, 84]
}
```

Reliability mode is the canonical defence against grader/executor stochasticity —
use it for tipping-point weeks where a 1–2 point delta is being interpreted as
real progress. The `confidence_interval_90` field in the top-level results uses a
1000-resample bootstrap (percentile method, seed=42) over all per-dimension
scores; `significant_vs_previous` is true when the week-over-week delta exceeds
1.5× the CI half-width.

## Validation Rules

Before recording ANY score, verify:

1. **File exists**: `traces/YYYY-WXX/<category>.md` must exist
2. **All sections present**: Metadata, Prompt Sent, Raw Output, Grading Reasoning, Scores, Overall Score
3. **Prompt ID matches**: Matches rotation formula selection
4. **Models differ**: Executor model ≠ Grader model
5. **Raw output non-empty**: >50 characters (not placeholder)
6. **Scores in range**: All dimensions 0-100
7. **Overall correct**: Σ(score × weight) ± 0.5 tolerance

If ANY validation fails: **score = 0** with note `TRACE_INVALID: <reason>`.

## Retention

- Keep all traces ≥ 12 weeks
- After 12 weeks: compress (gzip) but don't delete
