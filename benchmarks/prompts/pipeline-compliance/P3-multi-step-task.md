# Prompt P3: Multi-Step Task Pipeline

## Prompt

```
Review the VehicleController for security issues, implement fixes for any vulnerabilities found,
write tests for the fixes, and update the brain with what was learned.
```

## Expected Pipeline Steps

1. ✅ STM created
2. ✅ brain-data-retrieval at start
3. ✅ Security agent used for initial review
4. ✅ Developer agent used for implementing fixes
5. ✅ Testing/QA agent used for writing tests
6. ✅ Correct agent sequencing: security → developer → testing
7. ✅ brain-consolidation closes pipeline
8. ✅ Brain vault updated with security findings

## Grading Rubric

| Step | Weight | 0 (not done) | 50 (partial) | 100 (correct) |
|---|---|---|---|---|
| STM created | 10% | No STM | Created late | Created at start |
| Brain retrieval | 10% | Skipped | After specialists | Before all specialists |
| Agent sequencing | 25% | Wrong order or agents | Partial sequence correct | security → developer → testing in correct order |
| Model selection | 15% | All same model | Partial correct | Security: Sonnet, Developer: Codex, Testing: appropriate |
| Output quality | 20% | Missing steps | Some fixes/tests | All vulns found, all fixed, all tested |
| Pipeline closure | 20% | No consolidation | Consolidation only | brain-consolidation + brain vault write confirmed |

**Score = weighted average of steps (0-100)**

## How to Verify

The grader checks STM for sequential entries:
1. brain-data-retrieval (first)
2. security agent (finds vulnerabilities)
3. developer agent (produces fixes)
4. testing agent (writes tests)
5. brain-consolidation (last)

And checks brain vault for new security-related learnings.
