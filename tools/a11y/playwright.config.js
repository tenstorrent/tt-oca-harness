// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// @ts-check
const { defineConfig } = require('@playwright/test');
const path = require('path');

// Directory containing the built Antora site (static HTML output).
// Override with the BUILD_DIR env var if this path differs on your
// machine or in CI.
const BUILD_DIR = process.env.BUILD_DIR || path.resolve(__dirname, '../../doc/_build/html_antora');
const PORT = Number(process.env.A11Y_PORT || 4173);

module.exports = defineConfig({
  testDir: './tests',
  timeout: 30_000,
  // Single worker: each test appends its own result to report/a11y-results.jsonl,
  // and summarize.js reads that file back afterwards. Running serially avoids
  // any concern about multiple worker processes writing to it concurrently --
  // scanning ~15 pages serially is fast enough that parallelism isn't needed.
  workers: 1,
  globalSetup: require.resolve('./global-setup.js'),
  reporter: [['list']],
  webServer: {
    command: `npx http-server "${BUILD_DIR}" -p ${PORT} -s`,
    port: PORT,
    reuseExistingServer: !process.env.CI,
    timeout: 20_000,
  },
  use: {
    baseURL: `http://localhost:${PORT}`,
  },
});
