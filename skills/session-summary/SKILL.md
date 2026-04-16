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
~/copilot-sessions
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
2. **Generate explicit learnings** — distilled, forward-looking insights (see below).
3. **Pass both via flags** when calling the script.

**Example:**
```bash
python3 ~/.copilot/scripts/summarize-session.py be041063 \
  --prose "Mapped the full EROAD auth flow: Cognito + Amplify handles portal login, pre-token-gen Lambda injects user abilities, and myeroad-impersonation-service handles the clone flow for impersonation." \
  --learnings "Cognito pre-token-gen Lambda adds user abilities at login — this is why /userInfo/{username} is needed as a fallback lookup
User impersonation uses a clone flow in myeroad-impersonation-service, not JWT swapping
OneDrive sync can introduce null-byte corruption in markdown files — always validate file integrity after a sync
The myeroad-custom-authorizer Lambda is the single entry point for API Gateway auth — changes here affect all services"
```

The prose is stored between `<!-- prose_start -->` and `<!-- prose_end -->` markers in the daily Obsidian file. If `--prose` is omitted on re-runs, existing prose is preserved unchanged.

---

## Learnings — What to Write vs What to Skip

Learnings should be **forward-looking insights** a future agent or engineer would benefit from knowing. They are NOT a log of what was done.

### ✅ Write learnings like this:
- "OneDrive sync can corrupt markdown files with null bytes — always validate after sync"
- "Cognito pre-token-gen Lambda runs before the JWT is issued — use it to inject claims, not post-auth"
- "myeroad-impersonation-service clones the full user context, not just the token"
- "The myeroad-custom-authorizer is the sole API Gateway auth path — changes affect all downstream services"
- "DynamoDB-backed IDP config in myeroad-idp-service is cached — a restart is needed to pick up changes"

### ❌ Do NOT write structural metadata:
- "**MyEROAD Portal Login** — Cognito + Amplify + Lambda triggers" ← service description, not a learning
- "19 domain files rewritten" ← status report
- "220 service references — all 220 linked" ← count
- "GitHub repo link (direct URL from service note frontmatter)" ← template field

### The test: ask yourself
> "Would this help a future agent or engineer avoid a mistake, understand a non-obvious behaviour, or make a better decision?"

If yes → write it. If it's just describing what exists → skip it.

---

## Automatic Extraction (no `--learnings` flag)

If `--learnings` is not provided, the script extracts learnings in priority order:

1. `<!-- learnings_start -->` ... `<!-- learnings_end -->` markers in any AI message
2. Content under a `## Key Learnings` or `## Learnings` heading in any AI message
3. **Fallback heuristic**: bullet points with insight language (`always`, `never`, `gotcha`, `be aware`, `turns out`, etc.) — structural noise is filtered out automatically

To guarantee clean extractions, write an explicit learnings block in your response:

```markdown
## Key Learnings

- OneDrive sync corrupts files with null bytes — validate after every sync
- The pre-token-gen Lambda runs before JWT issuance, making it the right place for claim injection
```

Or use inline markers:

```
<!-- learnings_start -->
- Cognito pre-token-gen Lambda injects user abilities before JWT is issued
- Impersonation uses clone flow — not JWT swapping
<!-- learnings_end -->
```

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
