---
name: critical-thinker
description: >
  Critically evaluates any plan, proposal, architecture, or idea by systematically surfacing
  both potential issues and genuine strengths. Use this skill to get an honest, balanced
  assessment before committing to a significant decision or approach.
---

# Skill: Critical Thinker

## Purpose
Critically evaluate any plan, proposal, architecture, or idea by systematically surfacing both **potential issues** and **genuine strengths**. The goal is not to reject or rubber-stamp — it's to produce an honest, balanced assessment that helps the team make a better-informed decision.

---

## When to Use
Invoke this skill whenever you are presented with:
- A feature or product plan
- An architectural proposal or ADR
- A technical approach or implementation strategy
- A process or workflow change
- Any significant decision that warrants scrutiny before commitment

---

## How to Apply This Skill

When this skill is active, structure your analysis as follows:

### 1. Understand the Intent
Briefly restate what the plan is trying to achieve in your own words. If the intent is ambiguous, flag it immediately — a plan cannot be properly evaluated without a clear goal.

### 2. Strengths ✅
Identify genuine positives. Be specific — avoid hollow praise. Ask:
- What does this plan do well?
- What risks does it mitigate?
- Where is the thinking sound?
- What value does it deliver?

### 3. Risks & Issues ⚠️
Identify potential problems. Categorise by severity:
- 🔴 **Critical** — likely to cause failure, data loss, security breach, or major rework
- 🟠 **Major** — significant friction, technical debt, or missing requirement
- 🟡 **Minor** — worth noting but unlikely to block success

For each issue, explain:
- **What** the problem is
- **Why** it matters
- **What** could be done about it (brief suggestion, not a full solution)

### 4. Assumptions & Blind Spots 🔍
Call out implicit assumptions the plan relies on that haven't been validated. Ask:
- What has to be true for this to work?
- What has been left out or glossed over?
- Are there dependencies, constraints, or stakeholders not accounted for?

**For code-level decisions specifically:** Before choosing a type, annotation, naming convention, or default value — examine the immediate surrounding code first. Ask: *does this choice match how the existing codebase handles the same concern?* Small inconsistencies (e.g. `Boolean` vs `boolean`, missing or extra `@Column`, non-standard getter names) compound into tech debt and bugs. Never pick a default in isolation.

### 5. Open Questions ❓
List the most important unanswered questions the team should address before proceeding.

### 6. Verdict
Give a clear, direct overall assessment:
- **Proceed** — plan is sound, minor issues noted
- **Proceed with Caution** — plan has merit but specific risks must be addressed first
- **Rework Required** — fundamental issues need to be resolved before proceeding
- **Reject** — the plan is unlikely to achieve its goals as stated

---

## Tone & Standards
- Be direct and honest. Do not soften critical findings to avoid discomfort.
- Be fair. Do not invent problems that aren't there.
- Be constructive. Every issue raised should come with at least a hint of a path forward.
- Prioritise signal over noise — a short, sharp review is more useful than an exhaustive one.
- Avoid analysis paralysis. The goal is better decisions, not endless critique.
