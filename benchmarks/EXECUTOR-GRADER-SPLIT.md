# Executor-Grader Split: Execution Flow

## Principle

**The model that generates output NEVER grades its own output.**

This eliminates self-grading bias — the #1 reliability problem in the previous benchmark system.

## Architecture

```
Phase 1: SELECT          Phase 2: EXECUTE          Phase 3: GRADE           Phase 4: REPORT
┌─────────────┐         ┌─────────────────┐       ┌──────────────────┐     ┌────────────┐
│ Prompt Pool  │────────▶│ Executor Agent  │──────▶│  Grader Agent    │────▶│  Results    │
│ (rotated)    │         │ (system models) │       │  (DIFFERENT      │     │  JSON + MD  │
└─────────────┘         └────────┬────────┘       │   model)         │     └────────────┘
                                 │                 └──────────────────┘
                                 ▼
                         ┌───────────────┐
                         │ Trace File    │
                         │ (mandatory)   │
                         └───────────────┘
```

## Grading Model Matrix

| Executor model family | Grader model | Rationale |
|---|---|---|
| Codex (gpt-5.x) | Claude Opus 4.6 | Cross-vendor eliminates shared biases |
| Claude Sonnet 4.x | GPT-5.3-Codex | Cross-vendor |
| Claude Opus 4.x | GPT-5.3-Codex | Cross-vendor |
| Claude Haiku 4.x | Claude Opus 4.6 | Different tier; Opus catches Haiku shortcuts |

**Rule**: If executor and grader would be same model, use the OTHER premium model.

## Execution Flow (Per Category)

### Step 1: Select Prompt

```python
import hashlib
week = "2026-W20"
category = "code-generation"
pool_size = 4

week_num = int(week.split('-W')[1])
offset = int(hashlib.sha256(category.encode()).hexdigest()[:8], 16)
prompt_index = (week_num + offset) % pool_size
# → Read benchmarks/prompts/{category}/P{index+1}-*.md
```

### Step 2: Execute

1. Read the selected prompt file
2. Extract the `## Prompt` section
3. Determine executor agent based on category:

| Category | Executor Agent | What it spawns |
|---|---|---|
| code-generation | `developer` | Code implementation task |
| context-retrieval | `brain-data-retrieval` + follow-up agent | Brain fetch + answer |
| security-review | `security` | Security audit of provided code |
| planning | `orchestrator` | Full planning pipeline |
| hallucination-resistance | `brain-data-retrieval` + any agent | Agent with brain context |
| error-recovery | (varies by prompt) | Agent under abnormal conditions |
| pipeline-compliance | `orchestrator` | Full pipeline execution |

4. Run the executor agent using the system's **real model configuration** (not a special benchmark model)
5. Capture the COMPLETE raw output — no truncation

### Step 3: Write Trace (Executor Part)

Create `traces/YYYY-WXX/<category>.md` with:
- Metadata section (prompt ID, executor model, timestamp)
- Prompt Sent section (verbatim)
- Raw Output section (complete)

### Step 4: Grade

1. Read the completed trace file
2. Read the grading rubric from the prompt file (`## Grading Rubric`)
3. Read ground truth if applicable (`## Ground Truth`, `## GRADER ONLY`)
4. Determine grader model from the matrix above
5. Spawn a grader agent with this prompt template:

```
You are a BENCHMARK GRADER. Your job: evaluate the quality of agent output against a rubric.

RUBRIC:
<grading rubric from prompt file>

GROUND TRUTH (if applicable):
<ground truth section>

AGENT OUTPUT TO GRADE:
<raw output from trace file>

For EACH dimension in the rubric:
1. Quote the relevant part of the agent output
2. Explain what was done well and what was missed
3. Assign a score 0-100

Output format:
| Dimension | Score (0-100) | Reasoning |
|---|---|---|

Overall: <weighted average> / 100

Show your calculation.
```

6. Append grading output to trace file (Grading Reasoning + Scores + Overall sections)

### Step 5: Validate Trace

Before recording the score, validate per TRACE-FORMAT.md:
- All sections present
- Executor ≠ Grader model
- Scores in range
- Overall computed correctly

If validation fails → score = 0, reason = `TRACE_INVALID: <detail>`

## Error Handling

| Failure | Action |
|---|---|
| Executor agent crashes | Score = 0, trace captures error output, note = `EXECUTOR_CRASH` |
| Executor produces empty output | Score = 0, note = `EMPTY_OUTPUT` |
| Grader agent crashes | Re-run grader ONCE. If second failure, score = 0, note = `GRADER_CRASH` |
| Grader returns invalid scores | Re-run grader ONCE with stricter format instructions |
| Trace write fails | Skip category, note = `TRACE_WRITE_FAILED` |

## Timing

Expected per-category execution time:
- Prompt selection: <1s
- Execution: 30-180s (varies by complexity)
- Trace writing: <1s
- Grading: 15-60s
- Validation: <1s

Total benchmark run: 5-20 minutes for all 7 categories.
