# HTML Report — Full Reference (Tier 3)

Complete CSS design system, sidebar navigation JS, and copy-paste component library.

---

## Design System — Full CSS

Copy this entire block into the `<style>` tag of every report.

```css
/* ============================================
   COPILOT HTML REPORT — DESIGN SYSTEM
   Dark theme, responsive, self-contained
   ============================================ */

/* --- CSS Variables --- */
:root {
  --bg-body: #0f1117;
  --bg-surface: #1a1d27;
  --bg-surface-hover: #232738;
  --bg-sidebar: #141620;
  --border: #2a2d3a;
  --border-light: #353849;

  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;

  --accent-blue: #6c8ef7;
  --accent-purple: #a78bfa;
  --accent-green: #34d399;
  --accent-yellow: #fbbf24;
  --accent-red: #f87171;
  --accent-cyan: #22d3ee;

  --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;

  --shadow-card: 0 2px 8px rgba(0,0,0,0.3);
  --shadow-hover: 0 4px 16px rgba(0,0,0,0.4);

  --sidebar-width: 280px;
}

/* --- Reset & Base --- */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--font-sans);
  background: var(--bg-body);
  color: var(--text-primary);
  line-height: 1.6;
  display: flex;
  min-height: 100vh;
}

/* --- Sidebar --- */
.sidebar {
  width: var(--sidebar-width);
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  padding: 2rem 1.5rem;
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  z-index: 100;
}

.sidebar-header { margin-bottom: 2rem; }
.sidebar-header h2 {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 0.25rem;
}
.sidebar-header .subtitle {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.sidebar nav { flex: 1; display: flex; flex-direction: column; gap: 2px; }

.nav-link {
  display: block;
  padding: 0.5rem 0.75rem;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.85rem;
  border-radius: var(--radius-sm);
  transition: all 0.2s ease;
}
.nav-link:hover { background: var(--bg-surface); color: var(--text-primary); }
.nav-link.active {
  background: rgba(108, 142, 247, 0.12);
  color: var(--accent-blue);
  font-weight: 600;
}

.sidebar-footer {
  margin-top: auto;
  padding-top: 1.5rem;
  border-top: 1px solid var(--border);
  font-size: 0.75rem;
  color: var(--text-muted);
}
.sidebar-footer .date { margin-top: 0.25rem; }

/* --- Main Content --- */
main {
  margin-left: var(--sidebar-width);
  padding: 2.5rem 3rem;
  max-width: 960px;
  width: 100%;
}

section { margin-bottom: 3rem; }
section h1 {
  font-size: 1.75rem;
  font-weight: 700;
  margin-bottom: 1.25rem;
  color: var(--text-primary);
}
section h2 {
  font-size: 1.25rem;
  font-weight: 600;
  margin-bottom: 1rem;
  color: var(--text-primary);
}
section h3 {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
  color: var(--text-secondary);
}
p { margin-bottom: 1rem; color: var(--text-secondary); }

/* --- Card --- */
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 1.5rem;
  margin-bottom: 1rem;
  box-shadow: var(--shadow-card);
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.card:hover {
  box-shadow: var(--shadow-hover);
  border-color: var(--border-light);
}
.card h3 {
  font-size: 1.05rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
  color: var(--text-primary);
}
.card p { font-size: 0.9rem; }

/* --- Card Grid --- */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.card-grid .card { margin-bottom: 0; }

/* --- Table --- */
table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 1.5rem;
  font-size: 0.9rem;
}
thead th {
  background: var(--bg-surface);
  padding: 0.75rem 1rem;
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 2px solid var(--border);
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
tbody td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  color: var(--text-primary);
}
tbody tr { transition: background 0.15s ease; }
tbody tr:hover { background: var(--bg-surface-hover); }

/* --- Badge --- */
.badge {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.badge-green  { background: rgba(52,211,153,0.15); color: var(--accent-green); }
.badge-yellow { background: rgba(251,191,36,0.15); color: var(--accent-yellow); }
.badge-red    { background: rgba(248,113,113,0.15); color: var(--accent-red); }
.badge-blue   { background: rgba(108,142,247,0.15); color: var(--accent-blue); }
.badge-purple { background: rgba(167,139,250,0.15); color: var(--accent-purple); }

/* --- Callout --- */
.callout {
  padding: 1rem 1.25rem;
  border-radius: var(--radius-md);
  margin-bottom: 1rem;
  font-size: 0.9rem;
  border-left: 4px solid;
}
.callout-info {
  background: rgba(108,142,247,0.08);
  border-left-color: var(--accent-blue);
  color: var(--text-secondary);
}
.callout-warn {
  background: rgba(251,191,36,0.08);
  border-left-color: var(--accent-yellow);
  color: var(--text-secondary);
}
.callout-danger {
  background: rgba(248,113,113,0.08);
  border-left-color: var(--accent-red);
  color: var(--text-secondary);
}
.callout-success {
  background: rgba(52,211,153,0.08);
  border-left-color: var(--accent-green);
  color: var(--text-secondary);
}
.callout strong { color: var(--text-primary); }

/* --- Score Bar --- */
.score-bar-container {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.score-bar {
  flex: 1;
  height: 8px;
  background: var(--border);
  border-radius: 999px;
  overflow: hidden;
}
.score-bar-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.6s ease;
}
.score-bar-fill.green  { background: var(--accent-green); }
.score-bar-fill.yellow { background: var(--accent-yellow); }
.score-bar-fill.red    { background: var(--accent-red); }
.score-bar-fill.blue   { background: var(--accent-blue); }
.score-bar-fill.purple { background: var(--accent-purple); }
.score-label {
  font-size: 0.85rem;
  font-weight: 600;
  min-width: 3rem;
  text-align: right;
  color: var(--text-primary);
}

/* --- Trend / List Item --- */
.trend-item {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1rem 0;
  border-bottom: 1px solid var(--border);
}
.trend-item:last-child { border-bottom: none; }
.trend-rank {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent-blue);
  min-width: 2rem;
  line-height: 1;
}
.trend-content { flex: 1; }
.trend-content h4 {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.25rem;
}
.trend-content p {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-bottom: 0;
}

/* --- Quick Reference Table (compact) --- */
.quick-ref {
  font-size: 0.85rem;
}
.quick-ref td:first-child {
  font-weight: 600;
  color: var(--accent-blue);
  white-space: nowrap;
  padding-right: 1.5rem;
}

/* --- Stat / KPI Row --- */
.stat-row {
  display: flex;
  gap: 1rem;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
}
.stat-card {
  flex: 1;
  min-width: 140px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 1.25rem;
  text-align: center;
}
.stat-value {
  font-size: 2rem;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 0.25rem;
}
.stat-label {
  font-size: 0.8rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* --- Code Block --- */
.code-block {
  background: var(--bg-body);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 1rem 1.25rem;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  overflow-x: auto;
  margin-bottom: 1rem;
  color: var(--text-secondary);
}

/* --- Tags / Chip List --- */
.tag-list { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
.tag {
  padding: 0.25rem 0.75rem;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 0.78rem;
  color: var(--text-secondary);
}

/* --- Responsive --- */
@media (max-width: 900px) {
  .sidebar { display: none; }
  main { margin-left: 0; padding: 1.5rem; }
}
```

---

## Sidebar Navigation JS

Paste this inside a `<script>` tag at the end of `<body>`.

```javascript
// Highlight active nav link on scroll
(function() {
  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.nav-link');

  function setActive() {
    let current = '';
    sections.forEach(function(section) {
      const top = section.offsetTop;
      if (window.scrollY >= top - 120) { current = section.getAttribute('id'); }
    });
    navLinks.forEach(function(link) {
      link.classList.remove('active');
      if (link.getAttribute('href') === '#' + current) {
        link.classList.add('active');
      }
    });
  }

  window.addEventListener('scroll', setActive);
  setActive();

  // Smooth scroll on click
  navLinks.forEach(function(link) {
    link.addEventListener('click', function(e) {
      e.preventDefault();
      var target = document.querySelector(this.getAttribute('href'));
      if (target) { target.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    });
  });
})();
```

---

## Component Library — Copy-Paste Snippets

### Card

```html
<div class="card">
  <h3>Card Title</h3>
  <p>Card description text goes here. Keep it concise.</p>
</div>
```

### Card Grid (auto-responsive columns)

```html
<div class="card-grid">
  <div class="card">
    <h3>Item One</h3>
    <p>Description of item one.</p>
  </div>
  <div class="card">
    <h3>Item Two</h3>
    <p>Description of item two.</p>
  </div>
  <div class="card">
    <h3>Item Three</h3>
    <p>Description of item three.</p>
  </div>
</div>
```

### Table with hover

```html
<table>
  <thead>
    <tr>
      <th>Name</th>
      <th>Status</th>
      <th>Score</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Item A</td>
      <td><span class="badge badge-green">Good</span></td>
      <td>92</td>
    </tr>
    <tr>
      <td>Item B</td>
      <td><span class="badge badge-yellow">Fair</span></td>
      <td>71</td>
    </tr>
    <tr>
      <td>Item C</td>
      <td><span class="badge badge-red">Poor</span></td>
      <td>38</td>
    </tr>
  </tbody>
</table>
```

### Badges

```html
<span class="badge badge-green">Excellent</span>
<span class="badge badge-yellow">Warning</span>
<span class="badge badge-red">Critical</span>
<span class="badge badge-blue">Info</span>
<span class="badge badge-purple">New</span>
```

### Callouts

```html
<div class="callout callout-info">
  <strong>ℹ️ Note:</strong> Informational callout for context or tips.
</div>

<div class="callout callout-warn">
  <strong>⚠️ Warning:</strong> Something to be cautious about.
</div>

<div class="callout callout-danger">
  <strong>🚨 Critical:</strong> A blocking issue or serious risk.
</div>

<div class="callout callout-success">
  <strong>✅ Success:</strong> Something that went well or a positive finding.
</div>
```

### Score Bar

```html
<div class="score-bar-container">
  <span style="min-width:100px;">Category</span>
  <div class="score-bar">
    <div class="score-bar-fill green" style="width: 85%;"></div>
  </div>
  <span class="score-label">85%</span>
</div>
```

Score bar colour classes: `green` (≥75%), `yellow` (40–74%), `red` (<40%), `blue`, `purple`.

### Stat / KPI Row

```html
<div class="stat-row">
  <div class="stat-card">
    <div class="stat-value" style="color: var(--accent-green);">47</div>
    <div class="stat-label">Tests Passed</div>
  </div>
  <div class="stat-card">
    <div class="stat-value" style="color: var(--accent-red);">3</div>
    <div class="stat-label">Failures</div>
  </div>
  <div class="stat-card">
    <div class="stat-value" style="color: var(--accent-blue);">94%</div>
    <div class="stat-label">Coverage</div>
  </div>
</div>
```

### Trend / Ranked Item

```html
<div class="trend-item">
  <span class="trend-rank">1</span>
  <div class="trend-content">
    <h4>Item Title</h4>
    <p>Brief description or supporting detail for this ranked item.</p>
  </div>
</div>
```

### Code Block

```html
<div class="code-block">
  curl -s http://localhost:8080/health | jq .
</div>
```

### Tag / Chip List

```html
<div class="tag-list">
  <span class="tag">Java</span>
  <span class="tag">Spring Boot</span>
  <span class="tag">PostgreSQL</span>
</div>
```
