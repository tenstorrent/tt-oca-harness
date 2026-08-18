<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# OCAH project curator

Disabled fill-empty alignment for open issues on
[Project 291](https://github.com/orgs/tenstorrent/projects/291).

## Files

- `issue-taxonomy.yml` — allow-lists and `automation.enabled` kill switch
- `workflows/ocah-project-curator.md` — source (edit this)
- `workflows/ocah-project-curator.lock.yml` — generated; do not edit
- `aw/actions-lock.json` — compiler action pins

## Disabled

The curator cannot run on a schedule:

1. `on: workflow_dispatch` only
2. `automation.enabled: false`
3. `safe-outputs.staged: true`

A manual dispatch with credentials installed still no-ops until `enabled` is true.

## Compile

After changing the markdown source:

```bash
gh aw compile ocah-project-curator --validate
```

Commit the source and the lockfile together.

## What it may do when enabled

Fill **empty** Workstream, Subsystem, Component, Priority, or Curation state, and add a
missing title prefix. It must not overwrite set fields, and must not set milestone or
Target release.
