// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Computes the page sample exactly once per `npm run scan` invocation and
// writes it to report/sample.json. tests/a11y.spec.js reads this static
// file rather than sampling itself -- Playwright loads spec files more
// than once per run (once to list/discover tests, again per worker that
// executes them), so any randomness inside the spec file itself would
// produce a different sample on each load and break test-title matching
// between the list phase and the run phase.
const fs = require('fs');
const path = require('path');
const { walk, sample } = require('./lib/discover-pages');

const BUILD_DIR = process.env.BUILD_DIR || path.resolve(__dirname, '../../doc/_build/html_antora');
const SAMPLE_SIZE = Number(process.env.SAMPLE_SIZE || 15);
const SEED = process.env.SAMPLE_SEED ? Number(process.env.SAMPLE_SEED) : undefined;
const OUT_FILE = path.join(__dirname, 'report/sample.json');

const allPages = walk(BUILD_DIR);
if (allPages.length === 0) {
  throw new Error(
    `No .html files found under ${BUILD_DIR} -- check BUILD_DIR points at a real Antora build output directory.`
  );
}

const { sample: pages, seed } = sample(allPages, Math.min(SAMPLE_SIZE, allPages.length), SEED);

fs.mkdirSync(path.dirname(OUT_FILE), { recursive: true });
fs.writeFileSync(OUT_FILE, JSON.stringify({ seed, totalPages: allPages.length, pages }, null, 2));

console.log(`[a11y] Sampled ${pages.length} of ${allPages.length} built pages (seed=${seed}).`);
console.log(`[a11y] Re-run with SAMPLE_SEED=${seed} to reproduce this exact sample.`);
console.log(`[a11y] Sample written to ${OUT_FILE}`);
