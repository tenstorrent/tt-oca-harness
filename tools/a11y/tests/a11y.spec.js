// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// @ts-check
const { test } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;
const fs = require('fs');
const path = require('path');

const REPORT_FILE = path.join(__dirname, '../report/a11y-results.jsonl');
const SAMPLE_FILE = path.join(__dirname, '../report/sample.json');

// The page sample is precomputed once by generate-sample.js (run via
// `npm run scan`, before Playwright starts) and read here as a static
// list. Sampling must NOT happen inside this file: Playwright loads spec
// files more than once per run (once to list/discover tests, again per
// worker that executes them), and any randomness here would generate a
// different sample -- and therefore different test titles -- between
// those loads, causing "Test not found in the worker process" failures.
if (!fs.existsSync(SAMPLE_FILE)) {
  throw new Error(
    `${SAMPLE_FILE} not found -- run "node generate-sample.js" first (this normally happens automatically as part of "npm run scan").`
  );
}

const { pages, seed, totalPages } = JSON.parse(fs.readFileSync(SAMPLE_FILE, 'utf8'));

console.log(`[a11y] Running scan on ${pages.length} of ${totalPages} built pages (seed=${seed}).`);

for (const url of pages) {
  test(`a11y scan: ${url}`, async ({ page }) => {
    await page.goto(url);

    const axeResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze();

    const record = {
      url,
      violationCount: axeResults.violations.length,
      violations: axeResults.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        description: v.description,
        help: v.help,
        helpUrl: v.helpUrl,
        nodeCount: v.nodes.length,
        nodes: v.nodes.map((n) => ({
          target: n.target,
          html: n.html,
          failureSummary: n.failureSummary,
        })),
      })),
    };

    fs.appendFileSync(REPORT_FILE, JSON.stringify(record) + '\n');

    console.log(`[a11y] ${url}: ${axeResults.violations.length} violation type(s)`);

    // Deliberately not asserting/failing here -- this pass is report-only
    // per current project decision. Revisit once a severity threshold is
    // agreed (see README).
  });
}
