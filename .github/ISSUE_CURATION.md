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
`safe-outputs.staged` is true: proposals appear in the Actions run
summary and are not applied.

## Compile

```bash
gh aw compile ocah-project-curator --validate
```

Commit the source and the lockfile together.

Ingest (`.github/scripts/ingest_github.py`) is separate: it copies form
fields on issue open or edit, and assigns a PR opener. It never assigns
issues.
