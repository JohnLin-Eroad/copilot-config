---
name: dual-critique
description: >
  Invoke for HIGH/CRITICAL blast-radius decisions where a single model's optimism bias
  could lead you astray. Runs an adversarial loop between Claude Opus (optimistic planner)
  and GPT Codex (pessimistic critiquer) until convergence or 3 rounds.
---

# Dual-Critique (Opus × Codex Adversarial Loop)

Structured adversarial collaboration between two models with **complementary biases**:

| Role | Model | Bias | Job |
|---|---|---|---|
| **Planner** | `claude-opus-4.6` | Optimistic, visionary | Produce the best version of the plan |
| **Critiquer** | `gpt-5.3-codex` | Pessimistic, implementation-grounded | Find every way it can fail |

Loop continues until the Critiquer rates all remaining issues as **Minor** — or until 3 rounds complete.

---

## When to Use

- Architectural decisions with HIGH/CRITICAL blast radius
- Plans that will be hard to reverse once started
- Proposals where you suspect optimism bias
- ADRs before finalisation
- Multi-service refactors or data migrations

**Not for:** Routine code changes, simple features, anything well-understood — the token cost (~45k) isn't worth it.

---

## Protocol Summary

1. **Frame the brief** — one paragraph: goal, constraints, convergence criteria
2. **Planner pass** (Opus) — produce the strongest plan, address prior critique
3. **Critiquer pass** (Codex) — rate every issue 🔴 Critical / 🟠 Major / 🟡 Minor
4. **Convergence check** — all issues Minor? → done. Otherwise → next round (max 3)
5. **Synthesise** — final plan + unresolved issues + what changed between rounds

---

## Gotchas

- **Don't skip the brief** — without explicit convergence criteria, the loop runs 3 rounds every time with no clear endpoint
- **Spawn separate agents per role** — don't simulate both voices yourself; the whole point is cross-model bias cancellation
- **Critiquer must not rubber-stamp** — if Codex agrees too easily, the prompt isn't strong enough; add "Do NOT agree for the sake of convergence"
- **3-round cap is a hard limit** — if still not converged, surface unresolved issues for human decision; don't keep looping
- **Token budget is ~45k total** — confirm with user before starting if the decision might not warrant the cost
- **Planner must commit to concrete choices** — "it depends" without a follow-through answer is not acceptable

---

## Progressive Loading

📘 **GUIDE.md** — Read when you're about to run the loop. Contains the full 4-step protocol with prompt templates for each role.

```bash
cat ~/.copilot/skills/dual-critique/GUIDE.md
```

📖 **DETAIL.md** — Read when you need the synthesis output format, temp file structure, or a worked example.

```bash
cat ~/.copilot/skills/dual-critique/DETAIL.md
```
