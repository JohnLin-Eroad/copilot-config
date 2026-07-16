# EROAD Engagement Wrap-Up — John Lin

> Prepared: 2026-07-16 · Departing engineer's final handover note

---

## 1. Stat Summary

| Metric | Count | Notes |
|---|---|---|
| **Jira tickets completed** | 98 | Assigned to me, resolved (status category = Done) |
| **Story points completed** | 140 | Across 64 pointed tickets (34 Tasks/CAB Requests aren't pointed) |
| **Jira projects touched** | 6 | DRP (46), GVC (35), PEC (11), CAB (2), RUC (3), ELD (1) |
| **Commits authored** | 1,007 | Across the `eroad` GitHub org |
| **Pull requests merged** | 457 | |
| **Pull requests opened (total)** | 522 | 457 merged · 56 closed unmerged · 9 still open |
| **Code reviews given** | 451 | PRs reviewed for teammates |
| **Services/repos worked on** | 23 | See breakdown below |
| **Engagement span** | Feb 2025 – Jul 2026 | ~17 months, based on first/last merged PR |

**Top services by merged PRs:**

| Service | Merged PRs |
|---|---|
| replay-service | 84 |
| dashcam-video-platform | 72 |
| media-service | 71 |
| react-native-ui-components | 42 |
| inspect-app | 34 |
| device-integrations | 26 |
| support-scripts | 23 |
| maintenance | 21 |
| inspection | 19 |
| depot-configuration | 16 |
| young-hackathon2026 | 11 |
| timely-service | 8 |
| others (11 repos) | ≤6 each |

---

## 2. Main Learnings

### Data Validation & Bulk Operations
- **`findByIdIn(ids)` silently drops missing IDs.** JPA bulk lookups return only matched rows with no signal that some requested IDs didn't exist. Always validate via **set-difference** (found vs. requested) before mutating, and return `400` listing the missing IDs — not a silent `200`. (media-service, DRP-380/381)
- **Null/empty-list validation and existence validation are separate concerns** — handle both, in separate guards, both are needed for correct bulk-endpoint behaviour.
- **Null-guard ordering matters.** When a mapper/factory can return `null`, do the null check *before* any mutation on the result — not after. A `setX()` call before the guard causes an NPE on the null-return path. Easy to miss in review; worth a specific code-review heuristic.
- **Mockito defaults `Map` returns to an empty Map, not `null`.** Tests relying on downstream enrichment from a mocked map lookup can silently pass without ever asserting the enriched fields — always add explicit assertions for fields derived from map lookups.

### Cross-Service & Permission Design
- **Keep resolver services "dumb."** When one service resolves IDs on behalf of another (e.g., media-service resolving event IDs for replay-service), the resolver should carry zero auth/org logic. The **consuming** service enforces permissions on the resolved IDs using its own existing helpers. Avoids duplicating auth logic and coupling two services' security models together. (DRP-383)
- **Insufficient permission → 401, not 403**, consistently across dismiss/restore/undo endpoints.
- **Resolver wrappers must return empty collections, not `null`**, when upstream has nothing — protects every call site transitively without scattering null checks through the codebase.

### API & Contract Design
- **Prefer one unified response shape over ad-hoc scalar fields.** Replacing scattered `dismissedBy`/`dismissedDate` fields with a single `UserFeedbackResponse { commandId, events }` shape made the contract predictable across dismiss/restore/undo. (DRP-387)
- **Add canonical fields to the shared schema, not per-endpoint.** `EventDetails.lastFeedbackAction` became the one source of truth read by multiple consumers (getEventDetails, requestEvent v1/v2, requestHighResolutionEvent) rather than duplicating logic per endpoint.
- **"Undo" reverts to the pre-command state, not to "not dismissed."** Undoing a restore (or undoing a dismiss that was already dismissed) can legitimately produce `dismissed:true` again — that's correct semantics, not a bug. Audit fields like `lastDismissed*` should be gated by the **operation performed**, not by the resulting state.
- **TTL guards must fire before any mutation.** Undo commands expiring 15 minutes after being performed must be rejected with zero DB side effects — verified via dedicated tests for both expired and non-expired paths. (DRP-389)

### Testing & Build Gotchas
- **JUnit `@Nested` classes cause a false-negative in the Surefire summary** — the outer report can show "Tests run: 0" even when the nested class ran and passed everything. Always check the nested-class's own report file, don't trust the aggregate line.
- **`local-dev/start.sh` intentionally comments out `mvn clean install`** for faster restart loops — meaning after any rebase, you must manually rebuild (`mvn clean install -DskipTests`) or Docker silently runs a stale jar.
- **Per-service Java version pinning is real** — e.g. replay-service needs Java 17 via `sdkman` and a specific `mvn` binary path; mixing versions produces confusing build errors that look unrelated to the actual cause.
- **swagger-codegen DTOs need a recompile after schema edits.** Editing `replay-service-api.json` doesn't make the new generated DTO class available until `mvn -pl replay-service-api -am compile` is run.
- **Local audit-logged endpoints need `X-Forwarded-For` set manually.** Endpoints that push audit logs require a client IP; in production the ALB injects this header, but local `.http` test files need it added explicitly or you get a confusing 500.

### Process & Tooling
- **Jira ADF custom fields are full-replace, not merge.** Any update to an ADF-based custom field (e.g. test notes) must include the complete document — a partial update silently wipes the rest.
- **GitHub's Copilot code-review bot isn't enabled in the EROAD org** — only `copilot-swe-agent` shows up as a suggested reviewer, and it can't actually be requested. Request human reviewers instead.
- **The DRP Jira workflow has a fixed transition path**: Ready → In Progress → Code Review → Ready For Testing → In Testing → PO Sign-Off → Ready For Release → Done — useful to have the transition IDs memorized/scripted rather than looked up each time.

---

*Generated 2026-07-16 from Jira (assignee = me, resolved) and GitHub (`eroad` org, commits/PRs/reviews authored or reviewed by me).*
