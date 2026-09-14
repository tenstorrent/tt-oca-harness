// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Walks the built site directory for all .html files, returning them as
// site-root-relative URL paths (e.g. "/trm/index.html"). Used to build a
// random sample of pages for the accessibility scan.
const fs = require('fs');
const path = require('path');

function walk(dir, base = dir, results = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, base, results);
    } else if (entry.isFile() && entry.name.endsWith('.html')) {
      const relative = '/' + path.relative(base, full).split(path.sep).join('/');
      results.push(relative);
    }
  }
  return results;
}

// Seeded Fisher-Yates shuffle (mulberry32 PRNG) so a specific sample can
// be reproduced later by passing the same seed back in. Seed defaults to
// the current time, so runs are genuinely randomized unless a seed is
// explicitly supplied.
function sample(array, n, seed) {
  const initialSeed = seed ?? Date.now();
  let s = initialSeed;
  function rand() {
    s |= 0;
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  const arr = array.slice();
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return { sample: arr.slice(0, n), seed: initialSeed };
}

module.exports = { walk, sample };
