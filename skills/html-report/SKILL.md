---
name: html-report
description: >
  Generates a beautiful, self-contained HTML page to present task results to the
  user. Invoke at the end of any task to visually summarise what was accomplished —
  and automatically open it in the browser.
---

# Skill: HTML Report

On task completion, generate a self-contained HTML page that shows the user what you did — then save it and open it in the browser.

---

## When to Use

Generate an HTML page when a task produces output worth presenting visually:
- Code changes, refactors, or migrations — summarise what changed and where
- Research or analysis — present findings, comparisons, recommendations
- Benchmarks, audits, reviews — show scores, status, trends
- Any multi-step task — give the user a clear picture of what was accomplished

**Skip when:** output is a single sentence, user asked for markdown/plain text, or output goes to Jira/Confluence/Notion.

---

## Output Contract

1. **Save** to `~/.copilot/session-state/<session-id>/files/<name>.html`
2. **Open** with `open <filepath>` (macOS)
3. **Confirm** with: `📊 Report saved to: <path>` / `🌐 Opened in browser.`
4. Do NOT ask permission — just generate and open
5. File must be **fully self-contained** — no external CSS, JS, fonts, or images

---

## Content & Layout

**Let the task output drive the structure.** There is no fixed layout — choose what fits:
- A simple summary page for a small task
- A dashboard with stats and cards for a multi-file change
- A comparison table for benchmarks or before/after analysis
- A narrative with callouts for research findings

Use the dark theme design system and component library for a consistent, polished look — but pick only the components that serve your content.

---

## Progressive Loading

This skill has **3 tiers**. You are reading **Tier 1** (brief).

📘 **GUIDE.md** — Read when you are ready to build the page.
Contains: the build process, filename conventions, HTML skeleton, layout guidance, and quality tips.

```bash
cat ~/.copilot/skills/html-report/GUIDE.md
```

📖 **DETAIL.md** — Read when you need the exact CSS or component HTML snippets.
Contains: full design system CSS, optional sidebar JS, and copy-paste component library.
**Do NOT generate CSS from memory** — always read DETAIL.md for the canonical styles.

```bash
cat ~/.copilot/skills/html-report/DETAIL.md
```
