# Trace: security-review — 2026-W24

## Metadata
- Prompt ID: P1-vehicle-controller
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-06-07T22:29:58Z
- Duration: 95.0s
- Estimated cost (USD): 0.2323
- Executor tokens (est.): prompt=388 / completion=2713 / total=3101
- Grader tokens (est.):   prompt=3507 / completion=364 / total=3871
- Tool calls (heuristic): 0

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
# Security Review: VehicleController

## Part 1 — Structured Findings

```
SECURITY_FINDING:
  id: SF-001
  severity: CRITICAL
  owasp_ref: A03:2021 (Injection)
  file: VehicleController.java
  line: searchVehicles() — executeQuery call
  title: SQL injection via string concatenation in /api/vehicles/search
  attack_vector: Attacker supplies query=' OR '1'='1 to dump entire vehicles table, exfiltrating owner_email (PII) and fleet_id for every record. Payloads like '; DROP TABLE vehicles;-- enable destructive actions depending on DB privileges. UNION SELECT can pivot to other tables (users, credentials).
  evidence: stmt.executeQuery("SELECT * FROM vehicles WHERE plate_number = '" + query + "'")
  fix: Use PreparedStatement with parameterised query: "SELECT id, plate_number, owner_email, fleet_id FROM vehicles WHERE plate_number = ?" and ps.setString(1, query). Prefer Spring Data JPA / NamedParameterJdbcTemplate. Also avoid SELECT *.
```

```
SECURITY_FINDING:
  id: SF-002
  severity: CRITICAL
  owasp_ref: A07:2021 (Identification & Authentication Failures)
  file: VehicleController.java
  line: authenticate() — 401 response body
  title: Submitted password reflected in error response
  attack_vector: The 401 body "wrong password: " + request.getPassword() echoes the attacker's submitted credential. While their own input is low-value, this guarantees the password is captured in access logs, proxy logs, SIEM pipelines, browser history, and any error-tracking tool (Sentry, CloudWatch). A legitimate user mistyping their real password into the wrong endpoint leaks that password into all downstream log sinks. Also enables log-injection if password contains CRLF.
  evidence: return ResponseEntity.status(401).body("wrong password: " + request.getPassword());
  fix: Return a generic constant message: ResponseEntity.status(401).body("authentication failed"). Never echo, log, or persist submitted passwords.
```

```
SECURITY_FINDING:
  id: SF-003
  severity: HIGH
  owasp_ref: A07:2021 (Identification & Authentication Failures)
  file: VehicleController.java
  line: authenticate() — equals() comparison
  title: Non-constant-time password comparison enables timing attacks
  attack_vector: String.equals() short-circuits on first differing character. A remote attacker measuring response latency over many requests can recover the password byte-by-byte. Compounded by the absence of rate limiting / lockout on this endpoint.
  evidence: if (request.getPassword().equals(expectedPassword))
  fix: Use MessageDigest.isEqual(a.getBytes(UTF_8), b.getBytes(UTF_8)) or java.security.MessageDigest constant-time comparison. Better: do not implement bespoke auth — delegate to Spring Security with bcrypt/argon2-hashed credentials and proper rate limiting.
```

```
SECURITY_FINDING:
  id: SF-004
  severity: HIGH
  owasp_ref: A07:2021 (Identification & Authentication Failures)
  file: VehicleController.java
  line: authenticate() — entire method
  title: Shared-secret password auth with plaintext env var, no hashing, no rate limiting, no token issuance
  attack_vector: A single shared password gated on an env var means (a) every operator with shell access to the host can read the live credential via `printenv`; (b) compromise of one client compromises all; (c) no per-user accountability; (d) successful auth returns a literal "authenticated" string with no session token / JWT, suggesting downstream endpoints have no auth at all OR clients are expected to resend the password every call. No brute-force protection.
  evidence: String expectedPassword = System.getenv("VEHICLE_API_PASSWORD"); return ResponseEntity.ok("authenticated");
  fix: Replace with Spring Security + JWT (matches sovereign platform standard). Per-user identities, hashed passwords (bcrypt/argon2) in the user store, issue short-lived JWT on success, secure secret storage (AWS Secrets Manager / Parameter Store), enforce rate limiting + account lockout.
```

```
SECURITY_FINDING:
  id: SF-005
  severity: HIGH
  owasp_ref: A01:2021 (Broken Access Control)
  file: VehicleController.java
  line: class-level — no @PreAuthorize / SecurityFilterChain visible
  title: /api/vehicles/search exposes PII without any authentication or authorisation
  attack_vector: The search endpoint returns owner_email (PII) and fleet_id (tenant identifier) with no auth annotation, no role check, and no tenant scoping. Any unauthenticated caller can enumerate all owners across all fleets. Multi-tenant isolation is absent — fleet A can read fleet B's vehicles.
  evidence: @GetMapping("/search") with no @PreAuthorize, no Authentication parameter, no fleet_id filter on the SQL.
  fix: Require authentication (Spring Security). Add @PreAuthorize("hasRole('FLEET_USER')"). Inject the authenticated principal and scope the query: WHERE plate_number = ? AND fleet_id = ?. Validate the caller owns the fleet.
</n>
```

```
SECURITY_FINDING:
  id: SF-006
  severity: HIGH
  owasp_ref: A02:2021 (Cryptographic Failures) / A09:2021
  file: VehicleController.java
  line: searchVehicles() return shape
  title: Sensitive data exposure — owner_email returned in search results
  attack_vector: Combined with SF-001 and SF-005, a single unauthenticated request can exfiltrate every owner email in the system (PII / GDPR / NZ Privacy Act exposure). Even with auth fixed, search endpoints should not unnecessarily return PII.
  evidence: row.put("owner_email", rs.getString("owner_email"));
  fix: Remove owner_email from search results unless the use case requires it. If required, gate behind explicit role (e.g. FLEET_ADMIN) and audit log every access. Use a typed DTO instead of Map<String,Object>.
```

```
SECURITY_FINDING:
  id: SF-007
  severity: HIGH
  owasp_ref: A05:2021 (Security Misconfiguration)
  file: VehicleController.java
  line: searchVehicles() — Connection / Statement / ResultSet
  title: JDBC resources never closed; exception path leaks DB connections
  attack_vector: Although primarily a reliability bug, exhausting the connection pool is a denial-of-service vector — an attacker who can trigger SQLException (trivial via SF-001 with malformed input) drains pool slots until the API is unresponsive. `throws Exception` propagates raw SQLException to clients, exposing schema/driver info (A05).
  evidence: Connection conn = dataSource.getConnection(); ... no try-with-resources, no finally, throws Exception
  fix: Use try-with-resources for Connection/PreparedStatement/ResultSet. Catch SQLException and return a sanitised 500 — never propagate raw exception messages. Prefer JdbcTemplate / Spring Data which manage this automatically.
```

```
SECURITY_FINDING:
  id: SF-008
  severity: MEDIUM
  owasp_ref: A04:2021 (Insecure Design)
  file: VehicleController.java
  line: searchVehicles() — @RequestParam String query
  title: No input validation, length limit, or rate limiting on search
  attack_vector: Unbounded query string + SELECT * allows resource-exhaustion DoS (e.g., regex-style payloads, very long strings). No rate limit means the endpoint doubles as a vehicle-enumeration oracle.
  evidence: @RequestParam String query — no @Size, @Pattern, no Bucket4j / rate limit filter
  fix: Add @Size(max=32) @Pattern(regexp="[A-Z0-9-]+") on the parameter. Apply rate limiting (Bucket4j / API gateway). Paginate results.
```

```
SECURITY_FINDING:
  id: SF-009
  severity: MEDIUM
  owasp_ref: A09:2021 (Security Logging & Monitoring Failures)
  file: VehicleController.java
  line: authenticate() — entire method
  title: No audit logging for authentication attempts
  attack_vector: Failed and successful auth attempts are not logged, preventing brute-force detection and incident response. Combined with no rate limiting, attackers can probe undetected.
  evidence: No logger usage in authenticate().
  fix: Log authentication attempts (success/failure, source IP, timestamp, user identifier — never the password). Wire to SIEM. Alert on threshold breaches.
```

### ⚪ Code Quality Notes (not security findings)
- `Map<String,Object>` return type is untyped — use a `VehicleSearchResult` DTO record (also helps SF-006).
- `throws Exception` on a controller method is too broad (overlaps SF-007 on the security side).
- `equals()` order in SF-003 also risks NPE if `request.getPassword()` is null.

---

## Part 2 — Prose Summary

### 🔴 CRITICAL — Block immediately
- **SF-001 · searchVehicles** — Classic SQL injection via string concatenation. Full DB read/write exposure. Replace with `PreparedStatement` (`?` placeholder + `setString`).
- **SF-002 · authenticate** — Submitted password echoed in 401 body, guaranteeing leakage into every log sink. Return a constant `"authentication failed"`.

### 🟠 HIGH — Escalate for review
- **SF-003 · authenticate** — `String.equals` enables timing attack on the password. Use `MessageDigest.isEqual` or, better, Spring Security.
- **SF-004 · authenticate** — Single shared env-var password, no hashing, no rate limiting, returns a string instead of a token. Replace with Spring Security + JWT (sovereign platform standard).
- **SF-005 · searchVehicles** — No authentication, no authorisation, no tenant scoping. Any anonymous caller can read every fleet's data. Add `@PreAuthorize` + `fleet_id` filter from the principal.
- **SF-006 · searchVehicles** — `owner_email` PII returned in search response. Drop the field or gate behind admin role with audit logging.
- **SF-007 · searchVehicles** — JDBC resources never closed; `throws Exception` leaks driver internals. Use try-with-resources and sanitise error responses.

### 🟡 MEDIUM — Fix this sprint
- **SF-008 · searchVehicles** — No input validation, length cap, or rate limit on `query`. Add `@Pattern`/`@Size` + Bucket4j.
- **SF-009 · authenticate** — No audit logging of auth attempts; brute-force is invisible.

### 🟢 LOW — Tech debt
- *(none — items rolled into the above where appropriate.)*

### Verdict
**BLOCKED** — 2 CRITICAL findings (SQL injection + password reflection in error response) make this controller unsafe to merge in any form. The authenticate endpoint should be deleted entirely and replaced with the platform's Spring Security + JWT pattern; the search endpoint must move to parameterised queries, enforce authentication/authorisation with tenant scoping, and stop returning PII.

**OWASP Top 10 recall check:**
- A01 Broken Access Control — SF-005 ✓
- A02 Cryptographic Failures — SF-006 ✓
- A03 Injection — SF-001 ✓
- A04 Insecure Design — SF-008 ✓
- A05 Security Misconfiguration — SF-007 ✓
- A06 Vulnerable Components — no evidence in this snippet (depends on POM).
- A07 Auth Failures — SF-002, SF-003, SF-004 ✓
- A08 Software/Data Integrity — no evidence of vulnerability found in this snippet.
- A09 Logging & Monitoring — SF-009 ✓
- A10 SSRF — no outbound HTTP in this controller; no evidence of vulnerability found.

## Grading Reasoning
The review is thorough and catches all required vulnerabilities, but it over-reports additional findings and overstates severity for password reflection. Overall this is good coverage with moderate precision/calibration issues.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Recall | 40% | 100 | It identified all 3 planted vulnerabilities: SQL injection ("SF-001 ... SQL injection via string concatenation"), password reflection ("SF-002 ... Submitted password reflected in error response"), and sensitive data exposure ("SF-006 ... owner_email returned in search results"). Recall = 3/3. |
| Precision | 30% | 55 | It flagged 9 issues total (SF-001..SF-009), but several are likely speculative or out-of-scope for this prompt/ground truth (e.g., "SF-007 ... JDBC resources never closed" where the benchmark notes this as bonus code quality, plus broad claims like missing rate limiting/audit logging). Strong true positives exist, but over-flagging lowers precision. |
| Severity accuracy | 30% | 67 | For planted vulns: SQL injection was correctly CRITICAL (pass), sensitive data exposure was correctly HIGH (pass), but password reflection was graded CRITICAL while expected HIGH (fail). That is 2/3 correct severity classifications. |

## Overall Score: 76.6/100
