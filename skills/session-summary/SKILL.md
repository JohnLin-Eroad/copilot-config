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

## Invocation

### In-session trigger (inside Copilot chat)
When the user says any of:
- "sync session"
- "sync session data"
- "save session"
- "sync to obsidian"
- "sync to notion"

…the agent MUST immediately run the summariser script for the **current session ID**
(available from `workspace.yaml` in the session state directory):

```bash
python3 ~/.copilot/scripts/summarize-session.py <current-session-id>
```

The session ID is the UUID folder name under `~/.copilot/session-state/`.
Always pass the current session ID explicitly so the script doesn't fall back to
the last-modified session.

### Terminal alias
A `csync` zsh function is defined in `~/.zshrc` for quick manual invocation:

```bash
csync              # syncs the most recent session
csync <session-id> # syncs a specific session
```

### Automatic (on session exit)
The `copilot()` zsh wrapper in `~/.zshrc` calls this script automatically
every time a `gh copilot chat` session ends — no manual action needed.

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
