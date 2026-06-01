# Trace: security-review — 2026-W23

## Metadata
- Prompt ID: P4-compliance-webhook
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-06-01T21:58:36Z
- Duration: 123.1s
- Estimated cost (USD): 0.2074
- Executor tokens (est.): prompt=600 / completion=2345 / total=2945
- Grader tokens (est.):   prompt=3371 / completion=377 / total=3748
- Tool calls (heuristic): 0

## Prompt Sent
Review the following Java REST controller for security vulnerabilities.
Focus on OWASP Top 10. Report what you find with severity levels.

@RestController
@RequestMapping("/api/compliance")
public class ComplianceWebhookHandler {

    private final ComplianceService complianceService;
    private final String webhookSecret;

    public ComplianceWebhookHandler(ComplianceService complianceService,
                                     @Value("${compliance.webhook.secret}") String webhookSecret) {
        this.complianceService = complianceService;
        this.webhookSecret = webhookSecret;
    }

    @PostMapping("/webhook")
    public ResponseEntity<String> handleWebhook(@RequestBody String body,
                                                 @RequestHeader(value = "X-Signature", required = false) String signature) {
        if (signature != null) {
            String expected = HmacUtils.hmacSha256Hex(webhookSecret, body);
            if (!expected.equals(signature)) {
                return ResponseEntity.status(403).body("Invalid signature");
            }
        }

        ObjectMapper mapper = new ObjectMapper();
        try {
            ComplianceEvent event = mapper.readValue(body, ComplianceEvent.class);
            complianceService.processEvent(event);
            return ResponseEntity.ok("Processed: " + event.getEventId());
        } catch (Exception e) {
            return ResponseEntity.badRequest().body("Error: " + e.getMessage());
        }
    }

    @PostMapping("/events")
    public ResponseEntity<String> createEvent(@RequestBody Map<String, Object> eventData) {
        ComplianceEvent event = new ComplianceEvent();
        eventData.forEach((key, value) -> {
            try {
                var field = ComplianceEvent.class.getDeclaredField(key);
                field.setAccessible(true);
                field.set(event, value);
            } catch (Exception ignored) {}
        });

        complianceService.processEvent(event);
        return ResponseEntity.ok("Created: " + event.getEventId());
    }

    @GetMapping("/events/{eventId}")
    public ResponseEntity<ComplianceEvent> getEvent(@PathVariable String eventId,
                                                     @RequestParam(required = false) String nonce) {
        ComplianceEvent event = complianceService.findById(eventId);
        return ResponseEntity.ok(event);
    }
}

## Raw Output
# Security Review: ComplianceWebhookHandler

```
SECURITY_FINDING:
  id: SF-001
  severity: CRITICAL
  owasp_ref: A07:2021 (Identification and Authentication Failures) + A08:2021 (Software and Data Integrity Failures)
  file: ComplianceWebhookHandler.java
  line: 18-22 (handleWebhook signature check)
  title: Webhook signature verification bypassed when X-Signature header is absent
  attack_vector: Attacker omits the X-Signature header entirely; the `if (signature != null)` branch is skipped and the payload is processed as if authenticated. Full webhook forgery — attacker can inject arbitrary ComplianceEvent payloads, triggering downstream compliance processing with attacker-controlled data.
  evidence: "if (signature != null) { ... verify ... } // no else branch — unsigned requests fall through to processEvent()"
  fix: Make signature mandatory. Reject with 401 when header missing OR signature invalid. Header `required = false` should be `true`, or explicitly null-check and reject.

SECURITY_FINDING:
  id: SF-002
  severity: CRITICAL
  owasp_ref: A02:2021 (Cryptographic Failures)
  file: ComplianceWebhookHandler.java
  line: 20-21
  title: Non-constant-time HMAC comparison vulnerable to timing attack
  attack_vector: `String.equals()` short-circuits on first mismatching byte. An attacker can measure response-time differences to recover the valid HMAC signature byte-by-byte, then forge arbitrary webhook payloads.
  evidence: "if (!expected.equals(signature))"
  fix: Use `MessageDigest.isEqual(expected.getBytes(StandardCharsets.UTF_8), signature.getBytes(StandardCharsets.UTF_8))` or `java.security.MessageDigest.isEqual` / Guava `HashCode.equals` for constant-time comparison.

SECURITY_FINDING:
  id: SF-003
  severity: CRITICAL
  owasp_ref: A08:2021 (Software and Data Integrity Failures) / Mass Assignment
  file: ComplianceWebhookHandler.java
  line: 35-44 (createEvent)
  title: Unrestricted reflective field assignment enables mass-assignment and privilege escalation
  attack_vector: Caller POSTs arbitrary JSON keys; the handler reflectively writes to ANY declared field on ComplianceEvent — including `setAccessible(true)` on private fields. Attacker can set internal flags such as `approved`, `validated`, `tenantId`, `auditOverride`, `signature`, etc., bypassing all domain invariants. No authentication is shown on this endpoint either.
  evidence: "eventData.forEach((key, value) -> { var field = ComplianceEvent.class.getDeclaredField(key); field.setAccessible(true); field.set(event, value); })"
  fix: Remove reflection entirely. Bind to an explicit DTO with only safe, whitelisted fields (`@JsonCreator` / typed `@RequestBody ComplianceEventCreateRequest`). Validate with `@Valid` + bean validation constraints.

SECURITY_FINDING:
  id: SF-004
  severity: HIGH
  owasp_ref: A01:2021 (Broken Access Control)
  file: ComplianceWebhookHandler.java
  line: 47-51 (getEvent) and 35 (createEvent)
  title: No authentication/authorisation on event read and create endpoints
  attack_vector: `/api/compliance/events` (POST) and `/api/compliance/events/{eventId}` (GET) have no `@PreAuthorize`, no tenant scoping, no IDOR protection. Any caller can enumerate eventIds and read other tenants' compliance events, or create events impersonating any source.
  evidence: "No @PreAuthorize, @Secured, or tenant filter on either method; findById(eventId) returns event without ownership check"
  fix: Add `@PreAuthorize("hasRole('COMPLIANCE_READER')")` (or equivalent), scope queries by authenticated principal/tenant, and return 404 (not 403) on cross-tenant access to avoid existence disclosure.

SECURITY_FINDING:
  id: SF-005
  severity: HIGH
  owasp_ref: A09:2021 (Security Logging and Monitoring Failures) + A04:2021 (Insecure Design)
  file: ComplianceWebhookHandler.java
  line: 28 (catch Exception e ... e.getMessage())
  title: Internal exception messages echoed to untrusted callers
  attack_vector: Jackson/JPA/reflection exceptions returned verbatim in the response body leak class names, field names, stack-trace fragments, SQL fragments, and internal paths — aiding reconnaissance. Also: failed signature verification, mass-assignment attempts, and parse failures are not audit-logged.
  evidence: "return ResponseEntity.badRequest().body(\"Error: \" + e.getMessage());"
  fix: Return a generic message ("Invalid payload") with a correlation id; log the full exception server-side at WARN with request metadata. Audit-log all signature failures.

SECURITY_FINDING:
  id: SF-006
  severity: MEDIUM
  owasp_ref: A04:2021 (Insecure Design)
  file: ComplianceWebhookHandler.java
  line: 47 (getEvent nonce param)
  title: Unused `nonce` parameter suggests broken replay-protection design
  attack_vector: Parameter is accepted but never validated — gives a false sense of replay protection. Combined with SF-001, webhook replay is trivially possible (no timestamp window, no nonce store).
  evidence: "@RequestParam(required = false) String nonce  // never read"
  fix: Either remove the parameter or implement a proper replay window (timestamp header + nonce cache with TTL, signed together with the body).

SECURITY_FINDING:
  id: SF-007
  severity: MEDIUM
  owasp_ref: A05:2021 (Security Misconfiguration)
  file: ComplianceWebhookHandler.java
  line: 14 (@Value injection)
  title: No validation that webhook secret is present/strong at startup
  attack_vector: If `compliance.webhook.secret` is empty or unset, `HmacUtils.hmacSha256Hex("", body)` still computes a deterministic HMAC — attacker who knows the secret is empty can forge signatures. Combined with SF-001, very low effort.
  evidence: "@Value(\"${compliance.webhook.secret}\") String webhookSecret  // no @NotBlank validation, no length check"
  fix: Validate at construction: `Objects.requireNonNull` + minimum length (e.g. ≥ 32 chars). Fail-fast on startup if missing.

SECURITY_FINDING:
  id: SF-008
  severity: LOW
  owasp_ref: A04:2021 (Insecure Design)
  file: ComplianceWebhookHandler.java
  line: 25 (new ObjectMapper())
  title: ObjectMapper instantiated per request
  attack_vector: Minor DoS amplifier — ObjectMapper construction is expensive; per-request allocation increases the cost of payload floods. Also bypasses any centrally configured security defaults (e.g. `FAIL_ON_UNKNOWN_PROPERTIES`, default typing disabled).
  fix: Inject a singleton `ObjectMapper` bean configured with secure defaults (no default typing, fail on unknown properties, size limits).
```

---

## Prose Summary

### 🔴 CRITICAL — Block immediately
- **SF-001 · L18-22** — Signature check is skipped when `X-Signature` header is absent. Full webhook forgery. Make header mandatory and reject null/invalid signatures with 401.
- **SF-002 · L20-21** — `String.equals` comparison of HMACs is timing-attack-vulnerable. Use `MessageDigest.isEqual` for constant-time comparison.
- **SF-003 · L35-44** — `createEvent` reflectively writes any client-supplied key to any declared field (incl. private), enabling mass-assignment and trust-flag tampering. Replace with an explicit, validated DTO.

### 🟠 HIGH — Escalate for review
- **SF-004 · L35, L47** — `/events` POST and `/events/{eventId}` GET have no auth, no tenant scoping, no IDOR check. Add `@PreAuthorize` + ownership filtering.
- **SF-005 · L28** — Internal exception messages returned to caller; signature failures not audit-logged. Return generic error + correlation id; audit all signature failures.

### 🟡 MEDIUM — Fix this sprint
- **SF-006 · L47** — Unused `nonce` parameter; no real replay protection. Implement timestamp+nonce signed window or remove.
- **SF-007 · L14** — Webhook secret not validated at startup; empty/short secret accepted. Add `@NotBlank` + minimum length, fail-fast.

### 🟢 LOW — Tech debt
- **SF-008 · L25** — Per-request `new ObjectMapper()`. Inject singleton with hardened config.

### ⚪ Code Quality Notes (not security findings)
- `ComplianceEvent event = complianceService.findById(eventId)` returns directly without null check — would NPE on missing id (reliability, not security).
- `catch (Exception ignored) {}` in `createEvent` silently swallows reflection errors — observability concern (handled separately).

### OWASP Top 10 Recall Check
- A01 Broken Access Control — **SF-004**
- A02 Cryptographic Failures — **SF-002**
- A03 Injection — No direct SQL/OS injection in this controller (depends on `ComplianceService` internals, out of scope).
- A04 Insecure Design — **SF-006, SF-008**
- A05 Security Misconfiguration — **SF-007**
- A06 Vulnerable Components — Apache Commons `HmacUtils` is acceptable but ensure version ≥ 1.15; not flaggable without `pom.xml`.
- A07 Identification & Auth Failures — **SF-001**
- A08 Software & Data Integrity Failures — **SF-001, SF-003**
- A09 Security Logging & Monitoring Failures — **SF-005**
- A10 SSRF — No evidence of vulnerability found (no outbound URL handling in this file).

### Verdict
**BLOCKED** — 3 CRITICAL findings (SF-001, SF-002, SF-003) must be fixed before this controller can be merged. SF-001 and SF-003 are independently exploitable for full integrity compromise of the compliance pipeline; SF-002 makes the (broken) signature check additionally recoverable. Recommend full rewrite of both `handleWebhook` (mandatory signature, constant-time compare, audit logging) and `createEvent` (typed DTO, auth, validation) before re-review.

## Grading Reasoning
This is a strong review with excellent recall and good technical depth, but it over-flags some issues and overstates at least one planted severity (mass assignment). Net result is good but not near-perfect calibration.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| recall | 40% | 100 | The output explicitly identified all 3 planted vulnerabilities: HMAC bypass ('if (signature != null) ... unsigned requests fall through'), mass assignment ('reflectively writes to ANY declared field ... setAccessible(true)'), and replay weakness ('nonce parameter ... never validated', 'no timestamp window, no nonce store'). So planted vulns found = 3/3. |
| precision | 30% | 75 | The agent reported 8 total findings (SF-001..SF-008). Several are clearly valid (SF-001, SF-003, SF-006, SF-005 bonus), but at least some are likely overreach/speculative for this snippet (e.g., SF-008 ObjectMapper-per-request framed as security, SF-007 secret-strength/startup validation claim). Using true positives ≈ 6 of 8 gives ~75. |
| severity accuracy | 30% | 67 | Against expected severities: HMAC bypass was correctly marked CRITICAL, replay was correctly marked MEDIUM, but mass assignment was expected HIGH and marked CRITICAL ('severity: CRITICAL ... mass-assignment'). That is 2/3 correct severity classifications. |

## Overall Score: 82.6/100
