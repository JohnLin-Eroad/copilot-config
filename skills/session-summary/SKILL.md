---
name: session-summary
description: >
  Teaches agents how to read from and write session summaries to the Copilot Sessions
  Obsidian vault. Use this skill when you want to manually save or update the current
  session log, or look up what happened in a previous session.
---

# Session Summary — Copilot Sessions Vault

## Vault Location

```
/Users/johnlin/Library/CloudStorage/OneDrive-EROAD/Documents/copilot-sessions
```

Shorthand: `$SESSIONS_VAULT`

---

## Folder Structure

```
copilot-sessions/
├── README.md
└── sessions/
    └── YYYY-MM-DD-<session-slug>.md   ← one file per session
```

---

## Auto-Summariser Script

The vault is automatically populated by:

```
~/.copilot/scripts/summarize-session.py
```

This script is triggered by the `copilot()` zsh wrapper function in `~/.zshrc`
every time a `gh copilot chat` session ends.

**Run manually:**
```bash
# Summarise the most recent session
python3 ~/.copilot/scripts/summarize-session.py

# Summarise a specific session by ID
python3 ~/.copilot/scripts/summarize-session.py <session-id>

# Summarise with a human prose summary (agent-generated)
python3 ~/.copilot/scripts/summarize-session.py <session-id> --prose "Your 2-4 sentence summary here"
```

## Agent Prose Summary Protocol

When syncing a session (triggered by "sync session", "save session", etc.):

1. **Generate a prose summary** of the full conversation — 2–5 sentences capturing what was accomplished, what was built/configured, and any notable decisions.
2. **Pass it via `--prose`** when calling the script.

**Example:**
```bash
python3 ~/.copilot/scripts/summarize-session.py be041063 \
  --prose "The session built a full session-sync pipeline including a csync alias, same-day squashing for Notion and Obsidian, and a summary table at the top of each daily note. All historical sessions were backfilled into the new format."
```

The prose is stored between `<!-- prose_start -->` and `<!-- prose_end -->` markers in the daily Obsidian file — visible directly below the summary table. If `--prose` is omitted on re-runs, existing prose is preserved unchanged.

---

## Session Note Format

Every session note is a markdown file with this structure:

```markdown
---
title: "Session Title"
date: "YYYY-MM-DD"
tags:
  - copilot-session
  - ai
session_id: <uuid>
---

# Session Title

## Session Metadata
| Field | Value |
|---|---|
| Date | ... |
| Working Directory | ... |
| Repository | ... |
| Branch | ... |
| Messages | N user / M AI turns |

## Conversation
**🧑 You:** <user message>

**🤖 Copilot:** <AI response snippet>
...
```

---

## Finding Previous Sessions

```bash
# List all saved sessions
ls "$SESSIONS_VAULT/sessions/"

# Search across all sessions for a keyword
grep -r --include="*.md" -l "KEYWORD" "$SESSIONS_VAULT/sessions/"

# Find sessions about a specific topic
grep -r --include="*.md" -n "obsidian\|brain" "$SESSIONS_VAULT/sessions/"
```

---

## Manually Writing a Session Summary

If you want to write or update a session note manually, follow these rules:

1. **Filename**: `YYYY-MM-DD-<kebab-case-title>.md`
2. **Location**: `$SESSIONS_VAULT/sessions/`
3. **Required frontmatter**: `title`, `date`, `tags`, `session_id`
4. **Never delete** — if updating, add a new section at the bottom

---

## Linking to the Main Brain

Session notes may cross-link to the main EROAD Brain vault using Obsidian wiki-links.
Both vaults are on OneDrive so links will resolve if both are open in Obsidian.

```markdown
Related knowledge: [[eroad-brain/01 - Services/media-service]]
ADR written: [[eroad-brain/04 - Decisions/adr-007-event-driven-provisioning]]
```
