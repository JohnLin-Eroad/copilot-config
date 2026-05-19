# Prompt P3: Fleet Report Exporter

## Prompt

```
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
```

## Planted Vulnerabilities (GRADER ONLY)

1. **Path Traversal (OWASP A01)** — `Paths.get("/tmp/reports/" + filename)` — user-supplied `filename` could be `../../etc/passwd` or `../../../app/config.yml`, writing arbitrary files
2. **Server-Side Request Forgery / SSRF (OWASP A10)** — `restTemplate.getForEntity(callbackUrl, String.class)` — user-supplied URL used directly, can access internal services, cloud metadata (169.254.169.254), or private network resources
3. **Log Injection (OWASP A09)** — `"Import received: fleet=" + data.get("fleet_id") + " user=" + data.get("user")` — user-controlled data injected into log entries without sanitization, enabling log forging/spoofing

## Grading Rubric

| Dimension | Weight | How to score |
|---|---|---|
| Recall | 40% | (planted vulns found) / 3 × 100 |
| Precision | 30% | (true positives) / (total issues flagged) × 100 |
| Severity accuracy | 30% | Were found vulns correctly classified? (per-vuln pass/fail, averaged) |

**Score = weighted average (0-100)**

## Ground Truth

- Path Traversal: CRITICAL severity (arbitrary file write)
- SSRF: HIGH severity (internal network access)
- Log Injection: MEDIUM severity (log forging, potential for log-based attacks)
- Bonus (not required): error message leaks parse exception details

## Auto-Checks

```yaml
- name: finds-path-traversal
  must_contain_any: ["path traversal", "../", "directory traversal", "canonical path"]
  case_insensitive: true
- name: finds-ssrf
  must_contain_any: ["SSRF", "server-side request forgery", "cloud metadata", "internal network", "metadata endpoint", "link-local"]
  case_insensitive: true
- name: finds-log-injection
  must_contain_any: ["log injection", "log forging", "log spoofing", "sanitize log", "sanitise log"]
  case_insensitive: true
- name: severity-classification
  must_contain_any: ["HIGH", "CRITICAL", "MEDIUM"]
- name: cites-owasp
  must_contain_any: ["OWASP", "A0", "Top 10"]
```
