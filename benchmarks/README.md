# Benchmarking System

This directory tracks the quality and performance of the Copilot setup over time. Every Monday at 09:00 the **benchmark-runner** agent runs a fixed test suite and records scores.

## Directory Structure

```
benchmarks/
├── README.md              ← This file
├── baseline.json          ← Week 0 measurement (before weekly learnings)
├── tasks/
│   ├── code-generation.md      ← Benchmark task 1 definition
│   ├── context-retrieval.md    ← Benchmark task 2 definition
│   ├── security-review.md      ← Benchmark task 3 definition
│   ├── planning.md             ← Benchmark task 4 definition
│   └── learning-retention.md   ← Benchmark task 5 definition
├── results/
│   └── YYYY-WXX.json      ← Weekly results (auto-generated)
└── reports/
    └── YYYY-WXX.md        ← Human-readable weekly report (auto-generated)
```

## Scoring

| Category | Method | Scale |
|---|---|---|
| Code Generation | Rubric: hexagonal compliance × correctness × Javadoc | 1–5 |
| Context Retrieval | Was brain data used? Was it accurate? | Pass/Fail + 1–5 accuracy |
| Security Review | Planted 3 OWASP vulns — recall + precision | % |
| Planning Quality | Rubric: completeness × blast radius × edge cases | 1–5 |
| Learning Retention | Re-run a previously-failing category after an experiment | Pass/Fail + delta |

**Overall score** = weighted average (code gen 25%, context retrieval 25%, security 20%, planning 20%, learning 10%)

## Interpreting Results

- **Score ≥ 4.0**: System performing well — continue current trajectory
- **Score 3.0–3.9**: Acceptable — look for targeted improvements
- **Score < 3.0**: Regression detected — investigate what changed (check the matching experiment branch)
- **vs_previous > +0.3**: Meaningful improvement from weekly experiments
- **vs_previous < -0.3**: Regression — check if an experiment branch made things worse

## Running Manually

```bash
copilot agent run benchmark-runner --message "Run full benchmark suite for week $(date +%Y-W%V)"
```

## Score History

| Week | Overall | Code | Context | Security | Planning | Retention | vs Prev |
|---|---|---|---|---|---|---|---|
| (populated by benchmark-runner) | | | | | | | |
