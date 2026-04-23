# Benchmark Task: Pipeline Compliance

## Purpose

Tests whether the orchestrator correctly follows the mandatory pipeline for every task: STM creation → brain-data-retrieval → correct specialist routing (with correct model) → brain-consolidation at close. Replaces the old "workflow-adherence" category.

## Category Weight: 15%

## Prompt Pool

3 prompts in `benchmarks/prompts/pipeline-compliance/`:
- **P1** — Simple code task (add field to entity) → verify developer routing with Codex
- **P2** — Architecture task (multi-tenancy) → verify architect routing with Opus + critical-thinker
- **P3** — Multi-step task (security review → fix → test) → verify correct agent sequencing

## Execution Method

1. Select prompt via rotation formula
2. Run the orchestrator with the selected prompt
3. After completion, read the STM file to verify pipeline steps
4. Check agent routing and model selection

## The Mandatory Pipeline Steps

| Step | Requirement |
|------|-------------|
| 1 | STM created at task start |
| 2 | brain-data-retrieval runs BEFORE any specialist |
| 3 | Correct specialist agent used (not general-purpose) |
| 4 | Correct model for each agent (Codex for code, Opus for architecture, etc.) |
| 5 | brain-consolidation closes the pipeline |
| 6 | Learnings written to brain vault |

## Grading Dimensions

Vary by prompt (see individual prompt files for specific rubrics).

General pattern:

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (correct) |
|---|---|---|---|---|
| STM created | 15% | No STM | Created late/incomplete | Created at pipeline start |
| Brain retrieval order | 15% | Skipped | After specialist | Before all specialists |
| Agent routing | 25% | general-purpose fallback | Right agent, wrong model | Right agent + right model |
| Output quality | 25% | Missing deliverables | Partial output | All deliverables complete |
| Pipeline closure | 20% | No consolidation | Partial | brain-consolidation + learnings |

## Model Routing Reference

| Agent | Expected Model Family |
|-------|----------------------|
| developer | Codex (gpt-5.x-codex) |
| architect | Opus (claude-opus-4.x) |
| security | Sonnet (claude-sonnet-4.x) |
| critical-thinker | Opus (claude-opus-4.x) |
| brain-data-retrieval | Haiku (claude-haiku-4.x) |
| brain-consolidation | Sonnet (claude-sonnet-4.x) |
| explore/discovery | Haiku (claude-haiku-4.x) |

A routing is correct if the model family matches.

## Scoring

Score = weighted average per the prompt-specific rubric (0-100).

## Why This Matters

Pipeline compliance is the difference between a professional system and an ad-hoc script. If brain-retrieval runs after the developer agent, context is wasted. If brain-consolidation never runs, knowledge is lost. Every missed step compounds.
