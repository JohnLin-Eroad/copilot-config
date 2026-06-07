---
name: advisor
description: >
  Invoke when facing a strategic or directional decision — what to build, which approach
  to take, or how to prioritise. Convenes 5 named advisors with distinct mental models
  for a single-pass multi-perspective analysis. Lighter than dual-critique, richer than
  critical-thinker.
---

# Advisor Panel

Convene a **virtual advisory board** of five advisors to examine a problem, plan, or decision from multiple angles simultaneously. Each speaks independently — this is not a debate.

---

## The Five Advisors

| Advisor | Lens | Core Question |
|---|---|---|
| 🔬 First Principles Thinker | Assumptions & framing | "What is this actually trying to solve?" |
| ⚠️ Risk Scout | Failure modes & blast radius | "How does this blow up?" |
| 🔧 Pragmatist | Operational reality | "Can we actually build this?" |
| 🔭 Long-Game Strategist | Compounding effects | "Where does this leave us in 3 years?" |
| 🔥 Devil's Advocate | Strongest counter-argument | "This is the wrong approach entirely." |

---

## When to Use

- Strategic / directional decisions (what to build, which approach)
- Architectural proposals before committing
- Situations where you suspect echo-chamber thinking
- Plans that benefit from diverse perspectives in a single pass

**Not for:**
- Routine code changes — overkill
- Adversarial pressure-testing → use `dual-critique`
- Structured risk/strength breakdown → use `critical-thinker`
- Low blast-radius decisions where speed matters more

---

## Gotchas

- **Advisors don't talk to each other** — they give independent takes; the synthesis resolves tensions
- **No advisor rubber-stamps** — even if the proposal is sound, each must find the most important nuance
- **The synthesis is not a summary** — it must add value by committing to a recommendation
- **Be specific, not generic** — advisors should name files, services, numbers, timelines — not speak in abstract platitudes
- **Devil's Advocate argues for a real alternative** — not nitpicking; a coherent different path
- **Keep it scannable** — total output should be readable in 2-3 minutes; sharp over exhaustive

---

## Progressive Loading

📘 **GUIDE.md** — Read when you're about to produce the panel output. Contains the exact output format and tone standards.

```bash
cat ~/.copilot/skills/advisor/GUIDE.md
```

📖 **DETAIL.md** — Read when you need the full advisor role descriptions or an example of a complete panel output.

```bash
cat ~/.copilot/skills/advisor/DETAIL.md
```
