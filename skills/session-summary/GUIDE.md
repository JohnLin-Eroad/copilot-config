# Session Summary — Learnings & Extraction Guide

## Writing High-Quality Learnings

Learnings are **forward-looking insights** — not a log of what was done.

### The Litmus Test

> "Would this help a future agent or engineer avoid a mistake, understand a non-obvious behaviour, or make a better decision?"

If yes → write it. If it's just describing what exists → skip it.

### ✅ Good learnings:
- "OneDrive sync can corrupt markdown files with null bytes — always validate after sync"
- "Cognito pre-token-gen Lambda runs before the JWT is issued — use it to inject claims, not post-auth"
- "myeroad-impersonation-service clones the full user context, not just the token"
- "The myeroad-custom-authorizer is the sole API Gateway auth path — changes affect all downstream services"
- "DynamoDB-backed IDP config in myeroad-idp-service is cached — restart needed to pick up changes"

### ❌ Not learnings (structural metadata):
- "MyEROAD Portal Login — Cognito + Amplify + Lambda triggers" ← service description
- "19 domain files rewritten" ← status report
- "220 service references — all 220 linked" ← count
- "GitHub repo link from service note frontmatter" ← template field

---

## Full Script Example

```bash
python3 ~/.copilot/scripts/summarize-session.py be041063 \
  --prose "Mapped the full EROAD auth flow: Cognito + Amplify handles portal login, pre-token-gen Lambda injects user abilities, and myeroad-impersonation-service handles the clone flow for impersonation." \
  --learnings "Cognito pre-token-gen Lambda adds user abilities at login — this is why /userInfo/{username} is needed as a fallback lookup
User impersonation uses a clone flow in myeroad-impersonation-service, not JWT swapping
OneDrive sync can introduce null-byte corruption in markdown files — always validate file integrity after a sync
The myeroad-custom-authorizer Lambda is the single entry point for API Gateway auth — changes here affect all services"
```

---

## Automatic Extraction (when `--learnings` is omitted)

The script extracts learnings in priority order:

1. `<!-- learnings_start -->` ... `<!-- learnings_end -->` markers in any AI message
2. Content under a `## Key Learnings` or `## Learnings` heading
3. **Fallback heuristic**: bullet points with insight language (`always`, `never`, `gotcha`, `be aware`, `turns out`, etc.) — structural noise is filtered out

To guarantee clean extraction, write an explicit block:

```markdown
## Key Learnings

- OneDrive sync corrupts files with null bytes — validate after every sync
- The pre-token-gen Lambda runs before JWT issuance — right place for claim injection
```

Or use inline markers:

```
<!-- learnings_start -->
- Cognito pre-token-gen Lambda injects user abilities before JWT is issued
- Impersonation uses clone flow — not JWT swapping
<!-- learnings_end -->
```
