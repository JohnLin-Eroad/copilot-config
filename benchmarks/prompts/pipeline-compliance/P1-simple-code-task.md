# Prompt P1: Simple Code Task Pipeline

## Prompt

```
Add a new field `lastSeenAt` (Instant) to the Driver domain entity in the sovereign platform.
Update the repository port and write a unit test.
```

## Expected Pipeline Steps

1. ✅ STM created in `~/.copilot/stm/`
2. ✅ brain-data-retrieval invoked BEFORE developer agent
3. ✅ Developer agent used (NOT general-purpose)
4. ✅ Codex model specified for developer
5. ✅ brain-consolidation invoked at pipeline end
6. ✅ Learnings written (if applicable)

## Grading Rubric

| Step | Weight | 0 (not done) | 50 (partial) | 100 (correct) |
|---|---|---|---|---|
| STM created | 20% | No STM file | STM created late or incomplete | STM created at pipeline start with proper format |
| Brain retrieval first | 20% | Skipped | Run but after developer started | Run before any specialist agent |
| Correct agent routing | 20% | general-purpose used | Developer used but wrong model | Developer agent with Codex model |
| Code quality | 20% | Doesn't compile | Compiles but missing tests | Compiles, tests pass, hexagonal compliant |
| Pipeline closure | 20% | No consolidation | Consolidation but no learnings | brain-consolidation + learnings written |

**Score = weighted average of steps (0-100)**

## How to Verify

The grader checks the STM file for:
- `brain-data-retrieval` entry appearing before `developer` entry
- Agent model field showing Codex variant
- `brain-consolidation` entry at the end
- Actual code output quality (if applicable)
