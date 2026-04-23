---
name: html-report
description: >
  Teaches agents how to generate beautiful, dark-themed HTML reports from research
  output, work summaries, or any structured findings — and automatically open them
  in the browser. Use after completing research, analysis, benchmarks, or any task
  where a polished visual summary is more useful than raw markdown.
---

# Skill: HTML Report

Generate a self-contained, dark-themed HTML report — saved to the session files folder and opened in the browser automatically.

---

## When to Trigger

- Completed research/analysis with **3+ structured sections**
- User asks for an HTML report, visual summary, or "make it pretty"
- Structured data (comparisons, benchmarks, scores, rankings) that benefits from visual presentation
- Weekly reports, audit summaries, or multi-dimensional analysis

**Do NOT use when:** single paragraph output, user asked for markdown, or output goes to Jira/Confluence/Notion.

---

## Output Contract

1. **Save** to `~/.copilot/session-state/<session-id>/files/<name>.html`
2. **Open** with `open <filepath>` (macOS)
3. **Confirm** with: `📊 Report saved to: <path>` / `🌐 Opened in browser.`
4. Do NOT ask permission — just generate and open
5. File must be **fully self-contained** — no external CSS, JS, fonts, or images

---

## Colour Semantics

| Colour | CSS Variable | Use for |
|---|---|---|
| Green `#34d399` | `--accent-green` | Positive, passing, good, success |
| Yellow `#fbbf24` | `--accent-yellow` | Warning, moderate, needs attention |
| Red `#f87171` | `--accent-red` | Critical, failing, danger, blocking |
| Blue `#6c8ef7` | `--accent-blue` | Informational, neutral highlight, primary accent |
| Purple `#a78bfa` | `--accent-purple` | New, experimental, premium |
| Cyan `#22d3ee` | `--accent-cyan` | Secondary info, alternative highlight |

---

## Available Components

`card`, `card-grid`, `table`, `badge` (green/yellow/red/blue/purple), `callout` (info/warn/danger/success), `score-bar`, `stat-row`, `trend-item`, `code-block`, `tag-list`

---

## Progressive Loading

This skill has **3 tiers**. You are reading **Tier 1** (brief).

📘 **GUIDE.md** — Read when you are ready to start building the report.
Contains: the 5-step process, filename conventions, HTML skeleton, and quality tips.

```bash
cat ~/.copilot/skills/html-report/GUIDE.md
```

📖 **DETAIL.md** — Read when you need the exact CSS or component HTML snippets.
Contains: full design system CSS, sidebar JS, and copy-paste component library.
**Do NOT generate CSS from memory** — always read DETAIL.md for the canonical styles.

```bash
cat ~/.copilot/skills/html-report/DETAIL.md
```
