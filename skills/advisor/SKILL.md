---
name: advisor
description: >
  Convenes a panel of five named advisors — each with a distinct mental model — to examine
  a problem, plan, or decision from multiple angles simultaneously. Lighter than dual-critique
  (single pass, no multi-model spawning), richer than critical-thinker (5 voices vs 1).
  Use for strategic decisions, design choices, and plans where diverse perspectives matter.
---

# Skill: Advisor Panel

## Purpose

Convene a **virtual advisory board** of five advisors, each with a sharply distinct mental model, to examine any problem, plan, or decision. Each advisor speaks in their authentic voice. The panel ends with a synthesis.

This technique surfaces blind spots that a single analytical framework misses. It is not a debate — advisors don't respond to each other. They each give their independent take, and the synthesis draws out tensions and consensus.

---

## When to Use

- Strategic or directional decisions (what to build, what to prioritise, what approach to take)
- Architectural proposals before committing to them
- Plans that benefit from diverse perspectives in a single pass
- Situations where you suspect you're in an echo chamber
- When you want something richer than a checklist critique but lighter than a full dual-critique loop

**Do NOT use for:**
- Routine code changes or well-understood implementations
- Situations where you need adversarial pressure-testing → use `dual-critique` instead
- Situations where you need a structured risk/strength breakdown → use `critical-thinker` instead
- Tasks where action is needed quickly and the decision is low blast-radius

---

## The Panel

### 🔬 The First Principles Thinker
*"What is this actually trying to solve?"*

Strips away assumptions. Asks: what is the core problem? Is this the right abstraction? What would this look like if we started from scratch with no legacy constraints? Challenges the framing of the problem itself, not just the solution.

### ⚠️ The Risk Scout
*"How does this blow up?"*

Identifies the top failure modes. Focuses on what's hard to reverse, what the blast radius is, what's being underestimated. Does not catastrophise — ranks risks by likelihood × impact. Flags the one thing most likely to cause regret.

### 🔧 The Pragmatist
*"Can we actually build this?"*

Grounds the discussion in operational reality. What will take 10× longer than expected? What dependencies are being glossed over? What does this cost in maintenance burden, cognitive load, or tech debt? Represents the engineers who will live with this decision.

### 🔭 The Long-Game Strategist
*"Where does this leave us in 3 years?"*

Evaluates compounding effects. Does this decision open up future options or constrain them? Does it build toward a coherent architecture or create islands? Will we be proud of this choice in 36 months, or will it be the thing we're paying down?

### 🔥 The Devil's Advocate
*"This is the wrong approach entirely."*

Argues the strongest possible case against the proposal. Not to be contrarian — to surface the best argument for a different path. Forces the proposer to either address the objection or consciously accept the trade-off.

---

## Output Format

When this skill is active, structure your response exactly as follows:

```markdown
## Advisory Panel: [Brief Topic]

### 🔬 First Principles Thinker
[3–5 sentences. Direct and specific. No hedging.]

### ⚠️ Risk Scout
[3–5 sentences. Name the top 2–3 risks. Be concrete.]

### 🔧 Pragmatist
[3–5 sentences. Focus on what's underestimated or glossed over.]

### 🔭 Long-Game Strategist
[3–5 sentences. Future-state reasoning. Option value vs lock-in.]

### 🔥 Devil's Advocate
[3–5 sentences. Strongest case against. Not nitpicking — a coherent alternative view.]

---

### Panel Synthesis

**Where advisors agree:** [1–2 points of genuine consensus]
**Key tension:** [The most important disagreement or trade-off surfaced by the panel]
**Recommendation:** [What the panel collectively suggests — direct, actionable]
**Watch closely:** [The single biggest risk or unknown to monitor going forward]
```

---

## Tone Standards

- Each advisor speaks in their voice — not as a generic analysis bullet list
- Advisors are direct and specific. They name files, services, numbers, timelines where relevant
- No advisor rubber-stamps. If the proposal is sound, they still find the most important nuance
- The synthesis is not a summary — it adds value by resolving tensions and committing to a recommendation
- Total response should be scannable in 2–3 minutes. Prefer sharp over exhaustive

---

## Comparison to Other Skills

| Skill | Perspectives | Cost | Use When |
|---|---|---|---|
| `critical-thinker` | 1 (structured) | Low | You want a thorough risk/strength breakdown |
| `advisor` | 5 (diverse, single pass) | Medium | You want multiple lenses quickly |
| `dual-critique` | 2 (adversarial, multi-round) | High | HIGH blast-radius, need adversarial pressure |

---

## Example

**Input:** "We're considering replacing our PostgreSQL event store with DynamoDB to handle scale."

**Output:**
> ### 🔬 First Principles Thinker
> The core question is: what scale problem are you actually experiencing? PostgreSQL scales further than most teams realise with proper indexing and read replicas. Before migrating, define the specific bottleneck — transactions per second? Read latency? Storage? The answer determines whether DynamoDB is the right lever or whether it's solving a different problem.

> ### ⚠️ Risk Scout
> Three risks: (1) Loss of ACID transactions — DynamoDB's eventual consistency model will require rethinking any workflow that currently relies on atomic writes across multiple entities. (2) Query flexibility — ad-hoc queries that are trivial in SQL become expensive access-pattern designs in DynamoDB. (3) Migration blast radius — the event store is foundational; a failed migration mid-stream is extremely hard to recover from.

> *(and so on for each advisor...)*
