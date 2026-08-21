<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# OCAH GitHub automation

`automation.enabled` in `issue-taxonomy.yml` gates every agentic
workflow below. When it is not true they emit no writes.

Ingest (`.github/scripts/ingest_github.py`) is separate: it copies form
fields on issue open or edit, and assigns a PR opener. It never assigns
issues.

## Files

- `issue-taxonomy.yml` — allow-lists and `automation.enabled`
- `workflows/<name>.md` — source (edit this)
- `workflows/<name>.lock.yml` — generated; do not edit
- `aw/actions-lock.json` — compiler action pins

```bash
gh aw compile <name> --validate
```

Commit the source and the lockfile together.

## Project curator

`.github/workflows/ocah-project-curator.lock.yml` runs at 05:00 and
16:00 PDT (`0 12 * * *` and `0 23 * * *` UTC) and on
`workflow_dispatch`. It applies Project 291 fills, assignments, and
title/body consistency on open issues and PRs, then lists those
changes in the Actions run summary. Issue titles keep
`[WORKSTREAM/SUBSYSTEM]`. PR titles use a path-like scope (`hw/smc:`,
`dv:`), or `treewide:` when the change spans several trees, not an
issue prefix and not `feat(scope):`. It also comments on PRs approved
for 3 days that are still open, and reminds issue assignees 3 days
before a milestone or issue due date. The window is every open issue
and PR opened at or after the last successful run of this workflow;
when there is no successful run, the window is every open issue and
PR. Approved-but-unmerged PRs and issues with a due date in the next
3 days are always in the window.

```bash
gh aw compile ocah-project-curator --validate
```

## Weekly issue activity

Catalog source: `githubnext/agentics/weekly-issue-activity`
(`source:` in the markdown). Overlay: Tuesday 12:00 PDT
(`0 19 * * 2` UTC), General category, `fallback-to-issue: false`,
Copilot credit caps.

`.github/workflows/weekly-issue-activity.lock.yml` reads repository
issues from the Issues API, plots opened/closed volume and
time-to-close, and opens a General discussion. It does not read
GitHub Insights or Project 291 Insights.

```bash
gh aw compile weekly-issue-activity --validate
gh aw update weekly-issue-activity
```

## Discussion task miner

Catalog source: `githubnext/agentics/discussion-task-miner`.
Overlay: no `[task-miner]` title prefix, no 1-day expiry, Ideas
only, Task form headings, label `discussion-miner`, type Task.

`.github/workflows/discussion-task-miner.lock.yml` runs daily and
on `workflow_dispatch`. Ingest prefixes and copies fields from the
form headings. The curator assigns.

```bash
gh aw compile discussion-task-miner --validate
gh aw update discussion-task-miner
```
