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
│   ├── hallucination-resistance.md  ← NEW adversarial
│   ├── error-recovery.md            ← NEW adversarial
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

| Week | Overall | Code (20%) | Context (20%) | Security (15%) | Planning (15%) | Pipeline (15%) | Halluc. (10%) | Error (5%) | vs Prev |
|---|---|---|---|---|---|---|---|---|---|
| **2026-W16** 🏁 | **87.0** | 100 | 72 | 92 | 98 | — | — | — | baseline |
| **2026-W17** | **90.9** | 100 | 90 | 94 | 100 | — | — | — | +3.9 |
| **2026-W18** | *config-audit* | — | — | — | — | — | — | — | *invalid* |

*W16/W17 scores back-converted from 1-5 scale (×20). W18 was config-audit only (not real execution) — excluded from trend analysis. W19+ will use the new system with all 7 categories, rotating prompts, separate grading, and mandatory traces. Expect scores to drop initially — this is correct behavior, not regression.*

*Categories marked "—" did not exist in that week's benchmark definition.*
