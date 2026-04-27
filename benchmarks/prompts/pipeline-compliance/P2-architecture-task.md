# Prompt P2: Architecture Task Pipeline

## Prompt

```
Run the full orchestrator pipeline for this architecture task. You MUST follow ALL pipeline steps below:

PIPELINE PROTOCOL (mandatory — you will be graded on each step):
1. Create an STM (Short-Term Memory) file using: eval "$(python3 ~/.copilot/scripts/stm-init.py 'Multi-tenancy architecture planning')"
2. Run brain-data-retrieval BEFORE any specialist work — fetch relevant domain context from ~/eroad-brain
3. Route to the correct specialist agent: use the architect agent for architecture decisions
4. Complete the task: We need to add multi-tenancy support to the sovereign platform. Fleet organisations must be isolated at the database level. What is the recommended approach and what is the blast radius?
5. Invoke critical-thinker on the architect's proposal before presenting it
6. Run brain-consolidation to persist any new knowledge back to the brain vault
7. Write learnings to learnings.md via: bash ~/.copilot/scripts/add-learning.sh

Show clear evidence of EACH pipeline step in your output.
```

## Expected Pipeline Steps

1. ✅ STM created
2. ✅ brain-data-retrieval before architect
3. ✅ Architect agent used (NOT general-purpose)
4. ✅ Opus model specified for architect
5. ✅ critical-thinker invoked after architect proposal
6. ✅ brain-consolidation at pipeline end

## Grading Rubric

| Step | Weight | 0 (not done) | 50 (partial) | 100 (correct) |
|---|---|---|---|---|
| STM created | 15% | No STM | Created late | Created at pipeline start |
| Brain retrieval first | 15% | Skipped | After architect | Before architect |
| Correct agent (architect) | 20% | general-purpose used | Architect but wrong model | Architect with Opus model |
| Critical-thinker invoked | 20% | Not invoked | Invoked but not on the plan | Invoked on architect's output, before presenting to user |
| Plan quality | 15% | No blast radius | Vague plan | Specific plan with blast radius, edge cases, phased approach |
| Pipeline closure | 15% | No consolidation | Partial | brain-consolidation + learnings |

**Score = weighted average of steps (0-100)**

## How to Verify

The grader checks:
- STM entries show: brain-data-retrieval → architect (Opus) → critical-thinker → brain-consolidation
- Architect output includes blast radius assessment
- critical-thinker output shows genuine critique (not rubber-stamp)
