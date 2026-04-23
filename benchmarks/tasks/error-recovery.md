# Benchmark Task: Error Recovery

## Purpose

Tests whether agents handle malformed input, missing resources, and broken state gracefully — without crashing, hanging, losing data, or producing garbled output. Robustness under failure is a key quality signal.

## Category Weight: 5%

## Prompt Pool

3 prompts in `benchmarks/prompts/error-recovery/`:
- **P1** — Malformed Java code with multiple syntax errors sent for security review
- **P2** — Brain-data-retrieval against an empty vault directory
- **P3** — Orchestrator pipeline with STM_PATH pointing to nonexistent file

Each prompt creates an abnormal condition and measures how cleanly the agent handles it.

## Execution Method

1. Select prompt via rotation formula
2. Apply the setup steps described in the prompt file (e.g., rename brain vault for P2)
3. Run the agent with the abnormal condition
4. Capture full response
5. **IMPORTANT**: Restore original state after test (e.g., restore brain vault)

## Grading Dimensions

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (perfect) |
|---|---|---|---|---|
| **Graceful handling** | 40% | Crashes, hangs, or loops indefinitely | Produces some output but confused | Clean error detection, clear message, recovery/fallback |
| **No data loss** | 20% | Corrupts existing files or session state | Partial output with side effects | Zero side effects, clean recovery |
| **Signal quality** | 40% | Silent failure or generic "error occurred" | Vague acknowledgment of problem | Specific: names what failed, why, and what to do about it |

## Grading Model

Use a **different model** than the executor. The grader receives:
1. The agent's full response (including any error output)
2. The expected behavior from the prompt file
3. Any evidence of side effects (file changes, process state)

## Scoring

**Score = (graceful_handling × 0.4) + (no_data_loss × 0.2) + (signal_quality × 0.4)**

Scale: 0-100. A perfect score means clean error detection + specific message + no side effects.

## Safety Notes

- P2 (empty brain) requires temporarily moving the brain vault. **Always restore it after the test.**
- P3 (missing STM) may create directories — clean up after test
- If any test causes actual data loss, the test itself has a bug — report it

## Why This Matters

Production systems fail. Network timeouts, missing files, malformed input — these happen daily. An agent that crashes on bad input is dangerous. An agent that clearly reports "this is broken, here's what I need" is production-ready.
