# Prompt P3: Machine-Device-Vehicle Relationship

## Prompt

```
What is the relationship between Machines, Devices, and Vehicles in the EROAD system?
1. How are these three entities related to each other?
2. Can a device be associated with multiple vehicles?
3. What happens when a device is moved from one vehicle to another?
4. Where do these entities live in the sovereign platform's hexagonal architecture?

Answer based on what is in the eroad-brain vault. For anything not covered, say so explicitly.
```

## Expected Behavior

- brain-data-retrieval fetches Vehicle-Machine.md and related domain model files
- Agent correctly describes the Machine-Device-Vehicle triangle
- Acknowledges gaps in lifecycle/reassignment details if not in brain
- No fabricated API endpoints or database schemas

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Brain data used | 25% | Generic answer, no vault data | Some vault references | Cites specific brain files like Vehicle-Machine.md |
| Accuracy | 25% | Relationships described incorrectly | Partially correct | Matches brain vault exactly |
| Gap handling | 25% | Invents reassignment lifecycle | Partially acknowledges unknowns | Clear "not in vault" for unknowns |
| No hallucination | 25% | Invents fields, APIs, or DB schemas | Minor embellishments | Zero fabrication |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

From eroad-brain:
- Machine is the physical hardware unit installed in a vehicle
- Device is the firmware/communication layer
- Vehicle is the logical entity (plate number, fleet assignment)
- Machine ↔ Vehicle is a 1:1 mapping that can change over time
- Specific reassignment details may not be in brain vault
