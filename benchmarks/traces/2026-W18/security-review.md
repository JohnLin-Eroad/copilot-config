# Trace: security-review — 2026-W18

## Metadata
- Prompt ID: P3-fleet-report-exporter
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-04-27T11:46:56Z
- Duration: 175.5s

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
  owasp_ref: A01:2021 (Broken Access Control) / A03:2021 (Injection — Path Traversal)
  file: FleetReportExporter.java
  line: 18-20 (exportReport)
  title: Path traversal via unsanitised `filename` request parameter
  attack_vector: Attacker calls `/api/reports/export/123?filename=../../etc/passwd` (or `../../../home/app/.ssh/authorized_keys`). `Paths.get("/tmp/reports/" + filename)` resolves outside `/tmp/reports/`, allowing arbitrary file write anywhere the JVM user can write — full RCE potential by overwriting cron, systemd units, app JARs, or SSH keys.
  evidence: 'Path outputPath = Paths.get("/tmp/reports/" + filename); Files.write(outputPath, reportData);'
  fix: Reject filenames containing path separators or `..`; canonicalise and assert the resolved path starts with the intended base directory. Prefer generating a server-side filename (UUID) and ignoring user input. Example:
        Path base = Paths.get("/tmp/reports").toRealPath();
        Path resolved = base.resolve(filename).normalize();
        if (!resolved.startsWith(base)) throw new SecurityException();

SECURITY_FINDING:
  id: SF-002
  severity: CRITICAL
  owasp_ref: A10:2021 (Server-Side Request Forgery)
  file: FleetReportExporter.java
  line: 28-31 (receiveWebhook)
  title: Unrestricted SSRF via attacker-controlled `callbackUrl`
  attack_vector: Attacker POSTs `{"callbackUrl":"http://169.254.169.254/latest/meta-data/iam/security-credentials/"}` (AWS IMDS) or `http://localhost:8080/actuator/env`, `file:///etc/passwd`, internal RDS/Redis endpoints. The server fetches the URL and the body is then passed into `processWebhookData`, which may also expose it back. Full SSRF — credential theft, internal network reconnaissance, bypass of network ACLs.
  evidence: 'String callbackUrl = payload.getCallbackUrl(); restTemplate.getForEntity(callbackUrl, String.class);'
  fix: Do not fetch arbitrary URLs from request bodies. If callbacks are required: (a) allowlist scheme (`https` only), (b) allowlist hosts/domains, (c) resolve DNS and reject RFC1918/loopback/link-local/IMDS ranges (re-resolve to defeat DNS rebinding), (d) disable redirects, (e) use IMDSv2-required EC2 metadata or block 169.254.169.254 at egress. Consider moving outbound calls behind an egress proxy.

SECURITY_FINDING:
  id: SF-003
  severity: HIGH
  owasp_ref: A01:2021 (Broken Access Control)
  file: FleetReportExporter.java
  line: 17, 27, 34 (all endpoints)
  title: No authentication / authorisation enforcement on sensitive endpoints
  attack_vector: No `@PreAuthorize`, tenant scoping, or fleet ownership check. Any authenticated (or possibly anonymous) caller can export reports for arbitrary `fleetId` (IDOR), trigger SSRF, or import data into another tenant's dataset.
  evidence: Controller methods have no authorisation annotations and no fleet-ownership verification against the caller's principal.
  fix: Add `@PreAuthorize("hasAuthority('REPORT_EXPORT')")` plus an explicit ownership check (`reportService.assertCallerOwns(fleetId, principal)`). Webhook/import endpoints should require service-to-service auth (signed HMAC, mTLS, or scoped JWT).

SECURITY_FINDING:
  id: SF-004
  severity: HIGH
  owasp_ref: A03:2021 (Injection — Log Injection / CRLF)
  file: FleetReportExporter.java
  line: 38-40 (importData)
  title: Log forging via unsanitised user input concatenated into log message
  attack_vector: Attacker submits `{"user":"alice\n2026-04-27 INFO admin granted role=ROOT"}`. Newlines/CRLF injected into log files forge fake entries, poison SIEM/audit trails, or inject ANSI escape sequences into terminal-tailed logs.
  evidence: '"Import received: fleet=" + data.get("fleet_id") + " user=" + data.get("user") + " action=" + data.get("action")'
  fix: Use parameterised logging (`logger.info("Import received: fleet={} user={} action={}", ...)`) AND strip/encode CR/LF from values before logging. Also use SLF4J (not `java.util.logging.Logger.getLogger`) consistent with the rest of the platform.

SECURITY_FINDING:
  id: SF-005
  severity: HIGH
  owasp_ref: A09:2021 (Security Logging & Monitoring Failures) / A04:2021 (Insecure Design)
  file: FleetReportExporter.java
  line: 46 (importData catch block)
  title: Exception details leaked to client via response body
  attack_vector: `return ResponseEntity.badRequest().body("Parse error: " + e.getMessage());` returns Jackson/JVM exception messages that reveal class structure, field names, and parser internals — useful for attackers profiling the deserialisation surface (especially relevant given the polymorphic `Map<String,Object>` deserialisation).
  fix: Return a generic error message to the client (`"Invalid request payload"`) with a correlation id; log the full stack trace server-side only. Add a `@ControllerAdvice` exception handler.

SECURITY_FINDING:
  id: SF-006
  severity: MEDIUM
  owasp_ref: A08:2021 (Software and Data Integrity Failures)
  file: FleetReportExporter.java
  line: 35-37 (importData)
  title: Untyped polymorphic deserialisation into Map<String,Object>
  attack_vector: `mapper.readValue(rawJson, new TypeReference<Map<String,Object>>(){})` itself is not vulnerable, but downstream `reportService.importData(data)` receives an attacker-controlled untyped map. If any consumer reflectively dispatches on type or values are passed into expression languages / SpEL / template engines, this becomes an RCE vector. No schema validation is performed.
  fix: Bind to a strongly-typed DTO with `@Valid` constraints. Reject unknown fields (`FAIL_ON_UNKNOWN_PROPERTIES`). Ensure `ObjectMapper` has default typing disabled (Spring's default — confirm the shared bean is used rather than a freshly-constructed `new ObjectMapper()` whose config is unknown).

SECURITY_FINDING:
  id: SF-007
  severity: MEDIUM
  owasp_ref: A04:2021 (Insecure Design)
  file: FleetReportExporter.java
  line: 19-20 (exportReport)
  title: Unbounded file writes to shared `/tmp/reports/` with no quota or cleanup
  attack_vector: An attacker can repeatedly call the endpoint to fill the disk (DoS), or overwrite previously-written reports of other tenants if filenames collide (information disclosure between tenants). Writing the report to disk before streaming it back is also unnecessary — the bytes are already in memory.
  fix: Stream `reportData` directly in the response without writing to disk. If persistence is required, write to a per-tenant prefixed path with server-generated names and a retention policy.

SECURITY_FINDING:
  id: SF-008
  severity: MEDIUM
  owasp_ref: A05:2021 (Security Misconfiguration)
  file: FleetReportExporter.java
  line: 26 (Content-Disposition header)
  title: Reflected user input in Content-Disposition header (response splitting / filename spoofing)
  attack_vector: `headers.setContentDispositionFormData("attachment", filename)` — Spring's setter does encode per RFC 6266, so HTTP response splitting is mitigated, but the attacker still controls the displayed download filename, enabling user-deception attacks (e.g., presenting `invoice.pdf` for a malicious payload).
  fix: Server-generate the download filename based on `fleetId` and timestamp; never echo the request param.
```

## Part 2 — Prose Summary

### 🔴 CRITICAL — Block immediately
- **SF-001 · exportReport L18-20** — Path traversal: `Paths.get("/tmp/reports/" + filename)` allows arbitrary file write via `../`. Validate against a canonicalised base directory or generate the filename server-side.
- **SF-002 · receiveWebhook L28-31** — Full SSRF: `restTemplate.getForEntity(payload.getCallbackUrl(), …)` fetches any attacker-supplied URL, including AWS IMDS (`169.254.169.254`) and internal services. Allowlist scheme/hosts and block private/link-local ranges.

### 🟠 HIGH — Escalate for review
- **SF-003 · all endpoints** — No `@PreAuthorize` and no fleet-ownership check; classic IDOR plus unauthenticated SSRF/import. Add authorisation annotations and tenant scoping.
- **SF-004 · importData L38-40** — Log forging via newline injection in `user`/`action`. Use parameterised SLF4J logging and strip CR/LF.
- **SF-005 · importData L46** — Exception messages leaked to client. Use `@ControllerAdvice` with a generic error body.

### 🟡 MEDIUM — Fix this sprint
- **SF-006 · importData L35-37** — Untyped `Map<String,Object>` deserialisation with no schema validation. Bind to a typed, `@Valid` DTO.
- **SF-007 · exportReport L19-20** — Unnecessary disk write to shared `/tmp/reports/`; DoS and cross-tenant overwrite risk. Stream the bytes directly.
- **SF-008 · exportReport L26** — Attacker-controlled download filename enables user deception. Server-generate the filename.

### 🟢 LOW — Tech debt
- None beyond above.

### ⚪ Code Quality Notes (not security findings)
- **L34** — `new ObjectMapper()` instantiated per request; should use the injected, Spring-configured bean (consistency, not a vuln by itself — but see SF-006 re: default typing).
- **L39** — `java.util.logging.Logger.getLogger("reports")` is inconsistent with platform SLF4J conventions.
- **L17** — `throws IOException` propagates to the framework — consider an explicit handler.

### OWASP Top 10 Recall Check
- A01 Broken Access Control — SF-001, SF-003 ✅
- A02 Cryptographic Failures — No evidence of vulnerability found (no crypto in this controller).
- A03 Injection — SF-001 (path), SF-004 (log) ✅
- A04 Insecure Design — SF-005, SF-007 ✅
- A05 Security Misconfiguration — SF-008 ✅
- A06 Vulnerable Components — Not assessable from this snippet (review `pom.xml` separately).
- A07 Identification & Auth Failures — Covered under SF-003.
- A08 Software & Data Integrity — SF-006 ✅
- A09 Logging & Monitoring Failures — SF-004, SF-005 ✅
- A10 SSRF — SF-002 ✅

### Verdict
**BLOCKED** — 2 CRITICAL (path traversal, SSRF) and 3 HIGH findings. Do not promote. SF-001 and SF-002 are directly exploitable for RCE/credential theft and must be fixed before merge. SF-003 (missing authz) should be addressed in the same change set as it amplifies every other finding.

## Grading Reasoning
The review has excellent coverage and correctly identifies all planted issues, but severity calibration is off on 2 of 3 expected vulnerabilities and several extra findings reduce precision. Overall, this is strong detection with moderate overcalling.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| recall | 40% | 100 | The agent found all 3 planted vulnerabilities with explicit findings: path traversal ('SF-001 ... Path traversal via unsanitised `filename`'), SSRF ('SF-002 ... Unrestricted SSRF via attacker-controlled `callbackUrl`'), and log injection ('SF-004 ... Log forging via unsanitised user input'). This is full recall: 3/3. |
| precision | 30% | 63 | It reported 8 findings total, but several are speculative or context-dependent rather than clearly evidenced in the snippet, e.g., 'No authentication / authorisation enforcement on sensitive endpoints' (could be enforced globally), and 'Untyped polymorphic deserialisation ... this becomes an RCE vector' (conditional downstream claim). With about 5 clearly valid findings out of 8, precision is roughly 62.5%. |
| severity_accuracy | 30% | 33 | Against expected severities for planted vulns: path traversal was correctly CRITICAL ('SF-001 ... severity: CRITICAL'), but SSRF was overclassified as CRITICAL (expected HIGH), and log injection was overclassified as HIGH (expected MEDIUM). That is 1 correct out of 3 severity labels. |

## Overall Score: 68.8/100
