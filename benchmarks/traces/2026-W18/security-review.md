# Trace: security-review — 2026-W18

## Metadata
- Prompt ID: P3-fleet-report-exporter
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-04-27T08:29:57Z
- Duration: 138.6s

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
  owasp_ref: A01:2021 (Broken Access Control) / CWE-22 Path Traversal
  file: FleetReportExporter.java
  line: 17-19 (exportReport)
  title: Path Traversal via unsanitised filename parameter
  attack_vector: Attacker calls GET /api/reports/export/{fleetId}?filename=../../etc/passwd or
                 ?filename=../../../home/app/.ssh/authorized_keys — Files.write() will resolve
                 the relative path components and overwrite ARBITRARY files on the host filesystem
                 with attacker-influenced report bytes. This is a write-anywhere primitive →
                 trivial RCE (overwrite cron, systemd unit, .ssh/authorized_keys, jar on classpath).
  evidence: 'Path outputPath = Paths.get("/tmp/reports/" + filename); Files.write(outputPath, reportData);'
  fix: 1) Reject filenames containing "/", "\\", "..", or null bytes.
       2) Resolve and canonicalise: Path base = Paths.get("/tmp/reports").toAbsolutePath().normalize();
          Path resolved = base.resolve(filename).normalize();
          if (!resolved.startsWith(base)) throw new SecurityException("Path traversal");
       3) Better: don't use the client-supplied filename for the FS path at all — generate a
          server-side UUID and only use the client filename in the Content-Disposition header
          (after sanitising for header injection).
       4) Question whether persisting to /tmp at all is needed — the bytes are returned in the
          response body anyway; the disk write appears unused (dead + dangerous).

SECURITY_FINDING:
  id: SF-002
  severity: CRITICAL
  owasp_ref: A10:2021 (Server-Side Request Forgery)
  file: FleetReportExporter.java
  line: 28-30 (receiveWebhook)
  title: Unvalidated SSRF via attacker-controlled callbackUrl
  attack_vector: Attacker POSTs {"callbackUrl":"http://169.254.169.254/latest/meta-data/iam/security-credentials/"}
                 (AWS IMDS) or "http://localhost:8080/api/internal/...", "file:///etc/passwd",
                 "http://10.0.0.5:6379/" (internal Redis), etc. The server fetches the URL with
                 RestTemplate and passes the body to reportService.processWebhookData — and the
                 raw response is also returned to the attacker on most RestTemplate error paths.
                 In AWS/EC2 this is a direct path to credential theft.
  evidence: 'String callbackUrl = payload.getCallbackUrl(); restTemplate.getForEntity(callbackUrl, String.class);'
  fix: 1) Allow-list scheme (https only) and host (against an explicit allow-list of partner domains).
       2) Resolve DNS and reject RFC1918 / loopback / link-local / IMDS (169.254.0.0/16) ranges
          BEFORE the request, and re-check after redirects (disable auto-redirect on RestTemplate).
       3) Set tight connect/read timeouts; cap response size.
       4) Reconsider the design — webhooks should be PUSHED with a signed payload (HMAC), not
          require the server to call back to a client-supplied URL.

SECURITY_FINDING:
  id: SF-003
  severity: HIGH
  owasp_ref: A07:2021 (Identification and Authentication Failures) / Missing AuthZ
  file: FleetReportExporter.java
  line: class-level — entire controller
  title: No authentication/authorisation annotations; no fleet ownership check
  attack_vector: There is no @PreAuthorize, no tenant scoping, and no verification that the
                 caller's principal is entitled to fleetId. Even if Spring Security is globally
                 configured, any authenticated user (or unauthenticated, if a permitAll matcher
                 covers /api/reports/**) can export ANY fleet's report by iterating fleetId. This
                 is IDOR. Same issue applies to /import and /webhook (no caller identity bound to
                 the imported data).
  evidence: 'No @PreAuthorize / @Secured / tenant filter visible on any handler.'
  fix: Add @PreAuthorize("@fleetAccess.canRead(#fleetId, principal)") on exportReport;
       restrict /webhook and /import to a service role; verify caller-tenant matches data tenant
       inside reportService.

SECURITY_FINDING:
  id: SF-004
  severity: HIGH
  owasp_ref: A09:2021 (Security Logging and Monitoring Failures) / CWE-117 Log Injection
  file: FleetReportExporter.java
  line: 41-43 (importData)
  title: Log forging / CRLF injection via unsanitised user-controlled fields
  attack_vector: data.get("user") is attacker-controlled JSON. Supplying
                 "alice\n2026-04-27 INFO  reports: Import received: fleet=999 user=admin action=DELETE_ALL"
                 lets the attacker forge log lines, frame other users, or poison SIEM rules.
                 If logs are ever rendered in an HTML viewer, this also becomes stored XSS.
  evidence: 'Logger.getLogger("reports").info("Import received: fleet=" + data.get("fleet_id") + " user=" + data.get("user") + ...);'
  fix: Use SLF4J with parameterised messages (logger.info("Import received: fleet={} user={} action={}", ...))
       AND strip CR/LF from string fields before logging. Also avoid logging PII (user identifiers)
       at INFO without a clear retention/justification.

SECURITY_FINDING:
  id: SF-005
  severity: HIGH
  owasp_ref: A08:2021 (Software and Data Integrity Failures) / CWE-502
  file: FleetReportExporter.java
  line: 38-40 (importData)
  title: Untyped deserialisation into Map<String,Object> with no schema validation
  attack_vector: Accepting arbitrary JSON into Map<String,Object> and forwarding to
                 reportService.importData(data) defers all type/size/shape checks to downstream
                 code. Risks: (a) unexpected nested structures causing NPE/parse DoS,
                 (b) extremely large payloads (no @RequestBody size cap evident) → memory DoS,
                 (c) if reportService later passes this into JPA/JPQL/native SQL or a templating
                 engine, this is a direct injection vector. Also: if Jackson default typing is
                 ever enabled globally, untyped Map deserialisation becomes RCE.
  evidence: 'Map<String, Object> data = mapper.readValue(rawJson, new TypeReference<>() {}); reportService.importData(data);'
  fix: Define a strongly-typed DTO with @Valid, @NotNull, @Size, @Pattern constraints. Configure
       ObjectMapper with FAIL_ON_UNKNOWN_PROPERTIES=true and explicitly DISABLE default typing.
       Enforce request body size limit (server.tomcat.max-http-form-post-size or filter).

SECURITY_FINDING:
  id: SF-006
  severity: MEDIUM
  owasp_ref: A05:2021 (Security Misconfiguration) / CWE-209
  file: FleetReportExporter.java
  line: 46 (importData catch block)
  title: Verbose exception message returned to client
  attack_vector: ResponseEntity.badRequest().body("Parse error: " + e.getMessage()) leaks
                 internal parser state, field names, line/column offsets, and potentially class
                 names — useful for crafting follow-up payloads and fingerprinting versions.
  evidence: 'return ResponseEntity.badRequest().body("Parse error: " + e.getMessage());'
  fix: Return a generic message ("Invalid request payload") with a correlation ID; log the full
       exception server-side only. Centralise via @ControllerAdvice.

SECURITY_FINDING:
  id: SF-007
  severity: MEDIUM
  owasp_ref: A03:2021 (Injection) / CWE-93 + RFC 6266
  file: FleetReportExporter.java
  line: 21 (exportReport)
  title: HTTP response header injection / unsafe Content-Disposition filename
  attack_vector: setContentDispositionFormData("attachment", filename) with an unsanitised
                 filename can contain CR/LF (HTTP response splitting on older containers) or
                 quote/encoding tricks that confuse browsers into saving with a different
                 extension (e.g. "report.pdf\";x.html") — aiding phishing / reflected file
                 download attacks.
  evidence: 'headers.setContentDispositionFormData("attachment", filename);'
  fix: Validate filename against ^[A-Za-z0-9._-]{1,128}$; reject otherwise. Use
       ContentDisposition.attachment().filename(safe, StandardCharsets.UTF_8).build().

SECURITY_FINDING:
  id: SF-008
  severity: MEDIUM
  owasp_ref: A04:2021 (Insecure Design)
  file: FleetReportExporter.java
  line: 28-32 (receiveWebhook)
  title: No webhook authenticity check (HMAC/signature)
  attack_vector: /webhook accepts any POST and acts on it (triggers an outbound HTTP call,
                 ingests the response). Without HMAC/signature verification or mTLS, anyone on
                 the internet can drive this endpoint — amplifying SF-002 and enabling abuse of
                 the service as an open HTTP proxy / scanner.
  evidence: 'No signature header read; no HMAC verification before processing.'
  fix: Require an X-Signature header (HMAC-SHA256 of body with a shared secret) and verify
       constant-time before any processing. Rate-limit the endpoint.

SECURITY_FINDING:
  id: SF-009
  severity: LOW
  owasp_ref: A09:2021
  file: FleetReportExporter.java
  line: 42
  title: Use of java.util.logging instead of project standard SLF4J
  attack_vector: Inconsistent logging bypasses centralised log scrubbing/PII filters and
                 SIEM enrichment configured for SLF4J/Logback.
  evidence: 'Logger.getLogger("reports").info(...)'
  fix: Use private static final Logger log = LoggerFactory.getLogger(FleetReportExporter.class);
```

## Part 2 — Prose Summary

### 🔴 CRITICAL — Block immediately
- **SF-001 · exportReport L17-19** — Path traversal: `Paths.get("/tmp/reports/" + filename)` with attacker-controlled `filename` is a write-anywhere primitive (overwrite `.ssh/authorized_keys`, cron, jars → RCE). Canonicalise and assert `startsWith(base)`, or eliminate the disk write entirely (it appears unused — bytes are returned in the response body).
- **SF-002 · receiveWebhook L28-30** — Classic SSRF: `RestTemplate.getForEntity(payload.getCallbackUrl(), …)`. Attacker can hit AWS IMDS (`169.254.169.254`) and exfiltrate IAM credentials, or pivot into internal services. Allow-list scheme/host, block RFC1918/loopback/link-local pre- and post-DNS, disable auto-redirect, cap timeouts and response size. Reconsider the push-vs-pull design.

### 🟠 HIGH — Escalate for review
- **SF-003 · class-level** — No `@PreAuthorize` / tenant ownership check anywhere. Any caller can export any fleet (IDOR). Add fleet-access expression and service-role restriction on `/import` and `/webhook`.
- **SF-004 · importData L41-43** — Log injection / CRLF forging via `data.get("user")`. Switch to SLF4J parameterised logging and strip CR/LF.
- **SF-005 · importData L38-40** — Untyped `Map<String,Object>` deserialisation with no size limit, no schema, no validation. Replace with a `@Valid` DTO; ensure Jackson default typing is disabled; cap request body size.

### 🟡 MEDIUM — Fix this sprint
- **SF-006 · importData L46** — `e.getMessage()` echoed to client leaks internals. Return generic error + correlation ID.
- **SF-007 · exportReport L21** — `Content-Disposition` filename unsanitised; allows header confusion / reflected file download. Validate against a strict regex and use `ContentDisposition.attachment().filename(...)`.
- **SF-008 · receiveWebhook** — No HMAC/signature on inbound webhook; combined with SF-002 this endpoint is fully attacker-driven.

### 🟢 LOW — Tech debt
- **SF-009 · L42** — `java.util.logging` instead of project SLF4J standard; bypasses central scrubbing/SIEM enrichment.

### ⚪ Code Quality Notes (not security findings)
- `exportReport` writes to `/tmp/reports/...` but never reads the file back — the disk write appears to be dead code (also amplifies SF-001). Recommend removing.
- `ObjectMapper` is instantiated per request; should be a Spring-managed singleton. (Performance, not security.)

### OWASP Top 10 Recall Check
- A01 Broken Access Control — SF-001, SF-003 ✓
- A02 Cryptographic Failures — No evidence of vulnerability found (no crypto in this controller; check transport TLS at gateway).
- A03 Injection — SF-007 (header), and SF-005 enables downstream injection ✓
- A04 Insecure Design — SF-008 ✓
- A05 Security Misconfiguration — SF-006 ✓
- A06 Vulnerable Components — Not assessable from this snippet (run `mvn dependency-check`).
- A07 AuthN Failures — SF-003 ✓
- A08 Software/Data Integrity — SF-005 ✓
- A09 Logging/Monitoring — SF-004, SF-009 ✓
- A10 SSRF — SF-002 ✓

### Verdict
**BLOCKED** — 2 CRITICAL (Path Traversal, SSRF) + 3 HIGH (missing AuthZ, log injection, untyped deserialisation). Do not promote. SF-001 and SF-002 are directly exploitable as written and either one alone justifies a block: SF-001 yields filesystem write → RCE; SF-002 yields cloud credential theft on any EC2/ECS/EKS host. Fix all CRITICAL and HIGH findings, then re-submit for review.

## Grading Reasoning
The agent had excellent vulnerability recall but over-reported beyond the benchmark ground truth and over-escalated severities for 2 of 3 planted issues. Strong detection coverage, weaker calibration.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Recall | 40% | 100 | The output explicitly identified all 3 planted vulnerabilities: path traversal ("Path Traversal via unsanitised filename parameter"), SSRF ("Unvalidated SSRF via attacker-controlled callbackUrl"), and log injection ("Log forging / CRLF injection via unsanitised user-controlled fields"). |
| Precision | 30% | 44.4 | It reported 9 total findings (SF-001 to SF-009), but only 4 align with ground truth/bonus in this benchmark (SF-001 path traversal, SF-002 SSRF, SF-004 log injection, SF-006 error detail leak). The remaining findings are extra/speculative for this prompt, reducing precision. |
| Severity accuracy | 30% | 33.3 | Against expected severities for planted vulns: Path Traversal was correctly marked CRITICAL; SSRF was marked CRITICAL but expected HIGH; Log Injection was marked HIGH but expected MEDIUM. That is 1 correct out of 3. |

## Overall Score: 63.3/100
