# Benchmarking System

Tracks the quality and capability of the Copilot agent system over time. Every Monday at 09:00 the **benchmark-runner** agent selects prompts from a rotating pool, executes real agent tasks, has a **different model** grade the output, and records scores backed by mandatory trace files.

## Core Principles

1. **Real execution** — every score comes from actually running agents, not checking config files
2. **No self-grading** — executor and grader are always different models (see `EXECUTOR-GRADER-SPLIT.md`)
3. **Rotating prompts** — 4-5 prompts per category, SHA-256 rotated weekly (see `prompts/INDEX.md`)
4. **Mandatory traces** — no trace file = score of 0 (see `traces/TRACE-FORMAT.md`)
5. **Adversarial tests** — hallucination resistance and error recovery alongside happy-path tests

## Directory Structure

```
benchmarks/
├── README.md                      ← This file
├── EXECUTOR-GRADER-SPLIT.md       ← Execution flow documentation
├── baseline.json                  ← Normalized to 0-100 scale
├── prompts/                       ← Rotating prompt pools
│   ├── INDEX.md                   ← Rotation formula + pool sizes
│   ├── code-generation/           ← 4 prompts (P1–P4)
│   ├── context-retrieval/         ← 4 prompts
│   ├── security-review/           ← 4 prompts (each with 3 planted vulns)
│   ├── planning/                  ← 4 prompts
│   ├── hallucination-resistance/  ← 4 prompts (all trick questions)
│   ├── error-recovery/            ← 3 prompts (abnormal conditions)
│   └── pipeline-compliance/       ← 3 prompts
├── tasks/                         ← Category definitions + rubrics
│   ├── code-generation.md
│   ├── context-retrieval.md
│   ├── security-review.md
│   ├── planning.md
│   ├── hallucination-resistance.md  ← Adversarial
│   ├── error-recovery.md            ← Adversarial
│   ├── pipeline-compliance.md       ← Replaces workflow-adherence
│   └── config-health.md             ← Pass/fail checklist (NOT weighted)
├── traces/                        ← Mandatory execution traces
│   ├── TRACE-FORMAT.md            ← Trace spec + validation rules
│   └── YYYY-WXX/                  ← Per-week trace files
├── results/
│   └── YYYY-WXX.json             ← Weekly results (0-100 scale)
└── reports/
    └── YYYY-WXX.md               ← Human-readable weekly report
```

## Scoring (0-100 Scale)

<<<<<<< HEAD
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
=======
| Category | Weight | What It Tests |
|---|---|---|
| Code Generation | 20% | Can the developer agent produce correct, hexagonal, tested code? |
| Context Retrieval | 20% | Does brain-data-retrieval fetch the right files and use them? |
| Security Review | 15% | Does the security agent find planted vulnerabilities? |
| Planning Quality | 15% | Can the orchestrator produce complete, structured plans? |
| Pipeline Compliance | 15% | Does the full pipeline execute correctly (STM → brain → specialist → close)? |
| Hallucination Resistance | 10% | Does the agent refuse to fabricate answers about nonexistent things? |
| Error Recovery | 5% | Does the agent handle broken input/state gracefully? |

**Overall score** = Σ(category_score × weight). These weights are **locked** — they do not change between weeks.

**Config health** runs as a separate pass/fail checklist (see `tasks/config-health.md`) and is NOT included in the overall score.

## Grading Model Matrix

| Executor Model Family | Grader Model |
|---|---|
| Codex (gpt-5.x) | Claude Opus 4.6 |
| Claude Sonnet/Opus | GPT-5.3-Codex |
| Claude Haiku | Claude Opus 4.6 |
>>>>>>> weekly/2026-W17

## Interpreting Results

- **Score ≥ 80**: System performing well
- **Score 60–79**: Acceptable — look for targeted improvements
- **Score < 60**: Regression or capability gap — investigate traces
- **vs_previous > +5**: Meaningful improvement
- **vs_previous < -5**: Regression — check traces and experiment branches

## Running Manually

```bash
copilot agent run benchmark-runner --message "Run full benchmark suite for week $(date +%Y-W%V)"
```

## Score History

<<<<<<< HEAD
| Week | Overall | Code | Context | Security | Planning | Workflow | Instr. | Retention | vs Prev |
|---|---|---|---|---|---|---|---|---|---|
| **2026-W16** 🏁 | **4.35** | 5.0 | 3.6 | 4.6 | 4.9 | — | — | 3.0 (N) | baseline |
| **2026-W17** | **4.615** | 5.0 | 4.5 | 4.7 | 5.0 | — | — | 3.0 (N) | +0.265 |
| **2026-W18** *(new weights)* | TBD | — | — | — | — | — | — | — | — |

> **Note:** W16/W17 used old weights (25/25/20/20/10). From W18 onward, new weights apply (20/20/20/15/15/5/5). Scores are **not comparable** across this boundary — treat W18 as a new baseline.
=======
| Week | Overall | Code (20%) | Context (20%) | Security (15%) | Planning (15%) | Pipeline (15%) | Halluc. (10%) | Error (5%) | vs Prev |
|---|---|---|---|---|---|---|---|---|---|
| **2026-W16** 🏁 | **87.0** | 100 | 72 | 92 | 98 | — | — | — | baseline |
| **2026-W17** ⭐ | **87.1** | 92.5 | 85.0 | 69.0 | 92.4 | 84.5 | 100.0 | 94.0 | v2 baseline |
| **2026-W18** | *config-audit* | — | — | — | — | — | — | — | *invalid* |

*W16/W17 scores back-converted from 1-5 scale (×20). W18 was config-audit only (not real execution) — excluded from trend analysis. W19+ will use the new system with all 7 categories, rotating prompts, separate grading, and mandatory traces. Expect scores to drop initially — this is correct behavior, not regression.*

*Categories marked "—" did not exist in that week's benchmark definition.*
>>>>>>> weekly/2026-W17
