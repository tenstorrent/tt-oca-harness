// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Reads report/a11y-results.jsonl (written incrementally during the
// Playwright run) and prints a readable summary: violation counts by
// page and by impact level, the actual failing selector/HTML for each
// node, plus a cross-page grouping that reveals whether the same
// element (e.g. shared navbar/footer chrome) is repeating across many
// pages versus a different element on each one.
const fs = require('fs');
const path = require('path');

const REPORT_FILE = path.join(__dirname, 'report/a11y-results.jsonl');
const MD_OUT = path.join(__dirname, 'report/a11y-summary.md');

if (!fs.existsSync(REPORT_FILE)) {
  console.error('No report found -- run "npm run scan" first.');
  process.exit(1);
}

const lines = fs.readFileSync(REPORT_FILE, 'utf8').trim().split('\n').filter(Boolean);
const results = lines.map((l) => JSON.parse(l));

function truncate(s, n) {
  if (!s) return s;
  return s.length > n ? s.slice(0, n) + '…' : s;
}

const impactCounts = { critical: 0, serious: 0, moderate: 0, minor: 0 };
let totalViolationTypes = 0;

// Group by (rule id + selector) across all pages, so we can see whether
// the exact same element is failing on many pages (shared chrome) or a
// different element each time (per-page content).
const patternMap = new Map();

for (const r of results) {
  for (const v of r.violations) {
    impactCounts[v.impact] = (impactCounts[v.impact] || 0) + 1;
    totalViolationTypes++;
    for (const n of v.nodes || []) {
      const selector = Array.isArray(n.target) ? n.target.join(' ') : String(n.target);
      const key = `${v.id}::${selector}`;
      if (!patternMap.has(key)) {
        patternMap.set(key, {
          id: v.id,
          impact: v.impact,
          selector,
          html: n.html,
          failureSummary: n.failureSummary,
          pages: new Set(),
        });
      }
      patternMap.get(key).pages.add(r.url);
    }
  }
}

const patterns = [...patternMap.values()].sort((a, b) => b.pages.size - a.pages.size);

console.log(`\nScanned ${results.length} page(s).`);
console.log(`Total violation types found: ${totalViolationTypes}`);
console.log(
  `By impact: critical=${impactCounts.critical} serious=${impactCounts.serious} moderate=${impactCounts.moderate} minor=${impactCounts.minor}\n`
);

console.log('Cross-page patterns (same rule + same selector, grouped across all sampled pages):');
for (const p of patterns) {
  console.log(`  [${p.impact}] ${p.id}  --  selector: ${p.selector}`);
  console.log(`    seen on ${p.pages.size}/${results.length} sampled page(s)`);
  console.log(`    html: ${truncate(p.html, 200)}`);
  if (p.failureSummary) console.log(`    why: ${p.failureSummary.replace(/\n/g, ' ')}`);
  console.log('');
}

const pagesWithIssues = results.filter((r) => r.violationCount > 0);

let md = `# Accessibility scan summary\n\n`;
md += `Scanned ${results.length} page(s). Total violation types: ${totalViolationTypes}.\n\n`;
md += `| Impact | Count |\n|---|---|\n`;
for (const level of ['critical', 'serious', 'moderate', 'minor']) {
  md += `| ${level} | ${impactCounts[level]} |\n`;
}

md += `\n## Cross-page patterns\n\n`;
md += `Same rule + same CSS selector, grouped across all sampled pages -- a high page count here means one shared element (e.g. navbar/footer chrome), not per-page content.\n\n`;
for (const p of patterns) {
  md += `### [${p.impact}] ${p.id}\n\n`;
  md += `- Selector: \`${p.selector}\`\n`;
  md += `- Seen on ${p.pages.size}/${results.length} sampled page(s)\n`;
  md += `- HTML: \`${truncate(p.html, 300)}\`\n`;
  if (p.failureSummary) md += `- Why: ${p.failureSummary.replace(/\n/g, ' ')}\n`;
  md += `\n`;
}

md += `\n## Per-page detail\n\n`;
if (pagesWithIssues.length === 0) {
  md += `None.\n`;
} else {
  for (const r of pagesWithIssues) {
    md += `### ${r.url}\n\n`;
    for (const v of r.violations) {
      md += `- **[${v.impact}] ${v.id}** -- ${v.help} (${v.nodeCount} element(s)). [More info](${v.helpUrl})\n`;
    }
    md += `\n`;
  }
}

fs.writeFileSync(MD_OUT, md);
console.log(`Markdown report written to ${MD_OUT}`);
