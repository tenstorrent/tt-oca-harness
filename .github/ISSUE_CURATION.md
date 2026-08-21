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

`.github/workflows/ocah-weekly-issue-activity.lock.yml` runs at 12:00
PDT on Tuesday (`0 19 * * 2` UTC) and on `workflow_dispatch`. It reads
repository issues from the Issues API, plots opened/closed volume and
time-to-close with pandas/matplotlib/seaborn on the runner, and opens
a General discussion titled `[Weekly Summary] YYYY-MM-DD`. It closes
older discussions with that prefix. It does not read GitHub Insights
or Project 291 Insights.

```bash
gh aw compile ocah-weekly-issue-activity --validate
```

## Discussion task miner

`.github/workflows/ocah-discussion-task-miner.lock.yml` runs at 10:00
PDT daily (`0 17 * * *` UTC) and on `workflow_dispatch`. It reads Ideas
discussions from the last 7 days, opens up to 5 Task issues labelled
`discussion-miner`, and remembers processed threads in cache-memory.
Each issue is type Task and uses the Task form headings so ingest
can prefix the title and copy fields. They do not expire.

```bash
gh aw compile ocah-discussion-task-miner --validate
```
