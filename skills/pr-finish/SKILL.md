---
name: pr-finish
description: >
  Invoke to run the standard end-of-PR ritual on the current branch's pull request:
  address and resolve Copilot/reviewer review comments, request the standard reviewer
  trio (Naveed, Jahz, Almir), and rename the session/terminal to the Jira ticket.
  Trigger phrases: "finish the PR", "pr-finish", "copilot left comments, address and
  resolve", "tag the usual reviewers", "wrap up this PR".
---

# PR Finish — End-of-PR Ritual

Automates the recurring steps performed at the end of almost every EROAD PR. Run the
steps that apply; skip any the user says are already done. Confirm before destructive
or review-state-changing actions only if the PR is not authored by the user.

## Standard reviewers

| Name   | GitHub handle  |
| ------ | -------------- |
| Naveed | `naveednizar`  |
| Jahz   | `atienzajazz`  |
| Almir  | `almirjamee`   |

> If the user names a different/extra reviewer in the prompt, add them too.
> Never request the PR author as a reviewer.

## Resolve order

Run these in order. Identify the PR for the current branch first:

```bash
PR=$(rtk gh pr view --json number,title,headRefName,url -q '{number,title,headRefName,url}')
echo "$PR"
```

If no PR exists for the branch, tell the user and stop (don't open one unless asked).

### 1. Address & resolve review comments

1. Fetch unresolved review threads (Copilot + human reviewers):
   ```bash
   rtk gh pr view <num> --comments
   ```
   For full thread + resolution state, use the GraphQL helper in DETAIL.md.
2. For each **unresolved** comment that represents an actionable change:
   - Make the code change (surgical — follow existing repo patterns).
   - After all changes for a file are made, note which comment it addresses.
3. **Only resolve comments you actually addressed.** The user is explicit about this —
   never bulk-resolve. Leave anything you couldn't address open and list it back to them.
4. Resolve addressed threads (GraphQL `resolveReviewThread` — see DETAIL.md).
5. Commit with a clear message and push:
   ```bash
   rtk git add -A && rtk git commit -m "address review comments" && rtk git push
   ```
   (Co-author trailer per global instructions.)

### 2. Request the standard reviewers

```bash
rtk gh pr edit <num> --add-reviewer naveednizar,atienzajazz,almirjamee
```
- Skip any handle that is the PR author (GitHub rejects self-review).
- **`gh` exits 0 even when a reviewer is silently dropped** (non-collaborator / author).
  Always verify with `gh pr view <num> --json reviewRequests` and report anyone missing —
  don't trust the exit code. See DETAIL.md.

### 3. Rename the session/terminal to the ticket

1. Derive the ticket from the branch or PR title (e.g. `VSF-3807`, `DRP-387`). Branches
   like `NONE-fix-client-publish` → use `NONE-...` slug.
2. Rename the CLI session so it's findable later:
   ```
   /rename <TICKET>: <short description>
   ```
   (This is a CLI slash command — surface it for the user to run, or run via the
   session rename mechanism if available.)

## Output

End with a short summary:
- ✅ Comments resolved (count) / ⚠️ left open (list with reason)
- ✅ Reviewers requested (handles) / skipped (author)
- ✅ Renamed to `<TICKET>`

## Gotchas

- **Never merge.** Global rule: agents create/push/open PRs and request review only — the
  user always performs the final merge. No `gh pr merge`.
- **Resolve only what you addressed** — the user has corrected this behaviour before.
- **Self-review is rejected** — filter the author out of the reviewer list.
- **Copilot review comments** appear as review threads from the `copilot-pull-request-reviewer`
  bot; treat them like any other unresolved thread.

## Progressive loading

📖 **DETAIL.md** — GraphQL snippets for listing unresolved threads and resolving them,
plus reviewer-not-collaborator handling.

```bash
cat ~/.copilot/skills/pr-finish/DETAIL.md
```
