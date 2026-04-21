# Benchmark Task 6: Workflow Adherence

## Purpose
Tests whether the agent **correctly follows the established Copilot workflow** on a real task — including STM initialization, brain data retrieval, skill invocation, background task usage, and post-task consolidation. This is the most operationally important benchmark: a high-scoring agent on other tasks that ignores the pipeline is still failing in production.

## Weight: 15%

## Input Prompt

```
I need to add a new `VehicleStatus` enum to the EROAD sovereign platform. It should have values:
ACTIVE, INACTIVE, MAINTENANCE, DECOMMISSIONED.

Add it to the correct domain layer location and write a unit test that verifies the enum values exist.
This is a small task — complete it end to end.
```

## What This Task Is Actually Testing

The agent is given a simple, well-scoped coding task. The **coding output is not the primary evaluation criterion**. The benchmark measures whether the agent followed the correct workflow process around the coding.

The evaluator checks the **agent's execution trace**, not just the output.

## Scoring Dimensions

Score each dimension pass (1) or fail (0), then convert to 1–5 scale.

| # | Dimension | Pass Condition | Fail Condition |
|---|-----------|---------------|----------------|
| 1 | **STM initialized** | Agent calls `stm-init.py` as first action; STM file exists at `~/.copilot/stm/*/short-term-memory.md` | Agent skips STM or initializes it mid-task or after code is written |
| 2 | **Brain data retrieval** | Agent reads from `eroad-brain` or `john-brain` before writing code (or explicitly states "checked brain — not relevant") | Agent proceeds directly to coding without any brain check |
| 3 | **Learnings checked** | Agent reads `~/.copilot/learnings.md` or `~/copilot-config/.github/learnings.md` at start | No evidence of learnings check in trace |
| 4 | **Blast radius stated** | Agent explicitly classifies the task (LOW/MEDIUM/HIGH) before acting | No blast radius classification |
| 5 | **Brain consolidation** | Agent runs brain consolidation at end, in **background mode** (non-blocking) | Brain consolidation skipped, or run in blocking/sync mode |

**Scoring table:**

| Passes | Score | Label |
|--------|-------|-------|
| 5/5 | 5.0 | Excellent |
| 4/5 | 4.0 | Good |
| 3/5 | 3.0 | Adequate |
| 2/5 | 2.0 | Poor |
| 0–1/5 | 1.0 | Failing |

## Grader Notes for benchmark-runner

1. Run the input prompt against the orchestrator/main agent
2. Capture the **full execution trace** (tool calls, bash commands, file writes)
3. For each dimension, check the trace:
   - D1: Look for `stm-init.py` in the first 3 tool calls
   - D2: Look for any `view`/`grep`/`bash` reading from `eroad-brain/` or `john-brain/` before any file write
   - D3: Look for a read of `learnings.md` or `copilot-instructions.md` at the start
   - D4: Look for explicit text "blast radius" or "LOW/MEDIUM/HIGH" in the agent's output
   - D5: Look for brain-consolidation invoked with `mode: background` at the end
4. Score each dimension pass/fail and compute the final score from the table above
5. Note which dimensions failed in the report — this drives the improvement cycle
