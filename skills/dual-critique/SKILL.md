---
name: dual-critique
description: >
  Runs an adversarial collaboration loop between Claude Opus 4.6 (optimistic planner) and
  GPT Codex (pessimistic critiquer) to pressure-test plans, architectures, or proposals.
  Opus expands and refines; Codex pokes holes. They iterate until convergence. Use for
  HIGH blast-radius decisions where a single model's bias could lead you astray.
---

# Skill: Dual-Critique (Opus × Codex Adversarial Loop)

## Purpose

Run a structured adversarial collaboration between two models with **complementary biases**:

| Role | Model | Bias | Job |
|---|---|---|---|
| **Planner** | `claude-opus-4.6` | Optimistic, visionary, can over-promise | Produce the best version of the plan |
| **Critiquer** | `gpt-5.3-codex` | Pessimistic, implementation-grounded | Find every way it can fail |

The loop continues until the Critiquer rates all remaining issues as **Minor** — or until 3 rounds complete. The result is a plan that has survived genuine adversarial scrutiny.

---

## When to Use

Invoke this skill for:
- Architectural decisions with HIGH/CRITICAL blast radius
- Plans that will be hard to reverse once started
- Any proposal where you suspect optimism bias (your own or an agent's)
- ADRs before finalisation
- Multi-service refactors or data migrations

**Do NOT use for:**
- Routine code changes
- Simple feature implementations
- Anything already well-understood — the cost (tokens + time) isn't worth it

---

## Protocol

### Step 0 — Frame the Brief

Before starting the loop, produce a **one-paragraph brief** containing:
1. What the plan is trying to achieve
2. Key constraints (time, tech stack, team, blast radius)
3. What "good enough" convergence looks like

### Step 1 — Planner Pass (Opus 4.6)

Spawn an **explore** or **general-purpose** agent with `model: "claude-opus-4.6"`.

Prompt template:
```
You are the PLANNER in an adversarial collaboration loop.
Your job: produce the strongest, most complete version of the following plan.
Be ambitious but grounded. Make it specific — name files, services, APIs, data flows.
Do not hedge excessively. Commit to concrete choices.

BRIEF:
<brief>

ROUND: <N>
CRITIQUER FINDINGS FROM LAST ROUND (if any):
<findings>

Produce: a revised plan that addresses the critiquer's findings where valid.
Format: numbered steps, clear decisions, explicit assumptions.
```

### Step 2 — Critiquer Pass (Codex)

Spawn an **explore** agent with `model: "gpt-5.3-codex"`.

Prompt template:
```
You are the CRITIQUER in an adversarial collaboration loop.
Your job: find every way this plan can fail. Be systematic and unsentimental.
Do NOT rubber-stamp. Do NOT agree for the sake of convergence.
Rate each finding: 🔴 Critical / 🟠 Major / 🟡 Minor

PLAN TO CRITIQUE:
<planner_output>

For each finding output:
- Severity: 🔴/🟠/🟡
- Issue: what can go wrong
- Why it matters: impact if not addressed
- Suggested fix: brief (not a full solution)

End with: CONVERGENCE CHECK — are all remaining issues Minor? YES/NO
```

### Step 3 — Convergence Check

After each Critiquer pass:

- If **CONVERGENCE: YES** → proceed to Step 4
- If **CONVERGENCE: NO** and round < 3 → increment round, return to Step 1 with critiquer findings
- If round = 3 and still not converged → proceed to Step 4 with **explicit unresolved issues** flagged

### Step 4 — Synthesise Output

After the loop, produce the final output:

```markdown
## Dual-Critique Result

**Rounds taken:** N
**Convergence:** YES / PARTIAL (N unresolved issues)

### Final Plan
<the Planner's last output>

### Unresolved Issues (if any)
<any 🔴/🟠 findings the Planner did not fully address>
Human judgement required on these before proceeding.

### What Changed Between Rounds
- Round 1→2: <key changes driven by critique>
- Round 2→3: <key changes driven by critique>
```

---

## Practical Invocation

When this skill is active, the invoking agent should:

1. Write the brief to a temp file: `/tmp/dual-critique-<slug>/brief.md`
2. Run the loop using the **task** tool — spawn Planner and Critiquer as separate agents per round
3. Save each round's output to `/tmp/dual-critique-<slug>/round-N-plan.md` and `round-N-critique.md`
4. After loop completes, present the synthesised output to the user

**Token budget guidance:**
- Each round: ~8–15k tokens (Opus plan + Codex critique)
- 3 rounds max: ~45k tokens total
- Not appropriate for trivial decisions — confirm with user before starting if uncertain

---

## Convergence Criteria

The Critiquer declares convergence when **no 🔴 or 🟠 findings remain**. Minor (🟡) issues are noted but do not block convergence. If the Critiquer has not converged by round 3, surface all unresolved issues and let the human decide.

---

## Tone Standards

**Planner (Opus):** Assertive, specific, commits to choices. Does not hedge with "it depends" without following through with a concrete answer.

**Critiquer (Codex):** Direct, unsentimental, focused on failure modes. Does not capitulate to the Planner's confidence. Does not manufacture problems that aren't there.

---

## Example Use

```
User: "I want to refactor the telematics ingestion pipeline to use SQS FIFO instead of Kinesis"

Invocation:
  skill: dual-critique
  brief: Migrate espserver-service → ebox-service → central-event-forwarder chain 
         from Kinesis to SQS FIFO. Constraints: zero downtime, no schema changes, 
         2-week window. Convergence = no ordering or throughput risks unaddressed.
```

Round 1: Opus produces migration plan with blue-green cutover
Round 2: Codex flags FIFO throughput limit (3,000 msg/s) vs current Kinesis peak
Round 3: Opus revises with message batching + FIFO group IDs per vehicle
Critiquer: all remaining issues minor → CONVERGED
```
