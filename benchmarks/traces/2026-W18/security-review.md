# Trace: security-review — 2026-W18

## Metadata
- Prompt ID: P3-fleet-report-exporter
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-04-27T22:08:23Z
- Duration: 111.2s

## Prompt Sent
Review the following Java REST controller for security vulnerabilities.
Focus on OWASP Top 10. Report what you find with severity levels.

@RestController
@RequestMapping("/api/reports")
public class FleetReportExporter {

    private final ReportService reportService;
    private final RestTemplate restTemplate;

    public FleetReportExporter(ReportService reportService, RestTemplate restTemplate) {
        this.reportService = reportService;
        this.restTemplate = restTemplate;
    }

    @GetMapping("/export/{fleetId}")
    public ResponseEntity<byte[]> exportReport(@PathVariable String fleetId,
                                                @RequestParam String filename) throws IOException {
        byte[] reportData = reportService.generateReport(fleetId);
        Path outputPath = Paths.get("/tmp/reports/" + filename);
        Files.write(outputPath, reportData);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentDispositionFormData("attachment", filename);
        headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
        return new ResponseEntity<>(reportData, headers, HttpStatus.OK);
    }

    @PostMapping("/webhook")
    public ResponseEntity<String> receiveWebhook(@RequestBody WebhookPayload payload) {
        String callbackUrl = payload.getCallbackUrl();
        ResponseEntity<String> response = restTemplate.getForEntity(callbackUrl, String.class);

        reportService.processWebhookData(response.getBody());
        return ResponseEntity.ok("Processed");
    }

    @PostMapping("/import")
    public ResponseEntity<String> importData(@RequestBody String rawJson) {
        ObjectMapper mapper = new ObjectMapper();
        try {
            Map<String, Object> data = mapper.readValue(rawJson, new TypeReference<>() {});
            String logEntry = "Import received: fleet=" + data.get("fleet_id")
                    + " user=" + data.get("user") + " action=" + data.get("action");
            Logger.getLogger("reports").info(logEntry);

            reportService.importData(data);
            return ResponseEntity.ok("Imported");
        } catch (Exception e) {
            return ResponseEntity.badRequest().body("Parse error: " + e.getMessage());
        }
    }
}

## Raw Output
# Security Review: FleetReportExporter

## Part 1 — Structured Findings

```
SECURITY_FINDING:
  id: SF-001
  severity: CRITICAL
  owasp_ref: A01:2021 (Broken Access Control) / A03:2021 (Injection - Path Traversal)
  file: FleetReportExporter.java
  line: ~17-20 (exportReport)
  title: Path traversal via unsanitised `filename` request parameter
  attack_vector: Attacker calls GET /api/reports/export/123?filename=../../etc/passwd or filename=../../home/app/.ssh/authorized_keys. `Paths.get("/tmp/reports/" + filename)` resolves outside /tmp/reports, allowing arbitrary file write (overwrite system files, plant webshells, escalate to RCE).
  evidence: 'Path outputPath = Paths.get("/tmp/reports/" + filename); Files.write(outputPath, reportData);'
  fix: |
    1. Validate filename against an allowlist regex (e.g., ^[A-Za-z0-9._-]{1,128}$).
    2. Resolve and canonicalise: Path base = Paths.get("/tmp/reports").toAbsolutePath().normalize();
       Path target = base.resolve(filename).normalize();
       if (!target.startsWith(base)) throw new SecurityException(...);
    3. Better: don't write to disk at all — stream `reportData` directly in the ResponseEntity. The file write is unused (the response body is `reportData`, not the file).

SECURITY_FINDING:
  id: SF-002
  severity: CRITICAL
  owasp_ref: A10:2021 (Server-Side Request Forgery)
  file: FleetReportExporter.java
  line: ~28-31 (receiveWebhook)
  title: Unrestricted SSRF via attacker-controlled callbackUrl
  attack_vector: Attacker POSTs {"callbackUrl":"http://169.254.169.254/latest/meta-data/iam/security-credentials/"} (AWS IMDS) or http://localhost:8080/actuator/env, file:///etc/passwd, http://internal-service/admin. The response body is then fed into reportService.processWebhookData — leaking internal service responses, cloud credentials, or pivoting into internal network. Classic SSRF leading to credential theft in AWS.
  evidence: 'String callbackUrl = payload.getCallbackUrl(); ResponseEntity<String> response = restTemplate.getForEntity(callbackUrl, String.class);'
  fix: |
    1. Validate callbackUrl against a strict allowlist of registered customer domains.
    2. Resolve hostname and reject RFC1918 / loopback / link-local / IMDS (169.254.169.254) addresses BEFORE the request.
    3. Restrict scheme to https only; disable redirects on the RestTemplate.
    4. Require IMDSv2 on EC2 hosts (defence-in-depth).
    5. Consider out-of-band webhook verification (signed challenge) instead of synchronous fetch.

SECURITY_FINDING:
  id: SF-003
  severity: HIGH
  owasp_ref: A01:2021 (Broken Access Control)
  file: FleetReportExporter.java
  line: 1-12 (class & all endpoints)
  title: No authentication or authorisation on fleet data endpoints
  attack_vector: No @PreAuthorize, no tenant/fleet ownership check. Any authenticated (or unauthenticated, depending on Spring Security config) caller can export any fleetId — IDOR. Customer A reads Customer B's fleet reports by guessing/iterating fleetId.
  evidence: 'public ResponseEntity<byte[]> exportReport(@PathVariable String fleetId, ...)' — no authz check, no tenant scoping.
  fix: |
    1. Add @PreAuthorize("@fleetAccessGuard.canAccess(authentication, #fleetId)") or equivalent.
    2. Enforce tenant scoping in ReportService against the authenticated principal.
    3. Verify Spring Security config requires authentication on /api/reports/**.

SECURITY_FINDING:
  id: SF-004
  severity: HIGH
  owasp_ref: A05:2021 (Security Misconfiguration) / A08:2021 (Insecure Deserialization)
  file: FleetReportExporter.java
  line: ~37-40 (importData)
  title: Untyped Map<String,Object> deserialisation + unvalidated propagation to service layer
  attack_vector: Endpoint accepts arbitrary JSON, parses to Map<String,Object>, and forwards to reportService.importData(data) with zero schema validation. Depending on downstream handling (especially if any reflective/SpEL/template processing is done), this enables mass-assignment, type confusion, or injection. Also no size limit — DoS via large payload.
  evidence: 'Map<String, Object> data = mapper.readValue(rawJson, new TypeReference<>() {}); reportService.importData(data);'
  fix: |
    1. Define a strongly-typed DTO with @Valid + bean-validation constraints.
    2. Enforce request size limits at the framework (Spring) and reverse proxy.
    3. Reject unknown fields (FAIL_ON_UNKNOWN_PROPERTIES = true).

SECURITY_FINDING:
  id: SF-005
  severity: HIGH
  owasp_ref: A09:2021 (Security Logging & Monitoring Failures) / A03:2021 (Log Injection)
  file: FleetReportExporter.java
  line: ~41-43 (importData logging)
  title: Log forging / log injection via unsanitised user input
  attack_vector: data.get("user") and data.get("action") are attacker-controlled strings concatenated into a log line. Attacker injects "alice\n2026-04-28 INFO admin granted role=SUPERUSER" — forging audit log entries to hide activity or frame other users. CRLF injection also enables log-aggregation parser confusion.
  evidence: '"Import received: fleet=" + data.get("fleet_id") + " user=" + data.get("user") + " action=" + data.get("action")'
  fix: |
    1. Use parameterised SLF4J logging: log.info("Import received: fleet={} user={} action={}", fleetId, user, action) — and ensure a CRLF-stripping pattern layout (replace %m with %replace(%m){'[\r\n]', '_'}).
    2. Switch from java.util.logging to SLF4J/Logback (project standard).
    3. Validate user/action against an allowlist before logging.

SECURITY_FINDING:
  id: SF-006
  severity: MEDIUM
  owasp_ref: A04:2021 (Insecure Design) / A05:2021
  file: FleetReportExporter.java
  line: ~44-46 (catch block)
  title: Verbose exception message returned to client
  attack_vector: Returning e.getMessage() to the caller leaks Jackson parser internals, class names, field paths, and possibly stack details — aiding attackers in fingerprinting libraries and crafting deserialisation payloads.
  evidence: 'return ResponseEntity.badRequest().body("Parse error: " + e.getMessage());'
  fix: |
    1. Return a generic message ("Invalid request payload"); log the full exception server-side with a correlation ID.
    2. Add a @ControllerAdvice global handler with sanitised responses.

SECURITY_FINDING:
  id: SF-007
  severity: MEDIUM
  owasp_ref: A05:2021 (Security Misconfiguration)
  file: FleetReportExporter.java
  line: ~22-24 (Content-Disposition header)
  title: Response splitting / header injection via unvalidated filename
  attack_vector: Same `filename` param is reflected into Content-Disposition header. While Spring's HttpHeaders generally encodes, raw CR/LF or quote characters in filename can cause UA-side filename smuggling and, in some configurations, header injection. Also enables reflected-download attacks (RFD) where attacker chooses .html/.bat extension.
  evidence: 'headers.setContentDispositionFormData("attachment", filename);'
  fix: |
    1. Sanitise filename to allowlist charset before using in header.
    2. Force a server-controlled filename derived from fleetId + timestamp.

SECURITY_FINDING:
  id: SF-008
  severity: MEDIUM
  owasp_ref: A04:2021 (Insecure Design)
  file: FleetReportExporter.java
  line: ~17-25 (exportReport)
  title: Disk write of sensitive report data without cleanup or access controls
  attack_vector: Reports are written to /tmp/reports/<filename> with default permissions and never deleted. Co-tenant users on the host (or other processes) may read PII fleet data. Combined with SF-001 path traversal, attacker can also *read* arbitrary files indirectly (overwrite known-served files).
  evidence: 'Path outputPath = Paths.get("/tmp/reports/" + filename); Files.write(outputPath, reportData);'
  fix: Remove the disk write entirely — it appears unused. If retention is needed, write to a permission-restricted directory and schedule cleanup.

SECURITY_FINDING:
  id: SF-009
  severity: LOW
  owasp_ref: A04:2021
  file: FleetReportExporter.java
  line: ~36 (importData)
  title: No request size limit / rate limiting
  attack_vector: Unbounded @RequestBody String and Map deserialisation enables memory-exhaustion DoS (e.g., deeply nested or huge JSON).
  evidence: 'public ResponseEntity<String> importData(@RequestBody String rawJson)'
  fix: Configure spring.servlet.multipart.max-request-size and Jackson StreamReadConstraints; add per-endpoint rate limiting.
```

---

## Part 2 — Prose Summary

## Security Review: FleetReportExporter

### 🔴 CRITICAL — Block immediately
- **SF-001 · exportReport (line ~19)** — Path traversal: unsanitised `filename` concatenated into `/tmp/reports/` path. Attacker can write arbitrary files (e.g., `../../etc/cron.d/evil`) leading to RCE. Validate against allowlist regex and canonicalise via `Path.normalize()` + `startsWith(base)` check; preferably remove the disk write entirely.
- **SF-002 · receiveWebhook (line ~30)** — Full SSRF: attacker-controlled `callbackUrl` fetched by RestTemplate with no validation. Trivially exploitable to read AWS IMDS credentials (`http://169.254.169.254/...`), internal Actuator endpoints, or `file://` URIs. Enforce scheme allowlist (https only), block RFC1918/loopback/link-local IPs after DNS resolution, and require an allowlist of registered domains.

### 🟠 HIGH — Escalate for review
- **SF-003 · class-level** — No authentication/authorisation on fleet endpoints. Direct IDOR on `fleetId`. Add `@PreAuthorize` and enforce tenant scoping in `ReportService`.
- **SF-004 · importData (line ~38)** — Untyped `Map<String,Object>` deserialisation forwarded to service. Replace with strongly-typed `@Valid` DTO; enforce size limits.
- **SF-005 · importData (line ~41)** — Log forging via unsanitised `user`/`action` concatenation. Switch to parameterised SLF4J logging and strip CR/LF.

### 🟡 MEDIUM — Fix this sprint
- **SF-006 · importData (line ~45)** — `e.getMessage()` returned to client leaks parser internals. Use generic error + correlation ID via `@ControllerAdvice`.
- **SF-007 · exportReport (line ~22)** — `filename` reflected into Content-Disposition; potential RFD/header smuggling. Generate server-side filename.
- **SF-008 · exportReport (line ~19)** — Sensitive report bytes written to world-readable `/tmp` with no cleanup. Remove the unused disk write.

### 🟢 LOW — Tech debt
- **SF-009 · importData** — No request size cap; DoS via large/deep JSON. Configure Jackson `StreamReadConstraints` and request size limits.

### ⚪ Code Quality Notes (not security findings)
- `Logger.getLogger("reports")` (java.util.logging) is inconsistent with Spring Boot's SLF4J/Logback standard — refactor for consistency.
- `ObjectMapper` instantiated per request — make it a singleton bean. (Not a security issue.)
- The `Files.write` result of `exportReport` is never used; the response body is `reportData` directly. Dead code worth removing (and removing it eliminates SF-001 + SF-008).

### Recall check — OWASP Top 10 2021 coverage
- A01 Broken Access Control — SF-001, SF-003 ✓
- A02 Cryptographic Failures — No evidence of vulnerability found (no crypto in this controller).
- A03 Injection — SF-001 (path), SF-005 (log) ✓
- A04 Insecure Design — SF-006, SF-008, SF-009 ✓
- A05 Security Misconfiguration — SF-004, SF-007 ✓
- A06 Vulnerable Components — Out of scope (no dependency manifest in this snippet).
- A07 Identification & Auth Failures — Covered under SF-003.
- A08 Insecure Deserialization — SF-004 ✓
- A09 Security Logging & Monitoring — SF-005, SF-006 ✓
- A10 SSRF — SF-002 ✓

### Verdict
**BLOCKED** — 2 CRITICAL (path traversal, SSRF) + 3 HIGH findings. Do not promote. SF-001 and SF-002 are independently exploitable for full system compromise (RCE-class and credential-theft-class respectively). SF-003 (missing authz) means every other finding is reachable by unauthenticated or cross-tenant callers. Fix all CRITICAL and HIGH items before re-review; MEDIUM items must be resolved in the same sprint.

## Grading Reasoning
Strong recall but over-reporting and severity inflation reduced calibration. The review is useful, but precision and severity alignment with expected benchmark levels are only moderate.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Recall | 40% | 100 | All 3 planted vulnerabilities were identified: path traversal ('SF-001 ... Path traversal via unsanitised `filename`'), SSRF ('SF-002 ... Unrestricted SSRF via attacker-controlled callbackUrl'), and log injection ('SF-005 ... Log forging / log injection via unsanitised user input'). |
| Precision | 30% | 44 | The agent reported 9 findings (SF-001 to SF-009), but only ~4 are clearly supported by the prompt/ground truth (the 3 planted issues plus bonus info leak SF-006). Several others are speculative or context-dependent from snippet alone (e.g., SF-003 authz/IDOR assumption, SF-004 'insecure deserialization' framing, SF-007 header injection despite framework handling, SF-008 /tmp exposure assumption, SF-009 generic rate-limit/size-limit hardening). |
| Severity accuracy | 30% | 33 | Only 1 of 3 planted severities matches ground truth: path traversal correctly marked CRITICAL. SSRF was overstated as CRITICAL (expected HIGH), and log injection was overstated as HIGH (expected MEDIUM). |

## Overall Score: 63.1/100
