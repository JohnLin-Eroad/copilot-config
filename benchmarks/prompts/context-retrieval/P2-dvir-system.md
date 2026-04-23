# Prompt P2: DVIR System

## Prompt

```
How does EROAD's DVIR (Driver Vehicle Inspection Report) system work? Specifically:
1. What services are involved in DVIR processing?
2. What is the data flow from driver submission to report storage?
3. What database tables or entities are used for DVIR data?
4. How does the system handle multi-fleet drivers in DVIR?

Answer based on what is in the eroad-brain vault. For anything not covered, say so explicitly.
```

## Expected Behavior

- brain-data-retrieval fetches DVIR-related files if they exist
- Agent correctly describes DVIR services from vault content
- Explicitly acknowledges any gaps in vault coverage
- Does not invent DVIR details not in the brain

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Brain data used | 25% | No vault references | References vault but vaguely | Explicitly cites brain files |
| Accuracy | 25% | Contradicts vault content | Some correct | All facts traceable |
| Gap handling | 25% | Hallucinates DVIR details | Partially acknowledges gaps | Clear "not in vault" for each gap |
| No hallucination | 25% | Invents database schemas or APIs | Minor embellishments | Zero fabricated facts |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

Expected brain vault coverage (may vary):
- DVIR involves driver submissions via mobile/in-cab devices
- dvir service processes inspection reports
- Multi-fleet drivers handled via driver_has_fleets relationship
- Specific table schemas may NOT be in brain vault — agent should say so
- If brain has no DVIR content, agent should clearly state this (score based on honesty, not knowledge)
