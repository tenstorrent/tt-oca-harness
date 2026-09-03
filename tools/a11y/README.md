# OCAH docs accessibility scan (Playwright + axe-core)

Standalone, local-only tool (not wired into CI yet) that scans a random
sample of the built OCAH docs site against WCAG 2.2 AA rules, using
Playwright + `@axe-core/playwright` — the same approach Tenstorrent uses
for their own site.

## Setup

```
cd tools/a11y
npm install
npm run install-browsers
```

## Usage

1. Build the docs site first (however you normally do — e.g. `docker-run.sh`
   from the repo root), so `doc/_build/html_antora/` exists and is current.
2. From this folder, run:

   ```
   npm run scan
   ```

   This runs two steps: `generate-sample.js` first discovers every built
   `.html` page and randomly samples 15 of them (override with
   `SAMPLE_SIZE=20 npm run scan`) into `report/sample.json`, then
   `playwright test` starts a local static server over the build output
   and runs an axe-core scan against each sampled page. Running these as
   one chained command, rather than two separate `npm` scripts, matters —
   see "Design note" below.
3. Then:

   ```
   npm run summarize
   ```

   Prints a summary to the console and writes `report/a11y-summary.md`.

## Design note: why sampling isn't done inside the test file

Playwright loads spec files more than once per run — once to discover/list
the tests, and again inside the worker process that executes them.

`generate-sample.js` runs once, before Playwright starts, and
writes the sample to `report/sample.json`. `tests/a11y.spec.js` only reads
that static file — no randomness inside the spec file itself — so every
reload produces identical test titles.

## Configuration

- `BUILD_DIR` — path to the built site, if it's not at the default
  `../../doc/_build/html_antora` relative to this folder.
- `SAMPLE_SIZE` — how many pages to sample (default 15).
- `SAMPLE_SEED` — reuse a specific seed (printed at the start of each run)
  to reproduce the exact same sample of pages on a later run.

## Notes

- Filtered to the `wcag2a`, `wcag2aa`, `wcag21aa`, `wcag22aa` axe-core rule
  tags, matching the WCAG 2.2 AA level referenced in Tenstorrent's review.
- Runs with a single Playwright worker (serial) so the JSONL report file
  written by each test can be read back reliably afterwards, without
  needing a worker-safe write scheme — fine at this scale (~15-20 pages).
- Package versions in `package.json` are current as of when this was
  written; run `npm install` to resolve to whatever's actually latest and
  compatible.
