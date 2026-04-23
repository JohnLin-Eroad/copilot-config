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

## Prompt Sent
<exact text sent to the agent — verbatim, no edits>

## Raw Output
<full unedited output from the agent — NO truncation>

## Grading Reasoning
<grader dimension-by-dimension analysis with explicit reasoning>

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| <dim1> | <weight%> | <score> | <one-line reasoning> |

## Overall Score: <N>/100

Weighted average: <calculation showing work>
```

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
