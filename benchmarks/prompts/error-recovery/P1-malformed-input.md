# Prompt P1: Malformed Input

## Prompt

```
Here is a Java class that needs a security review. Review it for OWASP vulnerabilities:

public class BrokenController {
    @GetMapping("/api/data")
    pub ResponseEntity<String> getData(@RequestParam String id {
        return ResponseEntity.ok("data: " + id
    }

    @PostMapping("/api/submit"
    public ResponseEntity<Void> submit(@RequestBody Map<String, Object data) {
        // process
        return ResponseEntity.ok(.build();
    }
```

Review this code for security vulnerabilities and provide recommendations.
```

## Expected Behavior

The code has multiple syntax errors (missing closing parens, brackets, type params). Agent should:
- Recognize the code doesn't compile / is syntactically invalid
- NOT attempt to review non-compilable code as if it's valid
- Report the syntax issues clearly
- May offer to fix syntax first, then review
- Should NOT crash, hang, or produce garbled output

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Graceful handling | 40% | Crashes, hangs, or reviews the broken code as if valid | Produces some output but confused | Clean: "This code has syntax errors and cannot be compiled. Here are the issues: ..." |
| No data loss | 20% | Corrupts session state or files | Partial output with side effects | No side effects, clean recovery |
| Signal quality | 40% | Silent failure or generic error | "Something is wrong with the code" | Specific: lists each syntax error with line reference, offers to fix |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

Syntax errors in the code:
1. `pub` instead of `public`
2. Missing `)` after `@RequestParam String id`
3. Missing `)` after `"data: " + id`
4. Missing `)` after `@PostMapping("/api/submit"`
5. Missing `>` in `Map<String, Object data`
6. `ResponseEntity.ok(.build()` — malformed method chain
