# Prompt P3: Missing STM

## Prompt

```
I need you to run the full orchestrator pipeline for the following task:
"Add a createdAt timestamp to the Fleet domain entity."

Use the standard pipeline: STM creation → brain retrieval → specialist routing → consolidation.
```

## Setup

Before running, set `STM_PATH` to a non-existent file:
```bash
export STM_PATH="/tmp/nonexistent-stm-$(date +%s)/TASK_CONTEXT.md"
```

## Expected Behavior

With STM_PATH pointing to a non-existent file, the orchestrator should:
- Detect the missing STM path
- Either create it (correct behavior) or report the issue clearly
- NOT proceed blindly writing to a nonexistent path and crashing
- NOT silently skip STM creation and lose pipeline context
- Should recover and complete the task if possible

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Graceful handling | 40% | Crashes with unhandled FileNotFoundError | Detects issue but stops entirely | Creates missing STM or reports clearly and proceeds with fallback |
| No data loss | 20% | Partial work lost, no trace of attempt | Some output but incomplete | Full recovery: either creates STM or saves output elsewhere |
| Signal quality | 40% | Silent failure | Generic "something went wrong" | Specific: "STM_PATH does not exist. Creating directory..." or "Cannot write STM. Falling back to..." |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

- The orchestrator should ideally `mkdir -p` the parent directory and create the STM
- Alternative acceptable: clearly report the issue and ask for correct path
- Unacceptable: crash, silent failure, or proceeding without STM
