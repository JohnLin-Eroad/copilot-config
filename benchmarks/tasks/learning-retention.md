# Benchmark Task 5: Learning Retention

## Purpose
Tests whether this week's experiment branch actually improved the capability it targeted. This benchmark is **dynamic** — it re-runs the most relevant other benchmark category after the experiment branch changes are applied.

## Weight: 5%

## How It Works

1. The `benchmark-runner` agent reads this week's `experiments/YYYY-WXX.md` to find which capability area the experiments targeted
2. It identifies the corresponding benchmark task (code-generation, context-retrieval, security-review, planning, or workflow-adherence)
3. It runs that task **twice**: once without the experiment changes (on `main`) and once with them (on `weekly/YYYY-WXX`)
4. It computes the delta

## Mapping: Experiment Categories → Benchmark Tasks

| Experiment category (from weekly-experimenter) | Benchmark task to re-run |
|---|---|
| `prompt-engineering` | planning (planning quality tests prompt following) |
| `tool-usage` | context-retrieval (better tools = better retrieval) |
| `architecture` | code-generation (architecture changes affect code output) |
| `model` | all tasks (model changes affect everything — run all tasks) |
| `security` | security-review |
| `workflow` | workflow-adherence |
| `multiple` | Run all tasks |

## Scoring

| Result | Score | Meaning |
|---|---|---|
| Improved ≥ +0.5 | PASS (5) | Experiment had clear positive impact |
| Improved +0.1 to +0.49 | PASS (4) | Small improvement — worth keeping |
| No change (±0.09) | NEUTRAL (3) | Experiment had no measurable effect |
| Regressed -0.1 to -0.49 | WARN (2) | Experiment may have hurt — review |
| Regressed ≥ -0.5 | FAIL (1) | Experiment caused regression — revert |

## If No Experiment Branch Exists This Week

If `experiments/YYYY-WXX.md` does not exist or has no actionable changes, score this category as **2 (WARN)** — not 3 (NEUTRAL).

**Rationale:** The weekly-experimenter is supposed to run every week. If it didn't produce a branch, that is itself a failure of the system. A score of 2 creates pressure to fix the experiment pipeline rather than treating inaction as neutral.

Note in the report: `"No experiments this week — weekly-experimenter did not produce a branch. Score: 2 (WARN — pipeline failure)."`

## Directing Experiments at Gaps

The `weekly-experimenter` agent should always target the **lowest-scoring benchmark category** from the prior week. The benchmark-runner should surface this in its report:

```markdown
### Recommended experiment target for next week
Lowest scoring category: {category} — {score}/5
Suggested experiment type: {type from mapping table}
```

## Output Format

```markdown
### Learning Retention — {WEEK}

Experiment branch: weekly/{WEEK}
Experiment type: {type}
Benchmark re-run: {task name}

Baseline score (main): {X}
Experiment score (weekly/YYYY-WXX): {Y}
Delta: {+/-Z}

Result: {PASS | WARN | FAIL | NEUTRAL}
Notes: {what specifically changed and whether it explains the delta}
```

## Grader Notes for benchmark-runner

Run the identified benchmark task twice with different agent configurations (once with main copilot-instructions + agents, once with the experiment branch version). Compare the numeric scores. Document the delta and assign the retention score from the table above.

If no experiment branch exists, immediately score 2 (WARN) and add a recommendation to fix the weekly-experimenter pipeline.
