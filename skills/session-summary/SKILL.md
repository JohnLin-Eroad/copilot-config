---
name: session-summary
description: >
  Invoke when a Copilot session ends (user says done/wrapping up), when the user says
  "save session" or "sync session", or when you need to look up what happened in a
  previous session.
---

# Session Summary — Copilot Sessions Vault

## Vault & Script

```
~/copilot-sessions/sessions/    ← one .md file per session
~/.copilot/scripts/summarize-session.py   ← auto-summariser
```

---

## When to Use

- **Session ending** — user says done, wrapping up, closing, "good job", etc.
- **Explicit request** — "save session", "sync session"
- **Lookup** — "what did I do last Tuesday?", "find the session where we discussed X"

---

## How to Save

```bash
# Get current session ID
SESSION_ID=$(ls -t ~/.copilot/session-state/ | head -1)

# Save with prose + learnings
python3 ~/.copilot/scripts/summarize-session.py "$SESSION_ID" \
  --prose "2-5 sentence summary of what was accomplished" \
  --learnings "learning 1\nlearning 2\n..."
```

The `--prose` content is stored between `<!-- prose_start -->` / `<!-- prose_end -->` markers. Re-runs without `--prose` preserve existing prose.

---

## What Makes a Good Learning

Ask: *"Would this help a future agent avoid a mistake or understand non-obvious behaviour?"*

- ✅ "Cognito pre-token-gen Lambda runs before JWT issuance — use it to inject claims"
- ✅ "OneDrive sync can corrupt markdown with null bytes — validate after sync"
- ❌ "19 domain files rewritten" (status report)
- ❌ "GitHub repo link from service note frontmatter" (template field)

---

## Gotchas

- **Always pass `--prose`** — without it, the note has no human-readable summary, just raw conversation excerpts
- **Learnings are newline-separated in the flag** — use `\n` between them, not separate `--learnings` flags
- **Don't write structural metadata as learnings** — service descriptions, file counts, and link references aren't insights
- **Session ID is the folder name** in `~/.copilot/session-state/`, not a timestamp or slug
- **The script is also run automatically** by the `copilot()` zsh wrapper on session exit — your manual call adds the AI-generated prose that the auto-run can't produce
- **Prose is preserved on re-runs** — safe to re-run the script; it won't overwrite existing prose

---

## How to Find Previous Sessions

```bash
ls ~/copilot-sessions/sessions/                                    # list all
grep -r --include="*.md" -l "KEYWORD" ~/copilot-sessions/sessions/ # search
```

---

## Progressive Loading

📘 **GUIDE.md** — Read when you need to write high-quality learnings or understand the extraction mechanism.

```bash
cat ~/.copilot/skills/session-summary/GUIDE.md
```

📖 **DETAIL.md** — Read when you need the session note template format or manual writing rules.

```bash
cat ~/.copilot/skills/session-summary/DETAIL.md
```
