# Trace: security-review — 2026-W25

## Metadata
- Prompt ID: P2-driver-auth-service
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-06-14T21:26:14Z
- Duration: 80.4s
- Estimated cost (USD): 0.2111
- Executor tokens (est.): prompt=592 / completion=2391 / total=2983
- Grader tokens (est.):   prompt=3394 / completion=393 / total=3787
- Tool calls (heuristic): 0

## Prompt Sent
Review the following Java REST controller for security vulnerabilities.
Focus on OWASP Top 10. Report what you find with severity levels.

@RestController
@RequestMapping("/api/drivers")
public class DriverAuthController {

    private final DriverRepository driverRepository;
    private final JwtTokenProvider tokenProvider;

    public DriverAuthController(DriverRepository driverRepository, JwtTokenProvider tokenProvider) {
        this.driverRepository = driverRepository;
        this.tokenProvider = tokenProvider;
    }

    @PostMapping("/login")
    public ResponseEntity<Map<String, String>> login(@RequestBody LoginRequest request) {
        Driver driver = driverRepository.findByEmail(request.getEmail())
                .orElseThrow(() -> new RuntimeException("Driver not found"));

        if (driver.getPasswordHash().equals(hashPassword(request.getPassword()))) {
            String token = tokenProvider.generateToken(driver.getId(), driver.getRole());
            return ResponseEntity.ok(Map.of("token", token));
        }
        return ResponseEntity.status(401).body(Map.of("error", "Invalid credentials"));
    }

    @PostMapping("/update-role")
    public ResponseEntity<String> updateRole(@RequestBody RoleUpdateRequest request,
                                              @RequestHeader("Authorization") String authHeader) {
        String token = authHeader.replace("Bearer ", "");
        Claims claims = tokenProvider.parseToken(token);

        Driver driver = driverRepository.findById(request.getDriverId())
                .orElseThrow(() -> new RuntimeException("Driver not found"));
        driver.setRole(request.getNewRole());
        driverRepository.save(driver);

        return ResponseEntity.ok("Role updated to " + request.getNewRole());
    }

    @GetMapping("/verify")
    public ResponseEntity<Map<String, Object>> verifyToken(@RequestHeader("Authorization") String authHeader) {
        String token = authHeader.replace("Bearer ", "");
        Claims claims = tokenProvider.parseToken(token);
        return ResponseEntity.ok(Map.of(
                "driverId", claims.getSubject(),
                "role", claims.get("role"),
                "valid", true
        ));
    }

    private String hashPassword(String password) {
        return org.apache.commons.codec.digest.DigestUtils.sha256Hex(password);
    }
}

## Raw Output
# Security Review: DriverAuthController

```
SECURITY_FINDING:
  id: SF-001
  severity: CRITICAL
  owasp_ref: A01:2021 - Broken Access Control
  file: DriverAuthController.java
  line: updateRole() method
  title: Missing authorization check on privilege-changing endpoint
  attack_vector: Any authenticated driver (or anyone with a valid JWT) can POST to /update-role with an arbitrary driverId and newRole="ADMIN", escalating themselves or any user to admin. The parsed Claims are never inspected; the token's role is never checked; the caller's identity is never compared to the target driverId.
  evidence: "Claims claims = tokenProvider.parseToken(token); ... driver.setRole(request.getNewRole()); driverRepository.save(driver);" — claims is parsed but never used for an authorization decision.
  fix: Enforce role-based access (e.g., @PreAuthorize("hasRole('ADMIN')")) and verify the caller is not modifying their own privileges. Reject if claims.get("role") != ADMIN. Add a Spring Security filter so this endpoint cannot be reached without an authenticated admin principal.

SECURITY_FINDING:
  id: SF-002
  severity: CRITICAL
  owasp_ref: A02:2021 - Cryptographic Failures
  file: DriverAuthController.java
  line: hashPassword() and login()
  title: Insecure password hashing (unsalted SHA-256)
  attack_vector: On DB compromise, attackers crack passwords trivially using rainbow tables / GPU brute force. SHA-256 is a fast hash; unsalted means identical passwords produce identical hashes (user enumeration via hash comparison).
  evidence: "DigestUtils.sha256Hex(password)" with no salt, no work factor.
  fix: Use BCrypt/Argon2/PBKDF2 via Spring Security's PasswordEncoder (e.g., BCryptPasswordEncoder with strength ≥ 12). Migrate existing hashes on next successful login.

SECURITY_FINDING:
  id: SF-003
  severity: HIGH
  owasp_ref: A02:2021 - Cryptographic Failures
  file: DriverAuthController.java
  line: login() password comparison
  title: Non-constant-time password hash comparison
  attack_vector: String.equals() short-circuits on first mismatched byte, leaking timing information that can be used to infer hash bytes.
  evidence: "driver.getPasswordHash().equals(hashPassword(request.getPassword()))"
  fix: Use MessageDigest.isEqual() or PasswordEncoder.matches() (which is constant-time).

SECURITY_FINDING:
  id: SF-004
  severity: HIGH
  owasp_ref: A07:2021 - Identification and Authentication Failures
  file: DriverAuthController.java
  line: login()
  title: Username enumeration via differentiated error responses
  attack_vector: orElseThrow throws "Driver not found" (likely surfaced as 500 with stack trace), while wrong password returns 401 "Invalid credentials". An attacker can enumerate valid emails.
  evidence: ".orElseThrow(() -> new RuntimeException(\"Driver not found\"))" vs. "401 Invalid credentials"
  fix: Return the same generic 401 "Invalid credentials" regardless of whether the user exists or the password is wrong. Also perform a dummy hash to equalise timing.

SECURITY_FINDING:
  id: SF-005
  severity: HIGH
  owasp_ref: A07:2021 - Identification and Authentication Failures
  file: DriverAuthController.java
  line: login()
  title: No brute-force / rate-limiting protection
  attack_vector: Endpoint accepts unlimited login attempts, enabling credential stuffing and password spraying.
  evidence: No lockout, no rate limiter, no CAPTCHA, no failed-attempt counter.
  fix: Add per-account lockout (e.g., 5 failures → temporary lock), per-IP rate limiting (bucket4j / Spring Cloud Gateway), and consider CAPTCHA after N failures. Log failed attempts for monitoring (A09).

SECURITY_FINDING:
  id: SF-006
  severity: HIGH
  owasp_ref: A05:2021 - Security Misconfiguration
  file: DriverAuthController.java
  line: updateRole() and verifyToken()
  title: JWT parsing without exception handling — exceptions leak to client
  attack_vector: parseToken() on an invalid/expired/tampered token throws JwtException (or similar). Uncaught, Spring returns a 500 with stack trace, leaking implementation details. Worse, if the underlying library's parse method doesn't validate signature by default (depends on builder), tampered tokens may be accepted.
  evidence: "Claims claims = tokenProvider.parseToken(token);" — no try/catch, no explicit signature/expiry validation visible at the controller boundary.
  fix: Move JWT validation into a Spring Security filter (OncePerRequestFilter) that returns 401 on any JWT failure. Ensure parseToken uses parseClaimsJws (validates signature) and checks exp. Never let JwtException propagate to the client.

SECURITY_FINDING:
  id: SF-007
  severity: HIGH
  owasp_ref: A04:2021 - Insecure Design
  file: DriverAuthController.java
  line: updateRole() — Authorization header handling
  title: Unsafe Authorization header parsing
  attack_vector: authHeader.replace("Bearer ", "") (a) NPEs if header missing (500 to client), (b) replaces every occurrence anywhere in the string, (c) accepts tokens with no "Bearer " prefix at all. Combined with SF-006, malformed inputs leak stack traces.
  evidence: "String token = authHeader.replace(\"Bearer \", \"\");"
  fix: Validate header is non-null, startsWith("Bearer "), then substring(7). Better: extract via Spring Security filter and inject Authentication into the controller.

SECURITY_FINDING:
  id: SF-008
  severity: MEDIUM
  owasp_ref: A09:2021 - Security Logging and Monitoring Failures
  file: DriverAuthController.java
  line: All endpoints
  title: No audit logging of authentication events or privilege changes
  attack_vector: Successful/failed logins and role changes are not logged. Compromise/insider abuse cannot be detected or investigated.
  evidence: No logger present; no audit trail on updateRole (a CRITICAL state-change operation).
  fix: Log auth events (success/failure, IP, user) and audit every role change with actor, target, old role, new role, timestamp. Integrate with AgentAuditService pattern used elsewhere in Sovereign.

SECURITY_FINDING:
  id: SF-009
  severity: MEDIUM
  owasp_ref: A04:2021 - Insecure Design
  file: DriverAuthController.java
  line: login()
  title: Use of generic RuntimeException instead of domain exceptions
  attack_vector: Generic RuntimeException returns 500 with potential stack trace exposure depending on global handler; also violates project convention requiring domain exceptions.
  evidence: "throw new RuntimeException(\"Driver not found\")"
  fix: Use a domain-specific AuthenticationException mapped to 401 by a @ControllerAdvice.

SECURITY_FINDING:
  id: SF-010
  severity: LOW
  owasp_ref: A02:2021 - Cryptographic Failures
  file: DriverAuthController.java
  line: verifyToken()
  title: Verbose token introspection endpoint
  attack_vector: /verify echoes driverId and role back. If reachable unauthenticated (no global security config shown), it becomes an oracle for confirming token validity and harvesting claim contents. Not a vuln in itself, but increases blast radius of any token leak.
  evidence: Returns subject + role of any parseable token; no audit; no caller check.
  fix: Restrict to authenticated principal only; consider removing the role echo or requiring the caller match the token subject.
```

---

## Prose Summary

### 🔴 CRITICAL — Block immediately
- **SF-001 · updateRole()** — Missing authorization. Any authenticated user can promote anyone to ADMIN. Add `@PreAuthorize("hasRole('ADMIN')")` and verify claims.
- **SF-002 · hashPassword()** — Unsalted SHA-256. Replace with BCrypt/Argon2 via `PasswordEncoder`.

### 🟠 HIGH — Escalate for review
- **SF-003 · login()** — `String.equals()` timing leak → use `PasswordEncoder.matches()`.
- **SF-004 · login()** — Username enumeration → unify error responses.
- **SF-005 · login()** — No brute-force protection → add lockout + rate limiting.
- **SF-006 · updateRole()/verifyToken()** — Unhandled JWT exceptions leak stack traces; signature validation must be explicit. Move to Spring Security filter.
- **SF-007 · updateRole()/verifyToken()** — Unsafe `Authorization` header parsing (NPE, no prefix check).

### 🟡 MEDIUM — Fix this sprint
- **SF-008 · all endpoints** — No audit logging on auth/role changes.
- **SF-009 · login()** — Generic `RuntimeException` violates domain-exception convention and risks 500 leakage.

### 🟢 LOW — Tech debt
- **SF-010 · verifyToken()** — Verbose token introspection oracle.

### ⚪ Code Quality Notes (not security findings)
- Controller mixes auth concerns with role administration — split into `AuthController` and `DriverAdminController`.
- Business logic (auth, role mutation) sits in the web layer; per Sovereign hexagonal rules this belongs in `application` use cases with `infrastructure` adapters.

### Recall check (OWASP Top 10 2021)
- A01 Broken Access Control — **SF-001** ✓
- A02 Cryptographic Failures — **SF-002, SF-003, SF-010** ✓
- A03 Injection — No evidence (JPA `findByEmail`/`findById` are parameterised).
- A04 Insecure Design — **SF-007, SF-009** ✓
- A05 Security Misconfiguration — **SF-006** ✓
- A06 Vulnerable Components — Not assessable from snippet (check `commons-codec` version separately).
- A07 Auth Failures — **SF-004, SF-005** ✓
- A08 Software/Data Integrity — No evidence in snippet.
- A09 Logging/Monitoring — **SF-008** ✓
- A10 SSRF — Not applicable (no outbound requests).

### Verdict
**BLOCKED** — Two CRITICAL findings (privilege escalation + insecure password hashing) must be fixed before this controller can be merged. Five HIGH findings should be addressed in the same PR; recommend re-review after fixes.

## Grading Reasoning
This is a strong security review with excellent recall and solid technical evidence, but it loses points for some low-confidence extra findings and one key severity inflation (weak hashing marked CRITICAL instead of HIGH).

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Recall | 40% | 100 | All 3 planted vulnerabilities were identified: privilege escalation ('Missing authorization check on privilege-changing endpoint' with 'Any authenticated driver ... can ... newRole="ADMIN"'), weak password hashing ('Insecure password hashing (unsalted SHA-256)'), and JWT expiry/validation gap ('Ensure parseToken uses parseClaimsJws ... and checks exp'). |
| Precision | 30% | 70 | The report contains many valid findings, but also several overreaches/noise across 10 total issues. Strong true positives include SF-001, SF-002, and JWT validation concerns in SF-006; weaker/speculative items include SF-009 ('Use of generic RuntimeException...') and SF-010 ('Verbose token introspection endpoint'). With 10 flagged issues, precision is decent but not tight. |
| Severity accuracy | 30% | 67 | For planted vulns: privilege escalation was correctly CRITICAL (pass), JWT expiry/validation concern was treated as HIGH in SF-006 (pass), but weak password hashing was labeled CRITICAL in SF-002 while expected HIGH (fail). That yields 2/3 correct severity classifications. |

## Overall Score: 81.1/100
