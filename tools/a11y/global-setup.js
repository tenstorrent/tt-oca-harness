// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Clears out any stale report data from a previous run before this one
// starts, so report/a11y-results.jsonl only ever contains the current
// run's pages.
const fs = require('fs');
const path = require('path');

module.exports = async () => {
  const reportDir = path.join(__dirname, 'report');
  fs.mkdirSync(reportDir, { recursive: true });
  fs.writeFileSync(path.join(reportDir, 'a11y-results.jsonl'), '');
};
