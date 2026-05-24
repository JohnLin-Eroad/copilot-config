# Prompt P4: Compliance Webhook Handler

## Prompt

```
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
```

## Planted Vulnerabilities (GRADER ONLY)

1. **HMAC Validation Bypass via Empty Signature (OWASP A07)** — `if (signature != null)` means omitting the `X-Signature` header entirely bypasses HMAC validation. The `required = false` allows null. Any unsigned request is accepted.
2. **Mass Assignment via Reflection (OWASP A08)** — `/events` endpoint uses reflection to set ANY field on `ComplianceEvent` based on user input: `field.setAccessible(true); field.set(event, value)`. Attacker can set internal fields like `status`, `approvedBy`, `isVerified`.
3. **Replay Attack — No Nonce/Timestamp Validation (OWASP A07)** — The `nonce` parameter on GET is unused. The webhook endpoint has no timestamp or nonce checking, so captured valid requests can be replayed indefinitely.

## Grading Rubric

| Dimension | Weight | How to score |
|---|---|---|
| Recall | 40% | (planted vulns found) / 3 × 100 |
| Precision | 30% | (true positives) / (total issues flagged) × 100 |
| Severity accuracy | 30% | Were found vulns correctly classified? (per-vuln pass/fail, averaged) |

**Score = weighted average (0-100)**

## Ground Truth

- HMAC bypass: CRITICAL severity (authentication bypass)
- Mass assignment: HIGH severity (arbitrary field manipulation)
- Replay attack: MEDIUM severity (no immediate data breach but allows duplicate processing)
- Bonus (not required): error message leaks exception details, `ignored` catch swallows errors silently

## Auto-Checks

```yaml
- name: finds-hmac-bypass
  must_contain_any: ["HMAC", "signature null", "unsigned request", "validation bypass", "signature not required"]
  case_insensitive: true
- name: finds-mass-assignment
  must_contain_any: ["mass assignment", "reflection", "setAccessible", "field.set", "arbitrary field"]
  case_insensitive: true
- name: finds-replay
  must_contain_any: ["replay", "nonce", "timestamp", "idempotency"]
  case_insensitive: true
- name: severity-classification
  must_contain_any: ["HIGH", "CRITICAL", "MEDIUM"]
- name: cites-owasp
  must_contain_any: ["OWASP", "A0", "Top 10"]
```
