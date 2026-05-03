# Dual-Critique — Protocol Guide

## Step 0 — Frame the Brief

Before starting the loop, write a **one-paragraph brief** containing:
1. What the plan is trying to achieve
2. Key constraints (time, tech stack, team, blast radius)
3. What "good enough" convergence looks like

---

## Step 1 — Planner Pass (Opus 4.6)

Spawn an **explore** or **general-purpose** agent with `model: "claude-opus-4.6"`.

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

---

## Step 2 — Critiquer Pass (Codex)

Spawn an **explore** agent with `model: "gpt-5.3-codex"`.

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

---

## Step 3 — Convergence Check

After each Critiquer pass:
- **CONVERGENCE: YES** → proceed to synthesis
- **CONVERGENCE: NO** and round < 3 → increment round, return to Step 1
- Round = 3 and still not converged → proceed to synthesis with unresolved issues flagged

**Convergence criteria:** No 🔴 or 🟠 findings remain. Minor (🟡) issues are noted but don't block.

---

## Tone Standards

**Planner (Opus):** Assertive, specific, commits to choices. No hedging with "it depends" without a concrete follow-through.

**Critiquer (Codex):** Direct, unsentimental, failure-mode focused. Does not capitulate to confidence. Does not manufacture problems.
