<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# OCAH project curator

Kill switch and compile notes. The prompt is
`.github/workflows/ocah-project-curator.md`.

## Files

- `issue-taxonomy.yml` — allow-lists and `automation.enabled`
- `workflows/ocah-project-curator.md` — source (edit this)
- `workflows/ocah-project-curator.lock.yml` — generated; do not edit
- `aw/actions-lock.json` — compiler action pins

## Disabled

It cannot run on a schedule: `on: workflow_dispatch` only,
`automation.enabled: false`, and `safe-outputs.staged: true`.
A dispatch still no-ops until `enabled` is true.

## Compile

```bash
gh aw compile ocah-project-curator --validate
```

Commit the source and the lockfile together.

Ingest (`.github/scripts/ingest_github.py`) is separate: it copies form
fields on issue open or edit, and assigns a PR opener. It never assigns
issues.
