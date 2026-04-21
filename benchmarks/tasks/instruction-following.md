# Benchmark Task 7: Instruction Following

## Purpose
Tests whether the agent **respects explicit user preferences** that have been captured in `~/.copilot/learnings.md`. This is an IFEval-style benchmark: the evaluator checks whether known, recorded preferences are honoured — not hallucinated.

## Weight: 5%

## Background

John's preferences are captured as global learnings. Over time, learnings.md accumulates rules the agent should always follow. This benchmark checks a sample of those rules on each run.

## Test Procedure

1. Read `~/.copilot/learnings.md` and extract all `[PREFERENCE]` entries
2. Select the **5 most recently added** preference entries for this week's test
3. For each preference, design a micro-task that would naturally violate it if ignored
4. Run the micro-task and check the agent's response

## Current Preference Test Cases

These are seeded from known preferences. The benchmark-runner should re-read learnings.md each week and update this list if new `[PREFERENCE]` entries were added.

| # | Preference (from learnings.md) | Violation micro-task | Pass condition |
|---|-------------------------------|----------------------|----------------|
| P1 | Always initialize STM as first action on every task | "Add a comment to line 5 of context-retrieval.md" | Agent runs stm-init.py before touching the file |
| P2 | Always display output summary at end of tasks | "List the files in ~/copilot-config/benchmarks/" | Agent ends response with a structured summary section |
| P3 | Brain consolidation always runs in background mode | "Research what LangChain is and save to brain" | brain-consolidation invoked with `mode: background` |
| P4 | Auto-write to STM without asking the user | Any multi-step task | Agent writes to STM without prompting user for confirmation |
| P5 | Default to action — proceed without asking for LOW blast radius tasks | "Create a new file test.txt in /tmp with the text 'hello'" | Agent creates the file without asking permission |

## Scoring

| Preferences followed | Score |
|---------------------|-------|
| 5/5 | 5.0 |
| 4/5 | 4.0 |
| 3/5 | 3.0 |
| 2/5 | 2.0 |
| 0–1/5 | 1.0 |

## Maintenance: Keeping Tests Current

The benchmark-runner should:
1. Read `~/.copilot/learnings.md` at the start of each run
2. Count total `[PREFERENCE]` entries
3. If new preferences exist that aren't in the test table above, add them (and remove the oldest to keep total at 5)
4. Note in the report how many total preferences exist and how many were tested

## Grader Notes for benchmark-runner

- For each micro-task, look for the **pass condition** in the agent's execution trace
- A "pass" is binary — either the preference was honoured or it wasn't
- Do not award partial credit
- Note the specific preference that failed (this informs the weekly experiment target)
- If a preference is ambiguous or no micro-task applies, skip it and test the next one — don't score unfairly
