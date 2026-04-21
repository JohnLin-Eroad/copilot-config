# Benchmarking System

This directory tracks the quality and performance of the Copilot setup over time. Every Monday at 09:00 the **benchmark-runner** agent runs a fixed test suite and records scores.

## Directory Structure

```
benchmarks/
├── README.md              ← This file
├── baseline.json          ← Week 0 measurement (before weekly learnings)
├── tasks/
│   ├── code-generation.md       ← Task 1: rotating variants, 6-dimension rubric
│   ├── context-retrieval.md     ← Task 2: brain retrieval + hallucination check
│   ├── security-review.md       ← Task 3: planted OWASP vulns
│   ├── planning.md              ← Task 4: rotating variants, 8-dimension rubric
│   ├── learning-retention.md    ← Task 5: experiment delta (2=WARN if no branch)
│   ├── workflow-adherence.md    ← Task 6 (NEW): STM, brain, skills, pipeline
│   └── instruction-following.md ← Task 7 (NEW): IFEval-style preference checking
├── results/
│   └── YYYY-WXX.json      ← Weekly results (auto-generated)
└── reports/
    └── YYYY-WXX.md        ← Human-readable weekly report (auto-generated)
```

## Scoring

| Category | Weight | Method | Scale |
|---|---|---|---|
| Code Generation | **20%** | Rubric: 6 dimensions, rotates weekly variant | 1–5 |
| Context Retrieval | **20%** | Brain data used + accuracy + hallucination check | Pass/Fail + 1–5 |
| Security Review | **20%** | Planted 3 OWASP vulns — recall + precision | 1–5 |
| Planning Quality | **15%** | Rubric: 8 dimensions, rotates weekly variant | 1–5 |
| Workflow Adherence | **15%** | 5 pipeline dimensions: STM, brain, skills, blast radius, consolidation | Pass/fail per dim |
| Instruction Following | **5%** | 5 preference rules from learnings.md — pass/fail | Pass/fail per rule |
| Learning Retention | **5%** | Experiment delta (2=WARN if no branch produced) | 1–5 |

**Overall score** = weighted average across 7 categories

### Why the weights changed (2026-W18)
- Code Gen and Planning hit 5.0 ceiling — reduced weight so saturated categories don't dominate
- Workflow Adherence added at 15% — most important real-world capability
- Learning Retention reduced to 5% — until weekly-experimenter is reliably producing branches
- Instruction Following added at 5% — new category, weight will increase as baseline establishes

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

| Week | Overall | Code | Context | Security | Planning | Workflow | Instr. | Retention | vs Prev |
|---|---|---|---|---|---|---|---|---|---|
| **2026-W16** 🏁 | **4.35** | 5.0 | 3.6 | 4.6 | 4.9 | — | — | 3.0 (N) | baseline |
| **2026-W17** | **4.615** | 5.0 | 4.5 | 4.7 | 5.0 | — | — | 3.0 (N) | +0.265 |
| **2026-W18** *(new weights)* | TBD | — | — | — | — | — | — | — | — |

> **Note:** W16/W17 used old weights (25/25/20/20/10). From W18 onward, new weights apply (20/20/20/15/15/5/5). Scores are **not comparable** across this boundary — treat W18 as a new baseline.
