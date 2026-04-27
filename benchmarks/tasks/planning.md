# Benchmark Task 4: Planning Quality

## Purpose

Tests the orchestrator + architect agents' ability to produce a complete, well-structured plan from a **deliberately ambiguous, multi-service feature request** — including correct blast radius assessment, cross-cutting concerns, edge cases, and dependency ordering.

## Prompt Pool

Prompts are in `prompts/planning/P1-P4.md`. Each prompt file includes its own rubric, expected behavior, and ground truth. The benchmark-runner selects the prompt using the rotation formula — do NOT select manually.

## General Scoring Dimensions

Each prompt file defines its own rubric. All rubrics score these common dimensions (0-100 per dimension, weighted average for final score):

- **Completeness** — All major plan components present (scope, dependencies, acceptance criteria)
- **Ambiguity resolution** — Explicitly surfaces unstated assumptions and gaps
- **Edge cases** — Identifies non-obvious failure modes and boundary conditions
- **Blast radius assessment** — Names specific risks and affected services
- **Dependency ordering** — Tasks ordered correctly with explicit dependencies
- **Domain correctness** — Business rules placed in domain layer, correct entity identification

## What Good Looks Like (Score 90+)

A complete plan that:
- Names domain entities explicitly with correct layer placement
- Identifies business rules and puts them in the domain layer as value/policy objects
- Lists edge cases including timezone, multi-fleet, clock sync
- Has ordered todos with explicit dependencies
- Has testable acceptance criteria per story
- Surfaces all ambiguities with explicit assumption statements

## Grader Notes for benchmark-runner

1. Read the selected prompt file — it contains the specific rubric, expected behavior, and ground truth
2. Score each dimension in the prompt's rubric with explicit reasoning
3. For **Ambiguity resolution**: count explicit assumption statements; ≥3 = 90+, 2 = 70, 1 = 50, 0 = 20
4. For **Edge cases**: count distinct edge cases identified; ≥4 = 90+, 3 = 70, 2 = 50, 1 = 30, 0 = 10
5. Calculate weighted average for the final score (0-100)
6. Write trace to `traces/$WEEK/planning.md` including the prompt ID, all dimension scores, and reasoning

---

## Future Prompt Candidates (Tier 3 — Expert)

These are not yet in the active prompt pool. Add them as P5/P6/P7 when the pool needs fresh challenges.

### Variant E — Contradictory Requirements

```
orchestrator: 5 contradictory requirements for driver activity logs:
- R1: 7-year retention (NZ compliance)
- R2: Auto-delete after 90 days (CFO commitment)
- R3: Immutable once written (legal hold)
- R4: 30-day hot cache then S3 Glacier (3-5h retrieval)
- R5: 3-second retrieval for 2 years of driver self-service
```

**Why this is hard:** The "right" answer is escalation, not implementation. Scoring penalises planning through contradictions.

### Variant F — Discovery from Raw Slack Transcript

```
orchestrator: No product spec. Extract bounded context, identify ambiguities, and produce a plan
(or explain what you need first) from a noisy Slack thread about "the overtime thing" involving
shift tracking, employment types, NZ vs AU rules, and a legacy reporting service.
```

**Why this is hard:** Must catalogue ≥6 ambiguities, identify stakeholders, and refuse to produce a full plan until key questions are answered.

### Variant G — Cross-Team 3-Squad Coordination

```
orchestrator: Three squads (Platform, Compliance, Reporting) must deliver a connected feature
in parallel. Requires API contracts per squad, rollback plans per squad, and acceptance criteria.
Platform publishes ShiftCompletedEvent → Compliance evaluates → Reporting updates read model.
```

**Why this is hard:** Must define all schemas, enable parallel development with contract-first approach, and specify squad-level rollback plans.
