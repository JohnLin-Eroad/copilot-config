# PR Finish — Detail

GraphQL snippets for review-thread handling. Requires `gh auth` with `repo` scope.

## List unresolved review threads

```bash
OWNER=eroad
REPO=device-integrations   # change to current repo
NUM=789                    # PR number

rtk gh api graphql -f query='
query($owner:String!, $repo:String!, $num:Int!) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$num) {
      reviewThreads(first:100) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first:1) {
            nodes { author { login } body }
          }
        }
      }
    }
  }
}' -F owner="$OWNER" -F repo="$REPO" -F num="$NUM" \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[]
        | select(.isResolved==false)
        | {id, path, line, author: .comments.nodes[0].author.login,
           body: (.comments.nodes[0].body[0:120])}'
```

This prints each unresolved thread's node `id` (e.g. `PRRT_kw...`), file, line, author,
and a body preview. Copilot review comments come from author
`copilot-pull-request-reviewer` (or similar bot login).

## Resolve a thread (only after addressing it)

```bash
THREAD_ID=PRRT_kwDO...   # id from the query above

rtk gh api graphql -f query='
mutation($id:ID!) {
  resolveReviewThread(input:{threadId:$id}) {
    thread { id isResolved }
  }
}' -F id="$THREAD_ID"
```

Resolve threads one-by-one as you confirm each is addressed. Do **not** loop-resolve all
threads blindly — leave anything unaddressed open.

## Reviewer not a collaborator

**Important:** `gh pr edit --add-reviewer` exits 0 even when GitHub silently drops a
handle (e.g. the user isn't a collaborator on the repo, or is the PR author). A zero exit
code does **not** mean the reviewer was added. Always verify afterwards.

1. Add reviewers individually so one bad handle doesn't block the rest:
   ```bash
   for r in naveednizar atienzajazz almirjamee; do
     rtk gh pr edit "$NUM" --add-reviewer "$r" 2>/dev/null || true
   done
   ```
2. **Verify what actually attached** (source of truth — not the exit code):
   ```bash
   rtk gh pr view "$NUM" --json reviewRequests --jq '[.reviewRequests[].login]'
   ```
3. Report any requested handle missing from that list as skipped, with the likely reason
   (not a collaborator on this repo / is the author). On EROAD repos all three are
   collaborators, so the list should contain all non-author handles.

## Deriving the ticket

```bash
# From branch name
BR=$(rtk git rev-parse --abbrev-ref HEAD)
echo "$BR" | grep -oiE '(VSF|DRP|NONE)-[0-9A-Za-z]+' | head -1
```

Fallback: extract from the PR title if the branch is non-standard.
