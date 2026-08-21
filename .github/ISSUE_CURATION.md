<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# OCAH project curator

The prompt is `.github/workflows/ocah-project-curator.md`.

## Files

- `issue-taxonomy.yml` — allow-lists and `automation.enabled`
- `workflows/ocah-project-curator.md` — source (edit this)
- `workflows/ocah-project-curator.lock.yml` — generated; do not edit
- `aw/actions-lock.json` — compiler action pins

## Run

`automation.enabled` in `issue-taxonomy.yml` is true. The workflow is
`.github/workflows/ocah-project-curator.lock.yml`. It runs at 05:00 and
16:00 PDT (`0 12 * * *` and `0 23 * * *` UTC) and on `workflow_dispatch`.
It applies Project 291 fills, assignments, and title/body consistency
on open issues and PRs, then lists those changes in the Actions run
summary. Issue titles keep `[WORKSTREAM/SUBSYSTEM]`. PR titles use a
path-like scope (`hw/smc:`, `dv:`), or `treewide:` when the change
spans several trees, not an issue prefix and not `feat(scope):`. It also comments on PRs approved for 3 days that are still
open, and reminds issue assignees 3 days before a milestone or issue
due date. The window is every open issue and PR opened at or after the
last successful run of this workflow; when there is no successful run,
the window is every open issue and PR. Approved-but-unmerged PRs and
issues with a due date in the next 3 days are always in the window.

## Compile

```bash
gh aw compile ocah-project-curator --validate
```

Commit the source and the lockfile together.

Ingest (`.github/scripts/ingest_github.py`) is separate: it copies form
fields on issue open or edit, and assigns a PR opener. It never assigns
issues.
