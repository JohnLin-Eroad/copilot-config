# Benchmark Task 4: Planning Quality

## Purpose
Tests the orchestrator + architect agents' ability to produce a complete, well-structured plan from a **deliberately ambiguous, multi-service feature request** — including correct blast radius assessment, cross-cutting concerns, edge cases, and dependency ordering.

## Active Variant

> **Rotate this each week.** Pick the next variant from the list below.

**Current variant: E — Contradictory Requirements (Tier 3)**

## Input Prompt (Variant E — Active)

```
orchestrator: The product team has provided the following requirements for the EROAD sovereign platform.
Plan the implementation.

REQUIREMENT 1 (from Product Manager): All driver activity logs must be retained for 7 years
to meet NZ transport compliance regulations.

REQUIREMENT 2 (from CTO): To reduce storage costs, all logs older than 90 days must be
automatically deleted. This is non-negotiable — we've already committed to the CFO.

REQUIREMENT 3 (from Legal): Driver activity logs must be immutable once written — no deletion,
no modification, ever, as they may be required as legal evidence.

REQUIREMENT 4 (from Engineering): We need to implement a 30-day hot cache and then move data
to cold storage (S3 Glacier). The cold storage retrieval time is 3–5 hours.

REQUIREMENT 5 (from Fleet Manager UX): Drivers must be able to pull up their own activity logs
from the last 2 years within 3 seconds.

Produce a detailed implementation plan.
```

## Scoring Rubric (Variant E)

Score each dimension 1–5:

| Dimension | 5 | 3 | 1 |
|---|---|---|---|
| **Contradiction detection** | Explicitly names all 3 contradictions: (R1 vs R2 retention clash), (R2 vs R3 deletion vs immutability), (R4 cold retrieval vs R5 3s SLA) | Names 1–2 contradictions | No contradictions identified — just plans as if requirements are coherent |
| **Escalation behaviour** | Stops planning and requests product/legal/CTO alignment before proposing implementation; proposes options for each contradiction | Plans with workarounds but notes risks | Ignores contradictions and produces a plan |
| **Regulatory grounding** | References specific NZ transport regulations or notes need to verify them; distinguishes legal hold from operational data | Mentions compliance generally | No regulatory awareness |
| **Architecture for compliance** | Proposes WORM storage (S3 Object Lock or similar) for immutability with tiered retention; correct separation of hot/cold paths | Tiered storage mentioned without immutability | Single-tier no compliance architecture |
| **SLA feasibility analysis** | Correctly flags that 3–5 hour Glacier retrieval is incompatible with 3s SLA and proposes resolution (index + metadata fast path, pre-warm) | Notices the gap but no resolution | Doesn't notice SLA/retrieval incompatibility |
| **Risk articulation** | Names specific risks: legal liability for premature deletion, CFO contract exposure if 7yr requirement enforced, performance risk | Names 1–2 risks | No risks named |
| **Dependency ordering** | Plan is conditional on alignment decisions; orders tasks correctly once decisions are resolved | Partially ordered | Unordered or treats contradictions as if resolved |
| **Decision log** | Explicitly proposes a decision log / RFC for each unresolved contradiction | Mentions need for alignment | No process for resolving contradictions |

**Final score** = average of 8 dimensions

**Why this is hard:** A naive agent will just plan the implementation. A good agent will stop at the contradictions and refuse to produce a plan until they're resolved. Scoring penalises planning through contradictions — the "right" answer is escalation, not implementation.

---

## Tier 3 Variants (F, G)

### Variant F — Discovery from Raw Slack Transcript

**Difficulty tier: 3 (Expert)**

```
orchestrator: No product spec has been written for this feature. All we have is this Slack thread
from last week. Extract the bounded context, identify what needs to be built, surface all
ambiguities and gaps, and produce an implementation plan — or explain what you'd need before
you can produce one.

--- SLACK THREAD START ---
@sarah.pm: hey team, fleet managers keep asking about the "overtime thing"
@dev.ali: yeah the compliance thing, drivers going over hours?
@sarah.pm: no its different, its more like… they want to see who's been doing too many shifts
@dev.ali: shifts? or hours within a single shift?
@sarah.pm: honestly not sure, I think both? Craig from the fleet side said something about weekly totals
@legal.team: just FYI there's a legal threshold but it depends on the employment agreement type
@dev.ali: so its per-employment-type?
@sarah.pm: I guess? Craig would know. Also it might need to show in the existing reporting thing
@dev.ali: the legacy reporting service? that hasn't been touched in 3 years
@sarah.pm: yeah probably that one
@dev.ali: ok so we're adding to legacy or building new?
@sarah.pm: up to you I think? just needs to work
@legal.team: don't forget the union rules also differ by region (NZ vs AU)
@dev.ali: 😬 ok I'll write something up
--- SLACK THREAD END ---

Produce a detailed implementation plan, or clearly articulate what must be answered first.
```

**Scoring Rubric (Variant F)**

| Dimension | 5 | 3 | 1 |
|---|---|---|---|
| **Ambiguity catalogue** | Lists ≥6 open questions (shifts vs hours, weekly vs daily, employment type, NZ vs AU rules, legacy vs new, what "too many" means) | 3–5 ambiguities | ≤2 or just says "requirements unclear" without cataloguing |
| **Bounded context extraction** | Identifies: driver, shift, employment agreement, compliance threshold, region as domain concepts from the noise | Identifies 3–4 concepts | ≤2 or incorrect concepts |
| **Build vs extend decision** | Raises new service vs legacy extension as a binary with pros/cons; recommends one with rationale | Mentions the choice | Ignores legacy question |
| **Stops before full plan** | Correctly refuses to produce a full implementation plan until key questions are answered; offers conditional plan or plan skeleton | Partial plan with caveats | Full plan as if requirements are clear |
| **Stakeholder mapping** | Identifies who must answer each question (Craig, legal, HR for employment types, Sarah for scope) | Some stakeholder attribution | No stakeholder mapping |
| **Region/legal awareness** | Notes NZ vs AU compliance diverges; flags this as a domain modelling decision (single model with region variant vs two models) | Mentions regional difference | Ignores legal.team's comment |
| **Next step proposal** | Proposes a concrete discovery workshop agenda or set of questions to send to Craig/Sarah before planning | Vague "let's have a meeting" | No next step |
| **Signal-to-noise ratio** | Plan is disciplined — no invented requirements, no speculation beyond what the transcript supports | Some invention | Significant hallucination |

---

### Variant G — Cross-Team 3-Squad Coordination

**Difficulty tier: 3 (Expert)**

```
orchestrator: Three engineering squads need to deliver a connected feature in the next sprint.

SQUAD A (Platform): Owns the driver-events SQS topic. Must add a new event type:
  ShiftCompletedEvent { driverId, vehicleId, shiftStartUtc, shiftEndUtc, totalDistanceKm }

SQUAD B (Compliance): Must consume ShiftCompletedEvent and evaluate whether the driver has
exceeded the weekly hours threshold (configurable per employment type). Must publish:
  ComplianceViolationEvent { driverId, violationType, severity, detectedAt }
  or
  CompliancePassedEvent { driverId, checkedAt }

SQUAD C (Reporting): Must consume both compliance events and update the fleet reporting
read model. Must expose a REST endpoint: GET /api/fleet/{fleetId}/compliance-summary

All three squads are working in parallel. They cannot wait for each other.

Produce an implementation plan that:
1. Defines the API contracts each squad must honour
2. Sequences the work so squads can develop in parallel
3. Specifies the rollback plan if Squad B's deployment fails after Squad A is live
4. Defines acceptance criteria per squad
```

**Scoring Rubric (Variant G)**

| Dimension | 5 | 3 | 1 |
|---|---|---|---|
| **API contract definition** | All 3 SQS event schemas defined (field names, types, required/optional); REST endpoint response schema defined | 2 schemas defined | 1 or 0 schemas |
| **Parallel work enablement** | Identifies contract-first approach; proposes stub consumers / test doubles so each squad can develop independently | Mentions parallelism | No parallel strategy |
| **Squad A rollback** | Specific rollback: SQS schema versioning or dual-publish (old + new event) so Squad C isn't broken if Squad B rolls back | Vague rollback | No rollback for A |
| **Squad B rollback** | Specific: if B fails post-deploy, A continues publishing, C degrades gracefully (stale data shown with warning, not error) | Mentions degraded state | No rollback for B |
| **Squad C rollback** | API versioning or feature flag so reporting endpoint can be disabled without affecting B/A; stale read model acceptable | Partial | No rollback for C |
| **Acceptance criteria per squad** | Each squad has ≥2 measurable acceptance criteria (Given/When/Then or equivalent) | 1 AC per squad | No AC |
| **Blast radius assessment** | Names specific risks: SQS consumer lag, schema incompatibility, eventual consistency window in read model | 1–2 risks | No blast radius |
| **Integration test strategy** | Proposes end-to-end integration test: publish ShiftCompletedEvent → verify ComplianceSummary updated within X seconds | Mentions testing | No integration test strategy |

---

## Variant Archive (A–D: Baseline / Intermediate)

| Variant | Scenario | Tier |
|---------|----------|------|
| A | "Driver hours compliance" — single-service, clear requirements | 1 |
| B | "Real-time fleet efficiency dashboard" — cross-service, vague | 2 |
| C | "Driver self-service portal" — new bounded context, auth, multi-tenant | 2 |
| D | "Compliance report export to CSV/PDF" — read model, scheduled job, file storage | 2 |
| E | Contradictory requirements — must surface conflicts, not plan | 3 |
| F | Discovery from raw Slack transcript — no spec | 3 |
| G | Cross-team 3-squad coordination with API contracts + rollback | 3 |

<details>
<summary>Variant A Prompt</summary>

```
orchestrator: Add a "driver hours compliance" feature to the EROAD sovereign platform.

Drivers must not exceed 13 hours of continuous driving. When a driver approaches 11 hours,
send them a warning notification. When they hit 13 hours, send a critical alert to the
fleet manager and log a compliance event.

Produce a detailed implementation plan.
```
</details>

<details>
<summary>Variant B Prompt</summary>

```
orchestrator: The business wants "real-time fleet efficiency reporting" in the EROAD sovereign platform.

Fleet managers should be able to see, on a live dashboard, which of their vehicles are currently
performing below the efficiency threshold. The data comes from trip events that are already being
published to SQS. The dashboard should refresh every 30 seconds.

Requirements are intentionally vague — you decide what's needed. Produce a detailed implementation plan.
```
</details>

## Grader Notes for benchmark-runner

1. Note which variant was run and its **difficulty tier** (1/2/3)
2. Score all rubric dimensions for the active variant with explicit reasoning
3. For **Ambiguity resolution** (where applicable): count explicit assumption statements; ≥3 = 5, 2 = 4, 1 = 3, 0 = 1
4. For **Edge cases** (where applicable): count distinct edge cases identified; ≥4 = 5, 3 = 4, 2 = 3, 1 = 2, 0 = 1
5. Average all dimension scores for the final score
6. Update "Active Variant" for next week
