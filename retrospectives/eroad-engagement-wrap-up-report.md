# EROAD Engagement Wrap-Up Report — John Lin

> **Prepared by:** John Lin  
> **Date:** 2026-07-16  
> **Engagement span:** ~August 2025 – July 2026 (≈11 months)  
> **Brain vault:** 738 memories across repo / project / domain / global / tooling layers  

---

## 1. Executive Summary

This report captures everything learned during an approximately 11-month AI-assisted engineering engagement with EROAD's digital transformation programme. The work spanned two distinct tracks running in parallel:

**Track 1 — EROAD Production Work (DRP tickets):** Feature delivery and bug fixes across existing Java microservices, primarily `media-service` and `replay-service` in the Safety / Video Safety domain. Work items ranged from input validation hardening (DRP-380, DRP-381) and user-feedback metadata features (DRP-387, DRP-374) to TTL-enforced undo (DRP-389), permission-checking for undo (DRP-383), and feedback refactoring and cleanup (DRP-416). All work went through EROAD's DRP Jira project with the standard transition workflow (Ready → In Progress → Code Review → Ready For Testing → Done).

**Track 2 — Sovereign Platform Build:** Design and implementation of Sovereign, EROAD's internal AI-governed transformation platform (Java 21 / Spring Boot 3 + Next.js 15). Work included the MVP completion (12 work items across domain, infrastructure, worker, and frontend layers — 2026-04-19), a comprehensive security review of REST controllers (2026-04-23), a test coverage audit (2026-04-28), a multi-tenancy architecture decision (ADR-0003, 2026-06-15), and the Sovereign V2 specification for the planned cloud-native rebuild.

The engagement produced 738 brain memories, 8 architecture/decision nodes, 7 domain model nodes, and a rich set of project-level learnings across the Safety domain and Sovereign platform. The earliest datable session is August 2025 (DRP-389 TTL undo, PR #2032 on media-service); the latest is July 2026 (ADR-0003 consolidation, DRP-416 cleanup).

---

## 2. Platform & Architecture Overview

### 2.1 EROAD's Existing Platform

EROAD is a fleet telematics SaaS operating across **APAC** (NZ, Australia) and **North America** (USA, Canada). The platform is multi-cloud:

| Cloud | Product | Key Infrastructure |
|-------|---------|-------------------|
| **AWS** | MyEROAD | EKS microservices, legacy GlassFish on EC2 ASG, Lambda, Kinesis, DynamoDB, RDS PostgreSQL |
| **Azure** | Coretex 360 | Container Apps, Azure SQL, Service Bus |

The architecture is event-driven. In-vehicle hardware (CoreHub Gen3 Android device, eBox Gen2 legacy tracker) transmits ATOM messages over TCP to `espserver-service`, which flows into `central-service` (the Java monolith), which fans out via Kinesis streams to EKS microservices and Lambda functions. Both product lines are converging toward **EROAD One** on Azure Landing Zones.

**Organisational structure:** Tribes include SAFETY, SUSTAIN, DEVICES, COMPLIANCE, COLD CHAIN, SHARED PLATFORM, TAX, and DIME.

### 2.2 Sovereign — The Transformation Platform

Sovereign is EROAD's internal AI-governed execution platform. It is not merely a code-generation tool — it governs how transformation work is defined, decomposed, executed, reviewed, and delivered.

**Three conceptual layers:**
- **Governance layer:** Domain registry, operating modes, quality baselines, GovernanceEngine policy rules (YAML-driven), stop/rollback criteria
- **Orchestration layer:** Jira-driven pipelines, agent coordination, preflight gates, slice execution, rework cycles
- **Delivery layer:** AI code generation, GitHub PR creation, validation, Studio agentic execution

**Sovereign builds toward Vanguard** — EROAD's next-gen enterprise platform. Sovereign is the construction tool; Vanguard is what it builds.

**Current tech stack (Java/Spring Boot V1):**
- Language: Java 21 | Framework: Spring Boot 3.x (API), Next.js 15 (frontend)
- Database: PostgreSQL with Flyway migrations | Messaging: AWS SQS (agent job worker)
- Build: Maven multi-module (domain / application / infrastructure / web / worker)

**Planned V2 stack** (not yet built): MongoDB (Cosmos DB MongoDB API), Azure Container Apps, Kong Gateway, Azure Service Bus, Redis cache, Terraform IaC, Auth0 + Entra, OpenTelemetry + Grafana, Azure Front Door.

### 2.3 Hexagonal Architecture (Sovereign)

```
domain <- application <- infrastructure <- web
```

| Layer | Maven module | Package prefix | Responsibility |
|-------|-------------|----------------|----------------|
| Domain | api/domain | com.sovereign.domain | Pure Java records, value objects, domain events. Zero Spring/JPA annotations. |
| Application | api/application | com.sovereign.application | Use cases, repository port interfaces |
| Infrastructure | api/infrastructure | com.sovereign.infrastructure | JPA adapters, Spring beans, AI provider clients, SQS |
| Web | api/web | com.sovereign.web | REST controllers, DTOs, request/response mapping |
| Worker | worker/ | com.sovereign.worker | Standalone SQS-backed agent job processor |

**Enforced rules:**
- Domain entities are Java **records** — immutable, no getter boilerplate
- NO `@Entity`, `@Table`, or Spring annotations anywhere in the domain layer
- Repository port interfaces live in **application**, not domain
- Timestamps always `java.time.Instant` — never `LocalDateTime` or `ZonedDateTime`
- Worker is a standalone Spring Boot module; must `mvn install -DskipTests` the api first so worker resolves sovereign-domain/application/infrastructure from local Maven repo
- New domain aggregates use `sealed interface` in `com.sovereign.domain.<bc>.events` for typed domain events

### 2.4 Multi-Tenancy Architecture (ADR-0003)

See Sections 8 and 10 for full detail. The core decision: **shared-database multi-tenancy using PostgreSQL RLS as the only real isolation layer**, with Hibernate @Filter and JDBC SET LOCAL as defence-in-depth convenience layers. Status: **Approve-with-gates** — 7 mandatory pre-flight gates block Phase 1.

---

## 3. Domain Model Overview

The 7 core EROAD domain entities, as documented in the brain vault:

| Entity | Internal Term | Key Fields | Owning Services |
|--------|--------------|-----------|-----------------|
| **Vehicle** | Machine | id (uuid), organisation_id, common_identifier (plate/tag), name, active (soft delete), start_date / end_date | central-service (master), myeroad-machine-service, asset-management-service |
| **Driver** | Driver | id, organisation_id, username, common_identifier, firstname, lastname, email, mobile_number, active, login_attempts, locked_start | myeroad-driver-service, replay-service (auth scoping), legacy driver |
| **Fleet** | Fleet | id, organisation_id, name, version, last_modified | replay-service (fleet auth), myeroad-geofence-service, myeroad-machine-service |
| **Event** | Event | id, machine_id, driver_id, organisation_id, trip_id, event_type, event_time, lat/lng, speed, status, discarded, discarded_by, discarded_at | myeroad-event-service, replay-service, historical-event-api |
| **Device** | Device | id, serial_number, device_type, firmware_version, machine_id (nullable), organisation_id, provisioned_at, last_seen, status | device-provisioning, asset-devices-device-telemetry, central-service |
| **Trip** | Trip | id, machine_id, driver_id (nullable), organisation_id, start_time, end_time, distance (km), start_location, end_location, status | myeroad-event-service, historical-event-api, replay-service |
| **Organisation** | Organisation | id, common_identifier, name, active, locale, timezone, address_*, ruc_customer_number (NZ), us_dot_number (US), hos_cycle (US ELD) | central-service (authoritative), all services via organisationId scoping |

**Key relationships:**
- Organisation is the top-level tenant — every other entity belongs to exactly one org
- Fleet is the access-control mechanism — users see only assets in their assigned fleets
- Event is the core unit of the safety/coaching workflow; always soft-deleted (never hard-deleted)
- Machine and Driver link via the trip — driver who was logged on at trip start

**Sovereign domain entities (new platform):**
- `Driver` — Java record: `UUID id`, `String name`, `Instant lastSeenAt`; use `withLastSeenAt(Instant)` wither for immutable updates
- `TripSummary` — read model projection (mapper + DTO under `api/application/trip`)
- `Fleet` aggregate — timestamps set on creation/rehydration, immutable across state transitions

---

## 4. Services Inventory

### 4.1 Sovereign (New Platform)

| Module | Description |
|--------|-------------|
| sovereign api (5 modules) | Java 21 Spring Boot 3 AI transformation platform with hexagonal architecture |
| sovereign worker | SQS-backed agent job processor with idempotency table (V4 migration) |
| sovereign web | Next.js 15 frontend — governance dashboard, Studio AI chat, domain views |

### 4.2 Safety Domain

| Service | Tribe | Description |
|---------|-------|-------------|
| media-service | SAFETY | Core dashcam video platform — 4-stage Lambda ingestion pipeline (Streamax), Spring Boot REST API on EKS, CloudFront delivery, ADAS detection, 15-min undo TTL, nightly retention deletion job (Java 21) |
| replay-service | SUSTAIN | Video event replay — event review, dismiss/restore/undo feedback, notes, documents, fleet authorisation layer (Java 17, EKS) |
| myeroad-event-service | SUSTAIN | Event creation and querying for the MyEROAD portal |
| historical-event-api | SUSTAIN | Long-term event history queries (DynamoDB-backed) |
| dashcam-video-platform | SAFETY | Streamax device webhook ingestion; feeds media-service Lambda pipeline |
| data-upload-service | SAFETY | MP4 to HLS conversion; registers converted videos with media-service |
| data-retrieval-service | SAFETY | Creates AWS IoT jobs for on-demand Clarity Edge video retrieval |
| event-manager | SUSTAIN | Consumes harsh-driving EboxEvents from Kinesis; dispatches video-clip requests |
| streamax-api-adapter | SAFETY | Adapter for Streamax FTCloud file downloads (Stage 3 Lambda dependency) |

### 4.3 Identity & Auth

| Service | Description |
|---------|-------------|
| auth-service | Primary auth — wraps Cognito with EROAD org-aware business logic; issues JWTs with userId/orgId/roles/authorisedOrgIds |
| central-service | Master machine/org registry; authoritative source for fleet/org hierarchy; 34 downstream dependents |
| user-service | User identity and org membership; 34 downstream dependents |
| myeroad-custom-authorizer | Lambda JWKS-based JWT validator for API Gateway |
| eroad-sso-service | SSO token exchange |
| myeroad-idp-service | Identity provider integration |
| myeroad-impersonation-service | Admin impersonation flows |
| session-service | Session state management |

### 4.4 Driver & HOS/ELD

| Service | Description |
|---------|-------------|
| myeroad-driver-service | CRUD, licence/cert management, HOS — orchestration over central-service + legacy driver service |
| driver (legacy) | Legacy driver record persistence being migrated |
| drivernz-service | NZ iOS/Android logbook app backend |
| myeroad-eld-service | ELD HOS ruleset + carrier configuration |
| eld (legacy) | ELD compliance legacy service (40 endpoints, GlassFish ASG) |
| hours-of-service | Country-specific HOS service |
| eroad-hos-rulekit | Encapsulated HOS rule logic library (separate from HOS service) |
| logbook / logbook-nz / myeroad-logbook-service | Log editing and NZ RUC hours tracking |

### 4.5 Vehicle, Asset & Device

| Service | Description |
|---------|-------------|
| asset-management-service | Asset lifecycle management |
| asset-machines-machine-entities/telemetry | Machine entity management and real-time telemetry |
| asset-devices-device-entities/telemetry | Device entity management and real-time telemetry |
| asset-trailers-trailer-entities/telemetry | Trailer management |
| myeroad-machine-service | Machine management for MyEROAD |
| vehicle-service | Vehicle management |
| device-provisioning | Device registration + assignment to machines |
| iot-job-manager | Firmware OTA updates for CoreHub |
| corehub-* (6 repos) | CoreHub Gen3 Android device firmware/app/kernel/scripts/sensors/tools |

### 4.6 Compliance & Tax

| Service | Description |
|---------|-------------|
| rucus-service | NZ NZTA RUCUS mandatory submission — GPS distance vs RUC declaration cross-check |
| eruc | eRUC distance licence data |
| mass-management-service + ui | Heavy vehicle mass management |
| permit-management-service | Oversize/overmass permit management |
| dvir-service / dvir-management-service | Driver Vehicle Inspection Reports (NZ and NA variants) |
| inspection-service / inspect-app | Vehicle inspection management and mobile app |
| ftc-service | Fuel Tax Credits (19 endpoints, ASG) |
| apac-tax / na-tax / global-tax | Tax calculation services |

### 4.7 Telematics & Ingestion

| Service | Description |
|---------|-------------|
| espserver-service | ATOM TCP listener — primary device communicator (GlassFish ASG) |
| central-service | Core event ingestion, RabbitMQ + Kinesis producer (GlassFish ASG) |
| central-event-persister | Persists device telemetry from Kinesis stream |
| central-event-forwarder | Lambda fan-out from Kinesis |
| customer-event-forwarder | Lambda → external Kinesis for customer integrations |
| event-api | Event querying, DynamoDB-backed, Kinesis-triggered |
| esp-event-adapter / esp-websocket-adapter | ESP protocol adapters |
| generic-event-adapter / generic-sensor-event-adapter | Generic device protocol adapters |
| calamp-gateway | CalAmp device gateway |

### 4.8 Data Platform & Analytics

| Service | Description |
|---------|-------------|
| data-platform (+ 13 submodules) | DBT, Glue, orchestration, raw data, Snowflake integrations, reverse ETL |
| analytics-service / analytics-platform | Analytics APIs |
| eroad-data-warehouse | Central data warehouse |
| insights-api | GraphQL insights API |
| trip-datalake | Trip data lake |

### 4.9 Geospatial

| Service | Description |
|---------|-------------|
| geographic / geographic-platform | Address, road name, speed zone resolution |
| geofence | Geofence management |
| location-places-* / location-regions-* | Places, POI, geofence boundary services |
| geospatial-assettracking-* | Real-time vehicle trace and point-on-map |

### 4.10 Mobile & Web Frontend

| Service | Description |
|---------|-------------|
| eroad-android-app / eroad-ios-app | Driver mobile apps (React Native) |
| portal | MyEROAD Spring MVC web UI (legacy GlassFish ASG) |
| myeroad-portal / myeroad-portal-fork | Modernised MyEROAD portal |
| mobile-api / mobile-backend | Mobile API layer |

### 4.11 Infrastructure & DevOps

| Service | Description |
|---------|-------------|
| continuous-delivery / continuous-delivery-aws | CI/CD pipeline definitions (Concourse + GitHub Actions) |
| shared-terraform-modules / terraform-modules | IaC modules |
| container-base-images | Base Docker images |
| grafana-cloud-platform | Observability platform |
| aws-cloud-accounts / aws-networking / aws-security | AWS infrastructure management |
| github-actions-pipelines / github-actions-cli | GitHub Actions workflow definitions |

> **Note:** The "01 - Services" brain vault contains 288 service nodes and the "Brain" vault contains 284 entity-type memories. The above list deduplicates both and groups by logical domain. Services not listed (approximately 80 additional entries) are either legacy/deprecated, supporting utilities, or had minimal direct engagement during this period.

---

## 5. Security Learnings & Findings

### 5.1 Sovereign Platform — Open P0 Security Issues

These were identified in the 2026-04-28 audit and remain **unresolved** as of the last session:

| # | Location | Finding | Severity | Required Fix |
|---|---------|---------|---------|-------------|
| 1 | CatalogController.scanLocalRepos() | User-controlled path param passed directly to ProcessBuilder — **command injection** | CRITICAL | Add allowlist validator; reject any path not on allowlist before ProcessBuilder call |
| 2 | StudioController.chat() | Full request history appended to every LLM call with no token/length guard — runaway costs + prompt injection | HIGH | Add maxHistoryTokens config; truncate/sliding-window history |
| 3 | CatalogAdapter | proc.waitFor() called with no timeout — indefinite thread block | HIGH | Use proc.waitFor(30, TimeUnit.SECONDS); handle false return (timeout) |
| 4 | CopilotChatService | Returns HTTP 200 on upstream 401 — auth failures masked from monitoring | MEDIUM | Propagate upstream HTTP status; do not wrap in 200 with success:false body |

### 5.2 ADR-001 — Auth Security Baseline for Sovereign

**Context:** Sovereign had NO Spring Security dependency and NO JWT library as of 2026-04-23. Every REST controller shipped with CRITICAL auth findings.

**Mandated requirements for all new Sovereign controllers:**
1. Add `spring-boot-starter-oauth2-resource-server` to pom.xml
2. Configure `spring.security.oauth2.resourceserver.jwt.jwk-set-uri` → AWS Cognito JWKS endpoint
3. Annotate SecurityConfig with `@EnableMethodSecurity`
4. All controller methods: `@PreAuthorize("isAuthenticated()")` at minimum
5. Every query extracts `organisationId` from JWT claim — never accept org from request body or path param alone without JWT cross-check
6. Cross-org access returns **404, NOT 403** — existence non-disclosure is mandatory
7. Never bind JPA entity classes as request bodies — DTOs only (prevents mass assignment)
8. Rate limiting: bucket4j token-bucket filter at controller layer, not business logic
9. Error envelope: `{error, code, correlationId}` only — no stack traces, no internal IDs

**Reference implementation:** VehicleController pattern (produced 2026-04-23). Includes: VehicleController.java, VehicleRequestDto.java, VehicleResponseDto.java, VehicleService.java, VehicleRepository.java, GlobalExceptionHandler.java, SecurityConfig.java, BucketRateLimitFilter.java.

**Security test scenarios (6 required per controller):**
1. Unauthenticated → 401
2. Authenticated, wrong org → 404
3. Authenticated, correct org → 200
4. Mass assignment attempt → org_id unchanged
5. Rate limit exceeded → 429
6. Soft-delete idempotency → 204 on repeat call

### 5.3 Multi-Tenancy Security (ADR-0003)

**PostgreSQL RLS — Known Bypass Vectors (all HIGH severity):**

| Bypass Vector | Risk | Mitigation |
|--------------|------|------------|
| SECURITY DEFINER functions | Run as function owner (often superuser), bypass RLS entirely | Audit all; add explicit `AND org_id = current_setting('app.current_tenant_id')` filter |
| Missing FORCE RLS on owner tables | Table owners bypass RLS by default | `ALTER TABLE <t> FORCE ROW LEVEL SECURITY` on every tenant table |
| Superuser connection pool | All queries bypass RLS | App pool role must NOT be superuser |
| Flyway migrations as superuser | DML in migrations bypasses RLS | Run data migrations as app role, not schema owner |
| Read replicas without RLS | Policies may not replicate | Verify RLS policies exist on all replicas |
| Direct DB access (psql/pgAdmin) | Ad-hoc bypass | Require restricted role for all human access |

**Hibernate @Filter gotcha (HIGH severity — silent data leak):**
- @Filter requires explicit `session.enableFilter(...)` activation per session
- Bypassed by: native queries (`nativeQuery=true`), `EntityManager.find()`, Criteria API, CompletableFuture/reactive pipelines
- Any new repository method added without awareness silently leaks cross-tenant data
- Mental model: @Filter = convenience hint only; PostgreSQL RLS = the ONLY enforced isolation boundary

**JDBC SET LOCAL gotcha (HIGH severity):**
- `SET LOCAL app.current_tenant_id = ?` only persists for the current transaction
- ALL connection-checkout paths must set it: HTTP request threads, @Scheduled jobs, SQS consumers, Flyway data migrations, Actuator health endpoints, @Async methods (tenant context does NOT automatically propagate from parent thread), CompletableFuture pipelines, admin/backoffice endpoints, ApplicationEvent listeners

**Cross-tenant leak test harness (CI gate pattern):**
```java
@Test void noOrgACrossLeak() {
    TenantContext.set(ORG_A_ID);
    assertThat(repository.findAll()).allMatch(e -> ORG_A_ID.equals(e.getOrgId()));
}
@Test void nullContextReturnsEmpty() {
    TenantContext.clear();
    assertThatThrownBy(() -> repository.findAll()).isInstanceOf(DataAccessException.class);
}
```
Must cover every repository method, every native query, every @Async/@Scheduled path, every SQS consumer that reads DB. Must be a required CI check — failure blocks merge.

### 5.4 EROAD Existing Services — Security Patterns

- **404-not-403 non-disclosure:** Cross-org access returns 404 in both Sovereign (ADR-001) and EROAD services (DRP-383 confirmed in replay-service). The existence of another org's resource must not be disclosed.
- **DTO-only binding rule:** Never bind JPA entities directly as request bodies (mass assignment/BOLA risk). Confirmed in media-service, replay-service, Sovereign.
- **Bulk-ID validation before mutation:** `findByIdIn` silently omits non-matching IDs — always validate completeness via set-difference before any state change. Throw 400 (not 200 or 404) if any IDs missing. (DRP-381)
- **Agent PR governance (global rule):** AI agents may create branches, push, open PRs, and request reviewers — but must NEVER merge. The user always performs the final merge. (Added 2026-06-29.)

---

## 6. Engineering Patterns & Gotchas

### 6.1 Spring / Java Patterns

| Pattern | Detail | Source |
|---------|--------|--------|
| @Async AOP proxy | Methods must be protected (not private) for AOP proxy to intercept. PipelineController.runAgentAsync() replaced raw new Thread(). | learnings.md 2026-04-17 |
| SQS idempotency | idempotencyKey = stable logical identity; jobId = SQS message ID, changes on re-delivery. On failure: do NOT delete message — SQS re-delivers up to maxReceiveCount=3 then DLQ. | learnings.md 2026-04-17 |
| CORS wildcard | Use allowedOriginPatterns (not allowedOrigins) for wildcard support. allowedOrigins breaks with allowCredentials=true. Configured via sovereign.cors.allowed-origins property. | learnings.md 2026-04-17 |
| Governance rules safe-fail | GovernanceEngine.isEnabled() defaults to true if rule ID not found — prevents missing YAML silently disabling security checks. | learnings.md 2026-04-17 |
| LLM cost tracking | (inputTokens/1000 * inputRate) + (outputTokens/1000 * outputRate). Falls back to chars/4 when API returns no token counts. Stored in llm_usage_records.estimated_cost_usd. Rates in ai-models.json. | learnings.md 2026-04-17 |
| Domain events sealed interfaces | New domain aggregates carry typed domain events via sealed interfaces in com.sovereign.domain.<bc>.events | learnings.md 2026-05-11 |
| Fleet aggregate timestamps | Fleet timestamps are immutable metadata — set on creation/rehydration, preserved across all state transitions. | learnings.md 2026-06-15 |
| Driver as Java record | Driver is a Java record with withLastSeenAt(Instant) wither. Never modify fields directly. Already implemented as of 2026-04-28. | learnings.md 2026-05-19 |
| @Scheduled fixedRateString | Values are milliseconds. getPollPeriodInMilliseconds() must return seconds * 1000. Easy to over-fire by 1000x. | DRP-416 session 2026-06-18 |
| SchedulerConfig profile | @Profile("!test") on SchedulerConfig means SPRING_PROFILES_ACTIVE=test disables all schedulers. Good for test isolation. | DRP-416 session 2026-06-18 |
| Native bulk DELETE cascades | Native SQL DELETE bypasses Hibernate cascade — relies entirely on DB FK ON DELETE CASCADE. Verify constraints exist in migrations before using bulk native DELETE. | DRP-416 session 2026-06-18 |
| EventFeedbackService extraction | Extracted from the 2500-line EventService monolith. Pattern: extract cohesive concern (dismiss/restore/undo/getFeedbackCommandEvents) into dedicated service with constructor injection. | DRP-416 |

### 6.2 Tooling & Build Gotchas

| Gotcha | Detail |
|--------|--------|
| Java 21 SDKMAN | Always run: source ~/.sdkman/bin/sdkman-init.sh && sdk use java 21.0.7-zulu before any mvn command. Without this: UnsupportedClassVersionError: Unsupported major.minor version 61. |
| Worker build order | Must mvn install -DskipTests the api first so worker resolves sovereign-domain/application/infrastructure from local Maven repo. |
| Maven test scoping | Run from /api with -pl domain,application -am. Using -pl api/domain from repo root fails reactor selection. Add -am when target module tests reference new classes in dependent modules. |
| JUnit @Nested surefire | @Nested classes generate separate surefire XML files. The outer class report shows Tests run: 0 — check nested-class XML files. Aggregate TEST-<RootTestClass>*.xml for full count. |
| replay-service startup | Takes ~133 seconds (JVM ~137s total). Normal — do not kill. Uses /opt/homebrew/bin/mvn (no ./mvnw). Uses Java 17 (sdk use java 17.0.16-zulu). |
| media-service stale jar | After any rebase: always run mvn clean install -DskipTests before starting local-dev. local-dev/start.sh has mvn clean install commented out intentionally. Stale jar causes startup failures on @PostConstruct. |
| Local dev remote RDS stash | Many EROAD Java repos have a git stash (stash@{0}) that patches the service to connect to remote test RDS. Apply: git stash apply stash@{0}. NEVER commit. Restore: git checkout -- . |
| replay-service surefire false-zero | MediaServiceTest runs under nested class — outer surefire report shows Tests run: 0. Check MediaServiceTest$GetDashcamChannels.txt for actual results. |
| Audit.java enum formatting | replay-service Audit.java is a Java enum. When adding a new constant: preceding constant must end with comma. Missing/extra commas = compile failure. |

### 6.3 Testing Patterns

| Pattern | Detail |
|---------|--------|
| Test framework | JUnit 5 + AssertJ. Always @Nested + @DisplayName + @ParameterizedTest. Never JUnit 4. |
| Gold standard | TripSummaryMapperTest (37 test cases, application layer) — use as template for mapper tests. |
| Domain testability | Domain layer (pure Java records, no Spring) — highest testability, zero Spring context needed. |
| Infrastructure tests | WireMock for HTTP adapters; Testcontainers for JPA repos. |
| Worker integration tests | Must use Testcontainers + LocalStack — NOT pre-running local infrastructure. |
| Frontend | Vitest + jsdom (NOT Jest — React 19 compat) + React Testing Library + MSW (works with raw fetch) + Playwright for E2E. |
| media-service exception style | Uses try/catch instead of assertThrows in EventServiceTest. Follow existing style. |
| Mockito Map default | Mockito returns empty Map (not null) for Map return types. Tests for NoteDTO enrichment can silently pass without asserting enriched fields — always add explicit field assertions. |
| Security test scenarios | 6 scenarios per controller: unauthenticated 401, wrong-org 404, correct-org 200, mass-assignment unchanged, rate-limit 429, soft-delete idempotency 204. |

---

## 7. Data & Domain Safety Learnings

### 7.1 Bulk ID Validation Pattern (from DRP-381, media-service)

**Problem:** `repository.findByIdIn(ids)` silently omits non-matching IDs. Pre-fix: `dismiss()` and `restore()` returned HTTP 200 even when all requested event IDs didn't exist.

**Correct pattern (validateAllExist helper):**
1. Build `foundIds` as a `Set<UUID>` from returned entities
2. Filter `requestedIds.stream().distinct()` for IDs not in `foundIds`
3. If any missing → throw `BAD_REQUEST` with the list of missing IDs explicitly
4. Only proceed with mutation if all IDs confirmed present — fail-fast, pre-mutation atomicity

**Why set-difference over size comparison:** Size comparison fails when requestedIds contains duplicates. Set-difference on distinct IDs handles this correctly and produces more descriptive error messages.

**Two separate concerns (DRP-380 + DRP-381):** Null/empty list validation and individual-ID existence validation must both be present. Neither alone is sufficient.

### 7.2 Cross-Service Permission Enforcement (from DRP-383, replay-service + media-service)

**Pattern:**
```
Step 1: resolver-service.getIds(commandId) → [id1, id2, ...]   // dumb, no auth/org logic
Step 2: consuming-service.checkPermissions(userId, [id1, id2, ...])  // 401 if insufficient
Step 3: consuming-service.mutate([id1, id2, ...])
```

**Anti-pattern:** Do NOT add permission logic to the resolver service — it creates coupling and duplicates auth logic that already exists in the consuming service.

**Null-safety corollary:** Resolver wrappers must return empty collections (not null) when upstream response is empty/null. Protects all call sites without defensive null checks throughout.

**Unauthorised response:** 401 UNAUTHORIZED (via userNotAuthorised()) — NOT 403. Matches dismiss/restore pattern.

### 7.3 media-service User Feedback Domain

**event_feedback_command schema (GOTCHA — PK is id, not command_id):**
- PK column is `id` — the undo endpoint receives a `commandId` parameter that maps directly to `event_feedback_command.id`
- `expired_at` default: `now() + interval '15 minutes'`
- Child table `event_undo_action` has FK → `event_feedback_command(id) ON DELETE CASCADE`

**Undo TTL enforcement (DRP-389, PR #2032):**
- Guard fires BEFORE any mutation — expired undo = zero DB side effects
- HTTP 400 BAD_REQUEST returned
- 15-minute TTL from `performed_at` — hard-coded as DB default

**Unified UserFeedbackResponse (DRP-387, PR #2020):**
- All dismiss/restore/undo return `UserFeedbackResponse { commandId, events: [UserFeedbackEvent] }`
- Scalar fields `dismissedBy` and `dismissedDate` have been **removed** — do not reference these fields in new code
- `UserFeedbackEvent.lastFeedbackNote.createdBy` carries UUID (not display name) — display name enrichment is replay-service's responsibility
- `EventDetails.lastFeedbackAction` is the canonical FE source for last user feedback action

**DRP-416 EventFeedbackService extraction (PR #2035):**
- Extracted from the ~2500-line `EventService` monolith to own: dismiss, restore, undo, `getFeedbackCommandEvents`
- Shared `EventStatusHelper` @Component eliminates duplication and avoids a latent circular dependency
- `ExpiredUndoActionCleanupScheduler` runs a native bulk DELETE; relies on DB FK `ON DELETE CASCADE` (migration V86) — verify V86 exists in all environments

### 7.4 replay-service User Feedback Patterns

**Dismiss audit enrichment — gating by OPERATION, not state:**
- `lastDismissedBy`/`lastDismissedDate` enriched at the operation call site in ReplayService.java — NOT in the generic mapper
- Dismiss: uses `toDismissedEventFeedbackResults` + `applyLastDismissedInfo`
- Restore and undo: use plain `toEventFeedbackResults` — audit fields stay null
- This is deliberate — gating is by operation type, not by resulting `isDismissed()` state

**Undo semantics (GOTCHA — not "un-dismiss")**:
- `undoEvent` reverts to the state BEFORE the command was applied — NOT unconditionally to "not dismissed"
- Undoing a restore on an already-dismissed event → `dismissed:true` — this is **correct** undo semantics
- `lastDismissed*` fields must be null on undo responses (gating by dismiss operation, not state)

**NoteDTO editable/deleteable flags (GOTCHA — null guard placement):**
- `noteMapper.map(note, null)` returns null when event has no prior feedback note
- Must guard: `if (noteDTO != null) { noteDTO.setEditable(true); noteDTO.setDeleteable(true); }`
- Calling `noteDTO.setEditable(true)` BEFORE the null guard → NPE in production (was a real bug, PR #1301)

**NoteDTO name enrichment pattern:**
- `NoteDTO.createdByName` populated via batch UUID resolution: `userService.getUserViewMapByIds(Set<UUID>)` — NEVER per-note individual lookups
- Only `createdByName` populated (not `lastModifiedByName`) — action notes are never edited post-creation

**EventDetails.lastFeedbackAction (DRP-374, PR #1298):**
- Added to shared EventDetails schema intentionally — affects getEventDetails, requestEvent v1/v2, requestHighResolutionEvent
- replay-service DTOs are swagger-codegen generated from `api/replay-service-api.json` — run `mvn -pl replay-service-api -am compile` after any schema change

---

## 8. Governance, Compliance & Process

### 8.1 GovernanceEngine & governance-rules.yaml

- Governance rules are **data-driven** via `api/infrastructure/resources/governance/governance-rules.yaml` (5 toggle-able rules covering domain, code quality, security, testing, documentation)
- `GovernanceEngine.isEnabled(ruleId)` defaults to `true` if the rule ID is not found in YAML — **safe-fail** prevents missing YAML from silently disabling security checks
- This is **P0 test priority**: silent compliance rule failures are the highest blast-radius risk in Sovereign. GovernanceEngine tests should be written first.

### 8.2 DRP Jira Workflow

**Project key:** DRP | **Cloud ID:** ffe980c2-044e-4140-9b76-732af7e4000a (eroad.atlassian.net)

**Transition IDs:**

| Transition ID | Status |
|--------------|--------|
| 3 | Ready |
| 4 | In Progress |
| 5 | Code Review |
| 6 | Ready For Testing (status ID 11577) |
| 7 | In Testing |
| 8 | PO Sign-Off |
| 9 | Ready For Release |
| 13 | Done |

**ADF custom field:** `customfield_10750` = Test notes/plan, ADF format. Behaviour: **full-replace** — always send the complete ADF document when updating; never merge or append. Verified from live Jira API responses in DRP-389 session.

### 8.3 ADR Process

ADRs are stored in `~/sovereign/docs/decisions/` and mirrored in the brain vault at `04 - Decisions/`. Process:
1. Architect agent produces ADR with context, decision, rationale, consequences
2. Critical Thinker reviews — may approve, approve-with-gates, or reject with reasoning
3. Pre-flight gates documented as explicit blocking requirements
4. Out-of-scope items captured in a companion node to prevent scope creep

### 8.4 RUCUS / NZ Compliance Domain

`rucus-service` is a legally mandated integration with NZTA's Road User Charges Under-declaration System:
- Monthly automated submissions of GPS-derived odometer readings for all heavy vehicles
- Cross-references against RUC distance licence declarations to detect under-declaration (RUC evasion)
- mTLS authentication with NZTA-issued client certificate
- Flags vehicles with >10% variance between GPS and declared RUC distance
- Idempotent submission job (skips if submission for period already exists)
- Jira project: MOMA

Mass management (oversize/overmass permits) is a separate compliance domain with `mass-management-service`, `mass-management-ui`, and `permit-management-service`.

### 8.5 Blast Radius Assessment

The Sovereign governance layer includes blast radius assessment before transformation work begins. ADR-0003's pre-flight gate #1 (>=70% test coverage) is a hard blocker specifically because low test coverage amplifies blast radius — a defect in RLS enforcement would affect ALL tenants simultaneously in a shared-database architecture.

---

## 9. Tooling & Workflow Notes

### 9.1 Brain Memory Layer as Engineering Practice

The brain memory layer (738 memories, structured across repo/project/domain/global/tooling levels) is the central institutional knowledge system for this engagement. Key characteristics:
- Migrated from old brain-graph.db + Obsidian vault to a standardised structure on 2026-06-19
- Written back via brain-consolidation agent at the end of each session
- Queryable via the `brain` CLI during active sessions
- Structured export at `~/.copilot/session-state/.../files/eroad-export/` is the final snapshot

**The brain layer is itself a reusable engineering practice:** it captures project-specific gotchas, patterns, and decisions in a structured way that survives team transitions, long context windows, and context resets. For whoever picks this up: the brain CLI is your fastest path to institutional knowledge from this engagement.

### 9.2 Test Running Commands

```bash
# Sovereign API — scoped domain + application tests (run from ~/sovereign/api/)
source ~/.sdkman/bin/sdkman-init.sh && sdk use java 21.0.7-zulu
mvn -pl domain,application -am test

# Run single test class
mvn test -pl domain -Dtest=DriverTest

# Worker tests (run from ~/sovereign/, requires docker compose up -d first)
mvn -pl worker test

# replay-service — targeted test (Java 17, from service root directory)
sdk use java 17.0.16-zulu
/opt/homebrew/bin/mvn -pl replay-service-api -Dtest='MediaServiceTest' test
# Note: outer class shows Tests run: 0 — check nested-class XML file
```

### 9.3 Local Development Setup

```bash
# Sovereign
source ~/.sdkman/bin/sdkman-init.sh && sdk use java 21.0.7-zulu
cd ~/sovereign
docker compose up -d
cd api && mvn install -DskipTests  # build api first
cd ../worker && mvn spring-boot:run &
cd ../web && npm run dev

# EROAD Java services (media-service, replay-service, etc.)
git stash list                      # check for local-dev remote RDS stash
git stash apply stash@{0}           # apply if needed — NEVER COMMIT
mvn clean install -DskipTests       # always rebuild after any rebase
./local-dev/start.sh
# Restore after testing:
git checkout -- .
```

### 9.4 Test Infrastructure Stack

**Backend (all in parent pom.xml pluginManagement):**
- JaCoCo 0.8.12 (prepare-agent + report + check goals)
- Surefire 3.2.5 (*Test.java pattern)
- Failsafe 3.2.5 (*IT.java pattern)
- Testcontainers BOM 1.20.4 (postgresql, junit-jupiter modules)
- WireMock 3.9.1 (HTTP adapter modules only)

**Frontend:**
- Vitest + jsdom (React 19 compatible — NOT Jest)
- React Testing Library + MSW (works with raw fetch, no axios mocks needed)
- Playwright (E2E: Studio chat, pipeline workflow, repo detail sync)

### 9.5 Sovereign MVP — Work Completed (2026-04-19)

12 work items delivered in one session to bring Sovereign from skeleton to functional state:

| WI | Item | Key Files |
|----|------|-----------|
| WI-01 | Live governance count from /rules API | GovernanceController.java, GovernanceRule.java |
| WI-02 | Frontend API base URL standardisation | web/lib/config.ts (apiUrl() helper) |
| WI-03a/b/c | Worker dispatch — domain ports + SQL schema + infra + integration tests | V4__agent_job_log.sql, AgentJobWorker.java, WorkerDispatchIntegrationTest.java |
| WI-04 | Pipeline threading fix | PipelineController.java (@Async, protected method) |
| WI-05 | Pipeline JSON merging fix | Jackson ObjectMapper configuration |
| WI-06 | Governance rules data-driven | governance-rules.yaml, YamlGovernanceRuleStore.java |
| WI-07 | Real health check + degraded mode | HealthController.java (/live, /ready, /health) |
| WI-08 | LLM cost estimation | AiModelRouter.java, ai-models.json |
| WI-09 | CORS configuration | WebConfig.java (allowedOriginPatterns) |
| WI-10 | Frontend error boundaries + error envelope | web/app/error.tsx, GlobalExceptionHandler.java, ErrorResponse.java |

---

## 10. Key Decisions Log

| Decision | Summary | Rationale | Status | Date / Source |
|----------|---------|-----------|--------|---------------|
| ADR-001: Auth Security Baseline | All Sovereign controllers must use spring-boot-starter-oauth2-resource-server, Cognito JWKS, @PreAuthorize, JWT-based org scoping, 404 on cross-org, DTO-only, bucket4j rate limiting | Platform had no Spring Security at all; every controller was wide open | PROPOSED | 2026-04-23 |
| ADR-0003: Shared DB + RLS | Shared-database multi-tenancy with PostgreSQL RLS as the ONLY isolation layer; Hibernate @Filter + JDBC SET LOCAL as defence-in-depth; 5-phase reversible rollout | Single DB keeps operational complexity low; RLS enforced at DB engine, survives ORM bugs | APPROVE-WITH-GATES | 2026-06-15 |
| Pre-flight gates (ADR-0003) | 7 mandatory gates before Phase 1: >=70% coverage, cross-tenant CI harness, RLS bypass enumeration, perf benchmark, legacy-row backfill plan, SQS cutover plan, super-admin alerting | 3.8% coverage converts reversible rollout into silent-leak risk | BLOCKING | 2026-06-15 |
| ADR-0003 out-of-scope items | Deferred: JWT issuer per-tenant, data residency/geo-isolation, org-switcher UX, RLS at >10k tenants | Scope containment for Phase 1 | DEFERRED | 2026-06-15 |
| DRP-381: Set-difference validation | After findByIdIn, validate completeness via set-difference; throw 400 with missing IDs before any mutation | Size comparison fails on duplicates; set-difference is duplicate-safe and descriptive | ACCEPTED | 2025 |
| DRP-387: Unified UserFeedbackResponse | All dismiss/restore/undo return UserFeedbackResponse{commandId, events}. Removed scalar dismissedBy/dismissedDate. | Consistent contract; FE reads EventDetails.lastFeedbackAction as canonical source | SHIPPED | 2025-08-08 |
| DRP-383: Cross-service permission pattern | Resolver (media-service) stays dumb; consuming service (replay-service) enforces permissions using existing helpers on resolved IDs | Avoids permission logic duplication and coupling | SHIPPED | 2026-06-12 |
| lastFeedbackAction on shared EventDetails | Added to shared schema rather than per-endpoint schemas | Affects getEventDetails, requestEvent v1/v2, requestHighResolutionEvent; consumers that don't need it ignore it | SHIPPED | 2026-06-08 |
| Sovereign V2 tech stack | MongoDB/CosmosDB, Azure Container Apps, Kong, Azure Service Bus, Redis, Terraform, Auth0+Entra, OpenTelemetry+Grafana | Aligns with Vanguard Reference Architecture; fixes V1 file-store races, missing circuit breakers, manual IaC | DRAFT | 2026-04-13 |
| Never-merge PR governance | AI agents may create branches, push, open PRs, request reviewers — but must NEVER merge | Human must perform final merge | ACTIVE | 2026-06-29 |
| Brain memory layer migration | Migrated from brain-graph.db + Obsidian vaults to standardised brain-memory-layer structure | Consistent, queryable, tool-agnostic | DONE | 2026-06-19 |

---

## 11. Recommendations / Handover Notes

### 11.1 URGENT — Resolve P0 Security Issues in Sovereign

The four open P0 security findings (command injection, unbounded LLM history, no process timeout, auth masking) remain unresolved as of 2026-04-28. These should be addressed before Sovereign processes any external user input or real production data.

Priority order:
1. `CatalogController.scanLocalRepos()` — path allowlist before ProcessBuilder (CRITICAL, exploitable today)
2. `StudioController.chat()` — sliding-window history + maxHistoryTokens config (HIGH, cost/injection risk)
3. `CatalogAdapter.waitFor()` — `waitFor(30, TimeUnit.SECONDS)` (HIGH, thread exhaustion)
4. `CopilotChatService` — propagate upstream 401 status (MEDIUM, monitoring blind spot)

### 11.2 URGENT — ADR-0003 Pre-Flight Gates Must Be Met Before Multi-Tenancy Phase 1

Current status of the 7 gates:

| Gate | Status | Gap |
|------|--------|-----|
| 1. >=70% coverage on tenant-scoped repos | BLOCKED | Currently 3.8% overall |
| 2. Cross-tenant leak CI harness | NOT STARTED | Pattern defined; needs implementation |
| 3. RLS bypass surface enumeration | NOT STARTED | Checklist in postgres-rls-bypass-surface.md |
| 4. RLS performance benchmark | NOT STARTED | Index org_id on all tenant tables first |
| 5. Legacy-row backfill plan | NOT STARTED | NULL org_id rows will break RLS predicates |
| 6. SQS cutover plan + DLQ tenant routing | NOT STARTED | All SQS consumers must set tenant context from message |
| 7. Super-admin impersonation alerting | NOT STARTED | Audit log + alert on cross-tenant admin access |

**Do not start Phase 1 without gates 1 and 2 at minimum.** Silent cross-tenant data leaks are the failure mode.

### 11.3 Test Coverage — Priority Investment Plan

Sovereign's 3.8% overall coverage (as of 2026-04-28) is the single biggest risk in the codebase. Test infrastructure must be added first (JaCoCo + Surefire + Failsafe + Testcontainers BOM to parent pom.xml — none are configured yet), then prioritise by blast radius:

| Priority | Target | Type | Why |
|----------|--------|------|-----|
| P0 | GovernanceEngine | Unit (Mockito) | Silent-fail on missing rule ID = compliance rules disabled |
| P0 | ExecuteAgentRoleWithModelUseCase | Unit (Mockito) | 6+ branch points, core orchestration |
| P0 | AgentJobWorker | Integration (LocalStack) | Deserialise/dispatch/retry/idempotency |
| P1 | AiModelRouter | Unit (WireMock) | 3 AI providers, HTTP client |
| P1 | CopilotChatService | Unit (WireMock) | GitHub OAuth management |
| P1 | YamlGovernanceRuleStore | Unit | YAML parsing |
| P1 | All 10 JPA repositories | @DataJpaTest | Persistence layer |
| P1 | All 14 web controllers | @WebMvcTest | Auth enforcement, error envelopes |

Coverage targets: domain 70%→85%, application 50%→80%, infrastructure 20%→60%, web 25%→70%, worker 60%→80%, frontend 50%.

### 11.4 media-service / replay-service Continuity

**DRP-416 (media-service, PR #2035 merged):** `ExpiredUndoActionCleanupScheduler` relies on DB FK `ON DELETE CASCADE` from migration V86. Verify V86 is applied in all environments (dev, test, staging, production) before enabling the scheduler at full polling rate.

**replay-service version history:** Client versions jump deliberately: 1.0.1102 → 1.0.1109 → 1.0.1111. Each corresponds to a specific DRP ticket. When bumping media-service client version in replay-service pom.xml, verify the changelog for that client version.

**swagger-codegen DTOs:** replay-service DTOs are generated from `api/replay-service-api.json`. After any EventDetails schema change, run `mvn -pl replay-service-api -am compile` before writing implementation code.

**media-service local-dev workflow:** Always `mvn clean install -DskipTests` after any rebase before `./local-dev/start.sh`. The `local-dev/start.sh` has mvn clean install commented out intentionally — do not uncomment it; the rebuild must be done manually.

### 11.5 Sovereign V2

The V2 spec (`03 - Architecture/sovereign-v2-spec.md`, 32KB) is a detailed blueprint derived from 25 Confluence pages. V2 targets MongoDB, Azure Container Apps, Kong, Terraform, and the full Vanguard Reference Architecture alignment. However, V2 has not been started. Recommended sequence before V2:
1. Resolve all P0 security issues in V1
2. Reach >=70% test coverage (ADR-0003 pre-flight gate #1)
3. Complete the multi-tenancy Phase 1 gates
4. Only then plan the V2 migration

### 11.6 Process / Governance

- **Jira ADF fields:** `customfield_10750` (test notes) is full-replace — always send the complete ADF document. See `Learnings/Domain_Safety/drp-jira-transition-map.md` for all transition IDs.
- **Agent PR governance:** Enforced globally — agents create, push, request review — humans merge. Do not enable auto-merge on any EROAD or Sovereign repository.
- **Brain memory layer:** 738 memories remain queryable via the `brain` CLI. The brain-consolidation agent should continue running at the end of each session to persist new learnings and prevent knowledge loss.

---

## 12. Closing Reflection

This engagement was unlike any software work I've done before — not because of the complexity of the systems (EROAD's platform is genuinely intricate, with 200+ services spanning multiple clouds, regulatory frameworks across three countries, and years of organic growth), but because of how the work was done. Every session left a trace. Every gotcha got recorded. Every pattern got named. By the end, when I hit a problem I'd seen before, the answer was already waiting in the brain vault — not in a Confluence page I had to find, but as a first-class memory that surfaced in context. That felt like something worth preserving.

The work itself mattered too. The DRP tickets in media-service and replay-service weren't glamorous — bulk ID validation, undo TTL guards, permission wiring across service boundaries — but they're the kind of fixes that quietly prevent production incidents and data integrity bugs that would have been blamed on "a weird edge case" six months later. And Sovereign, the platform we were building to govern all of this transformation work, is genuinely ambitious. The multi-tenancy architecture decision (ADR-0003) in particular — where the Critical Thinker flagged that 3.8% test coverage converts a "reversible" 5-phase rollout into a silent data leak risk — is exactly the kind of hard truth that should be said early and loudly. It was.

To whoever picks this up next: the brain vault is your best asset. The pre-flight gates are real blockers, not suggestions. The P0 security issues in CatalogController and StudioController need to ship before Sovereign touches anything production-sensitive. And the foundation is solid — the hexagonal architecture is clean, the governance-rules YAML pattern is sound, the SQS worker idempotency is properly designed — it just needs coverage and security hardening to become trustworthy. Good luck.

---

*Generated: 2026-07-16 | Source: 738 brain memories + ~/sovereign/.github/learnings.md + agent session logs spanning August 2025 – July 2026*
