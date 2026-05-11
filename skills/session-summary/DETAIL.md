# Session Summary — Reference Detail

## Session Note Format

Every session note follows this structure:

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

## Manual Writing Rules

If writing or updating a session note manually:

1. **Filename**: `YYYY-MM-DD-<kebab-case-title>.md`
2. **Location**: `~/copilot-sessions/sessions/`
3. **Required frontmatter**: `title`, `date`, `tags`, `session_id`
4. **Never delete** — if updating, add a new section at the bottom

---

## Cross-Linking to the Brain

Session notes can reference the main EROAD Brain vault using Obsidian wiki-links. Both vaults are on OneDrive so links resolve if both are open in Obsidian:

```markdown
Related knowledge: [[eroad-brain/01 - Services/media-service]]
ADR written: [[eroad-brain/04 - Decisions/adr-007-event-driven-provisioning]]
```

---

## Auto-Summariser Script Details

The script (`~/.copilot/scripts/summarize-session.py`) is triggered automatically by the `copilot()` zsh wrapper in `~/.zshrc` every time a session ends.

**Invocation modes:**
```bash
# Summarise the most recent session (no args)
python3 ~/.copilot/scripts/summarize-session.py

# Summarise a specific session by ID
python3 ~/.copilot/scripts/summarize-session.py <session-id>

# With agent-generated prose and learnings
python3 ~/.copilot/scripts/summarize-session.py <session-id> \
  --prose "summary" --learnings "learning1\nlearning2"
```

The auto-run captures the raw conversation. Your manual call adds the AI-generated prose and learnings that the auto-run can't produce — this is why both runs are needed.
