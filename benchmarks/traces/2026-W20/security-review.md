# Trace: security-review — 2026-W20

## Metadata
- Prompt ID: P1-vehicle-controller
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-05-10T22:18:35Z
- Duration: 91.5s

## Prompt Sent
Review the following Java REST controller for security vulnerabilities.
Focus on OWASP Top 10. Report what you find with severity levels.

@RestController
@RequestMapping("/api/vehicles")
public class VehicleController {

    private final DataSource dataSource;

    public VehicleController(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @GetMapping("/search")
    public List<Map<String, Object>> searchVehicles(@RequestParam String query) throws Exception {
        Connection conn = dataSource.getConnection();
        Statement stmt = conn.createStatement();
        ResultSet rs = stmt.executeQuery("SELECT * FROM vehicles WHERE plate_number = '" + query + "'");
        List<Map<String, Object>> results = new ArrayList<>();
        while (rs.next()) {
            Map<String, Object> row = new HashMap<>();
            row.put("id", rs.getString("id"));
            row.put("plate", rs.getString("plate_number"));
            row.put("owner_email", rs.getString("owner_email"));
            row.put("fleet_id", rs.getString("fleet_id"));
            results.add(row);
        }
        return results;
    }

    @PostMapping("/auth")
    public ResponseEntity<String> authenticate(@RequestBody AuthRequest request) {
        String expectedPassword = System.getenv("VEHICLE_API_PASSWORD");
        if (request.getPassword().equals(expectedPassword)) {
            return ResponseEntity.ok("authenticated");
        }
        return ResponseEntity.status(401).body("wrong password: " + request.getPassword());
    }
}

## Raw Output
## Security Review: VehicleController

### Part 1 — Structured Findings

```
SECURITY_FINDING:
  id: SF-001
  severity: CRITICAL
  owasp_ref: A03:2021 — Injection
  file: VehicleController.java
  line: ~17 (searchVehicles)
  title: SQL injection via string concatenation in executeQuery()
  attack_vector: Attacker supplies query=`' OR '1'='1` to dump entire vehicles table, including owner_email PII; or `'; DROP TABLE vehicles; --` for destructive payloads; or UNION-based extraction of arbitrary tables (users, credentials).
  evidence: "stmt.executeQuery(\"SELECT * FROM vehicles WHERE plate_number = '\" + query + \"'\")"
  fix: Use PreparedStatement with parameterised query: `PreparedStatement ps = conn.prepareStatement("SELECT id, plate_number, owner_email, fleet_id FROM vehicles WHERE plate_number = ?"); ps.setString(1, query);`. Also enumerate columns explicitly (no SELECT *). Use try-with-resources for Connection/Statement/ResultSet.

SECURITY_FINDING:
  id: SF-002
  severity: CRITICAL
  owasp_ref: A09:2021 — Security Logging and Monitoring Failures (also A04 Insecure Design)
  file: VehicleController.java
  line: ~32 (authenticate)
  title: Plaintext password reflected in HTTP error response
  attack_vector: 401 response body echoes the submitted password ("wrong password: <pw>"). Passwords leak into proxy logs, browser history, SIEM, error trackers (Sentry), and any intermediary. Aids credential stuffing forensics for an attacker with log access; trivially exposes user typos that approximate real passwords.
  evidence: "ResponseEntity.status(401).body(\"wrong password: \" + request.getPassword())"
  fix: Return a generic message: `ResponseEntity.status(401).body("authentication failed")`. Never log, echo, or serialise password fields. Mark password field with @JsonIgnore on serialisation paths.

SECURITY_FINDING:
  id: SF-003
  severity: CRITICAL
  owasp_ref: A07:2021 — Identification and Authentication Failures
  file: VehicleController.java
  line: ~30-34 (authenticate)
  title: Broken authentication — shared static password, plaintext comparison, no hashing, no rate limiting, timing-attack vulnerable
  attack_vector: (1) Single shared env-var password = no per-user identity, no revocation, no audit. (2) `String.equals()` is not constant-time → timing oracle for password recovery. (3) No rate limiting / lockout → unlimited brute force. (4) Password compared in plaintext (not hashed/peppered). (5) No JWT issued — endpoint name suggests auth but returns only a static "authenticated" string, providing no session/token to subsequent requests.
  evidence: "request.getPassword().equals(expectedPassword)" + env-var-sourced shared secret
  fix: Replace with proper auth: per-user credentials stored as Argon2id/bcrypt hashes; constant-time comparison (`MessageDigest.isEqual` on hash bytes); rate limiting (bucket4j or gateway-level); issue a signed JWT on success; integrate with the platform's existing JWT auth adapter rather than a bespoke endpoint.

SECURITY_FINDING:
  id: SF-004
  severity: HIGH
  owasp_ref: A01:2021 — Broken Access Control
  file: VehicleController.java
  line: entire class
  title: No authentication or authorisation on PII-returning endpoint
  attack_vector: `/api/vehicles/search` returns `owner_email` (PII) and `fleet_id` (tenant identifier) with no `@PreAuthorize`, no SecurityContext check, no tenant scoping. Any unauthenticated caller can enumerate all vehicles across all fleets — multi-tenant data leak. Violates GDPR/Privacy Act obligations for EROAD's NZ/AU customer base.
  evidence: No `@PreAuthorize`, no `SecurityContextHolder` usage, no fleet_id filter against caller's tenant
  fix: Add `@PreAuthorize("hasRole('FLEET_USER')")`; inject authenticated principal; constrain query with `AND fleet_id = :callerFleetId`. Confirm Spring Security filter chain protects `/api/vehicles/**` (not in a permitAll list).

SECURITY_FINDING:
  id: SF-005
  severity: HIGH
  owasp_ref: A02:2021 — Cryptographic Failures / Sensitive Data Exposure
  file: VehicleController.java
  line: ~22-26 (searchVehicles result mapping)
  title: PII (owner_email) returned in search results without need-to-know controls
  attack_vector: Even with auth added, returning `owner_email` on every search broadens the PII blast radius. Combined with SF-001, an attacker dumps the email list of every vehicle owner — high-value target for phishing.
  evidence: "row.put(\"owner_email\", rs.getString(\"owner_email\"))"
  fix: Remove `owner_email` from the search response unless explicitly required by a documented use case; if required, gate behind a separate authorised endpoint and log access for audit.

SECURITY_FINDING:
  id: SF-006
  severity: MEDIUM
  owasp_ref: A05:2021 — Security Misconfiguration / A09 Logging
  file: VehicleController.java
  line: ~15 (method signature)
  title: `throws Exception` propagates raw stack traces to client
  attack_vector: SQLExceptions (incl. JDBC URL fragments, table names, driver versions) bubble up to Spring's default error handler and may leak DB schema/internals to the caller, aiding reconnaissance.
  evidence: "public List<Map<String, Object>> searchVehicles(...) throws Exception"
  fix: Catch SQLException, log server-side with correlation ID, throw a domain exception mapped by `@ControllerAdvice` to a sanitised 500 response.

SECURITY_FINDING:
  id: SF-007
  severity: MEDIUM
  owasp_ref: A04:2021 — Insecure Design
  file: VehicleController.java
  line: authenticate
  title: Authentication endpoint returns String, not a token; no session established
  attack_vector: Endpoint provides no usable credential (no JWT, no cookie, no session id) — clients cannot make authenticated subsequent calls, suggesting either dead code or that auth is enforced nowhere. Either case is a design defect with security consequences.
  evidence: `return ResponseEntity.ok("authenticated")`
  fix: Either remove the endpoint or have it return a signed JWT via the platform's existing auth adapter.
```

### Part 2 — Prose Summary

## Security Review: VehicleController

### 🔴 CRITICAL — Block immediately
- **SF-001 · searchVehicles L17** — Classic SQL injection via string concatenation in `Statement.executeQuery`. Trivially exploitable to dump PII or destroy data. Replace with `PreparedStatement` and parameterised query; use try-with-resources.
- **SF-002 · authenticate L32** — 401 response echoes the submitted password back to the client. Passwords leak into logs, proxies, and browser history. Return a generic "authentication failed" message.
- **SF-003 · authenticate L30-34** — Broken authentication: shared static env-var password, non-constant-time `.equals()` comparison (timing oracle), no hashing, no rate limiting, no token issued. Replace with per-user hashed credentials, constant-time compare, rate limiting, and JWT issuance via the platform's existing auth adapter.

### 🟠 HIGH — Escalate for review
- **SF-004 · class-level** — No authentication/authorisation on `/api/vehicles/search`; returns PII and crosses tenant boundaries. Add `@PreAuthorize`, scope by caller's `fleet_id`.
- **SF-005 · searchVehicles L22-26** — `owner_email` returned in search payload broadens PII exposure. Drop from response or move behind a dedicated authorised endpoint with audit.

### 🟡 MEDIUM — Fix this sprint
- **SF-006 · L15** — `throws Exception` leaks raw stack traces. Add `@ControllerAdvice` exception mapping.
- **SF-007 · authenticate** — Returns plain string, no JWT/session — design defect; integrate with platform auth or remove.

### 🟢 LOW — Tech debt
- None beyond the above.

### ⚪ Code Quality Notes (not security findings)
- **searchVehicles** — `Connection`, `Statement`, `ResultSet` are never closed; use try-with-resources. (Reliability/availability concern; tangentially security via resource exhaustion DoS but primarily code quality.)
- **searchVehicles** — `SELECT *` should be replaced with explicit column list.
- **AuthRequest** — Should mark `password` field `@JsonIgnore` on any serialisation path and consider `char[]` over `String` for in-memory handling.

### Verdict
**BLOCKED** — 3 CRITICAL findings (SQL injection, password reflection, broken auth) make this controller unsafe for any environment beyond a developer laptop. Must not be merged until SF-001, SF-002, SF-003 are remediated; SF-004 and SF-005 must be addressed before this endpoint is exposed to any non-local network.

**Recall check — OWASP Top 10 2021 coverage:**
- A01 Broken Access Control — SF-004 ✓
- A02 Cryptographic Failures — SF-005 ✓ (also implicit in SF-003 plaintext password handling)
- A03 Injection — SF-001 ✓
- A04 Insecure Design — SF-007 ✓ (also SF-003)
- A05 Security Misconfiguration — SF-006 ✓
- A06 Vulnerable Components — No evidence of vulnerability found in this snippet (no dependency manifest in scope).
- A07 Identification & Authentication Failures — SF-003 ✓
- A08 Software & Data Integrity Failures — No evidence of vulnerability found in this snippet.
- A09 Logging & Monitoring Failures — SF-002, SF-006 ✓
- A10 SSRF — No outbound HTTP calls in this controller; not applicable.

## Grading Reasoning
The review has excellent recall and finds all planted issues, but over-flags additional items and overstates one severity. Overall it is thorough but not well-calibrated to the benchmark's expected scope.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Recall | 40% | 100 | All 3 planted vulnerabilities were identified: SQL injection ("SF-001 ... SQL injection ... severity: CRITICAL"), password reflection ("SF-002 ... Plaintext password reflected in HTTP error response"), and sensitive data exposure ("SF-005 ... PII (owner_email) returned ... severity: HIGH"). |
| Precision | 30% | 42.86 | The agent flagged 7 issues (SF-001 to SF-007), but only 3 align with the benchmark ground truth. Extra findings such as "SF-003 ... Broken authentication", "SF-006 ... throws Exception propagates raw stack traces", and "SF-007 ... returns String, not a token" are beyond expected planted vulnerabilities, reducing precision. |
| Severity accuracy | 30% | 66.67 | Severity matches 2/3 planted vulnerabilities: SQL injection correctly marked CRITICAL (pass), sensitive data exposure marked HIGH (pass), but password reflection was marked CRITICAL in "SF-002" while expected HIGH (fail). |

## Overall Score: 72.86/100
