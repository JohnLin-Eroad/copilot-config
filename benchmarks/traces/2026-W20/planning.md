# Trace: planning — 2026-W20

## Metadata
- Prompt ID: P4-audit-trail
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-05-10T22:22:29Z
- Duration: 233.7s

## Prompt Sent
Design a compliance event audit trail for the sovereign platform.

Requirements:
- All compliance events (driving hours, vehicle inspections, speed violations) must be logged
- 7-year retention for regulatory compliance (NZ Transport Agency requirements)
- Tamper-proof: once written, entries cannot be modified or deleted
- Queryable: fleet managers can search by date range, driver, vehicle, event type
- Must support export to CSV/PDF for regulatory submissions

Produce a detailed implementation plan with data model, storage strategy, and
tamper-proofing mechanism.

## Raw Output
✗ Search (glob)
  │ "docs/adr/*.md"
  └ Tool 'glob' does not exist.

✗ Search (glob)
  │ "api/domain/src/main/java/**/*.java"
  └ Tool 'glob' does not exist.

I only have delegation tools available. I'll have a general-purpose agent check existing ADR numbering and write the file, while I produce the design here.

● General-purpose(claude-haiku-4.5) Write compliance audit ADR
  │ Create ADR-0004-compliance-event-audit-trail.md +238
  │   └ docs/adr/ADR-0004-compliance-event-audit-trail.md
  └ Verify ADR file creation and get file size (shell)
      │ ls -lh ~/sovereign/docs/adr/ADR-0004-compliance-event-audit-trail.md && wc
      │ -c ~/sovereign/docs/adr/ADR-0004-compliance-event-audit-trail.md
      └ 3 lines...

ADR written: `~/sovereign/docs/adr/ADR-0004-compliance-event-audit-trail.md`.

## Summary — Compliance Event Audit Trail (HIGH blast radius, Status: Proposed)

**Domain model** (`api/domain`, pure Java): immutable `ComplianceEvent` aggregate with provenance, payload + schema version, severity, and `IntegrityStamp`. Ports for repo, signer, chain service, exporter.

**Storage — three layers:**
1. **PostgreSQL hot store** (24 mo): `compliance_audit.event` partitioned monthly on `occurred_at`. App role has only `SELECT, INSERT`; DB triggers reject `UPDATE`/`DELETE`; `pgaudit` on DDL.
2. **S3 Object Lock (Compliance mode), 7-year retention** for sealed monthly Parquet partitions — survives root-account compromise. Lifecycle to Glacier Deep Archive at month 13. Athena federated query for cold reads.
3. **Daily anchor** in a separate table + S3 + optional RFC 3161 timestamping authority.

**Tamper-proofing — defence in depth:**
- **Per-fleet hash chain**: `row_hash[N] = SHA-256(row_hash[N-1] ‖ JCS(event))`, serialised via `fleet_chain_head` row lock.
- **AWS KMS asymmetric (ECDSA P-256) signature** over each `row_hash`; old keys verify-only, never deleted.
- **Daily anchor** signed and locked — makes retroactive tampering O(1) detectable.
- Verification API + nightly job alerts on any chain break.

**Ingestion**: SQS FIFO queue keyed by `fleetId`, idempotent on `(sourceSystem, sourceEventId)`, DLQ after 5 failures.

**Query/Export**: REST endpoints with RBAC (`FLEET_MANAGER`/`COMPLIANCE_AUDITOR`/`REGULATOR_EXPORT`), keyset pagination. Async CSV (streamed) and PDF (OpenPDF) exports with signed manifest (query, row count, file SHA-256, KMS key ID) and 1-hour pre-signed URL.

**Key risks called out**: PII vs. right-to-erasure conflict (needs Legal sign-off — NZTA retention overrides), Object Lock irreversibility (mandates strict pre-write validation), KMS latency (mitigated by batched signing), clock skew (chain orders by server `recorded_at`).

**Alternatives rejected**: QLDB (EOL July 2025), Postgres-only (no insider-threat defence), blockchain (complexity > benefit), per-service tables (status quo problem), WORM NAS (no geo-redundancy), CloudTrail (wrong tool).

**Implementation**: 10 work packages, ~28 engineer-days. Critical path WP1→WP6. Pre-acceptance gates: Legal, Security, cost model, migration-validator PASS, dual-critique skill (mandatory at HIGH blast radius).

**Recommended next step**: invoke the `dual-critique` skill before moving from Proposed → Accepted, then hand off WP1+WP2 to the tech-lead for decomposition.

## Grading Reasoning
The output is technically strong on tamper-proof design and storage strategy, with decent architectural intent. It falls short on explicit phased implementation ordering and measurable acceptance criteria, preventing an excellent score.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Domain understanding | 15% | 88 | Strong domain framing with explicit immutable model and integrity invariants: "immutable `ComplianceEvent` aggregate ... and `IntegrityStamp`" and tamper controls like "per-fleet hash chain" + signatures. It does not explicitly define a `ComplianceEventType` enum or clearly map the three required event classes in the model. |
| Hexagonal architecture | 20% | 82 | Good separation is stated: "Domain model (`api/domain`, pure Java)" with "Ports for repo, signer, chain service, exporter," and infra concerns in storage/export sections. However, application-layer use cases/orchestration are not concretely specified (e.g., explicit `AuditUseCase` flow). |
| Blast radius assessment | 15% | 68 | It flags risk areas and calls this "HIGH blast radius," with issues like "Object Lock irreversibility," "KMS latency," and legal/PII conflict. But storage cost and migration-from-existing-logs analysis are not detailed, and query-at-scale impact is only lightly addressed. |
| Edge cases | 15% | 74 | Multiple edge conditions are covered: "clock skew," legal erasure conflict, object-lock irreversibility, and ingestion idempotency/DLQ. Gaps remain for explicit hash-chain recovery procedures, timezone handling policy, and retention-boundary behavior. |
| Dependency ordering | 15% | 58 | There is some sequencing signal ("10 work packages... Critical path WP1→WP6"), but the output does not clearly present the requested phased dependency chain such as domain → storage → indexing → query API → export → migration. |
| Acceptance criteria | 20% | 57 | The plan implies goals (append-only via "triggers reject `UPDATE`/`DELETE`", "7-year retention", query/export features), but lacks explicit measurable acceptance thresholds (e.g., query latency targets, export SLA, integrity verification pass criteria). |

## Overall Score: 71.0/100
