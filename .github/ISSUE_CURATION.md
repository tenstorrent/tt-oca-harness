<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# OCAH GitHub automation

`automation.enabled` in `issue-taxonomy.yml` gates every agentic
workflow below. When it is not true they emit no writes.

Ingest (`.github/scripts/ingest_github.py`) is separate: it copies form
fields on issue open or edit. When a bracket-prefix title (`[WS/SS]`) is
present but the body has no form headings, it derives W/S/C from the title.
It also assigns issues mechanically (explicit @mention or parent-issue
assignee), sets the `v0.5.0 (TT)` milestone when Target release = v0.5.0 and
the author is not protected, assigns PR openers, and requests a reviewer on PR
open or ready-for-review. The picker walks GitHub suggested reviewers, then the
assignee of a linked closing issue, then recent committers on the touched
paths, then `curation.reviewer_pool` in `issue-taxonomy.yml`. First assignable
human who is not the author wins.

## Files

- `issue-taxonomy.yml` — allow-lists, `automation.enabled`, and `curation.reviewer_pool`
- `scripts/unwrap_github_mentions.py` — strips code spans around @mentions in curator comments
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
`workflow_dispatch`. The window is state-driven: every open item with
incomplete fields, missing assignee, non-house-style title/body, or a
due reminder is processed; fully-managed items without pending reminders
are skipped to bound credit use. It applies Project 291 fills,
assignments, reviewer requests (same picker as ingest, when ingest found none),
milestone backstop (`v0.5.0 (TT)` only for clearly TT-owned issues), and
title/body consistency. Issue titles keep `[WORKSTREAM/SUBSYSTEM]`. PR
titles use a path-like scope (`hw/smc:`, `dv:`), or `treewide:`; PR
bodies are normalized to Summary/Test plan/Closes/Notes. Reminders:
due date (≤3 days, fed by milestone due date for v0.5.0 issues),
approved-PR merge nudge (≥3 days), review pending (>1 business day),
unreviewed PR (≥3 days, pings the assignee), draft open (>5 business days),
changes-requested idle (>3 business days), and stale-assigned issue (≥21 days).
All reminders are gated by a hidden marker and minimum re-nudge spacing.
Comment bodies pass through `.github/scripts/unwrap_github_mentions.py` so a
login wrapped in a code span becomes a real @mention before posting. gh-aw
`add_comment` then keeps mentions in `safe-outputs.mentions.allowed` (human
repository collaborators) plus the parent issue or PR author. Refresh that
list when someone new should be pingable. The
Actions run conclusion is the `noop` safe-output; the agent emits one every run.

```bash
gh aw compile ocah-project-curator --validate
```

## Weekly issue activity

Catalog source: `githubnext/agentics/weekly-issue-activity`
(`source:` in the markdown). Overlay: Tuesday 12:00 PDT
(`0 19 * * 2` UTC), discussion category `Weekly issue activity`,
`fallback-to-issue: false`, Copilot credit caps.

`.github/workflows/weekly-issue-activity.lock.yml` reads repository
issues from the Issues API, plots opened/closed volume and
time-to-close, and opens a discussion in that category. The category
name must match a repository discussion category exactly. A name that
does not match falls back to Announcements, which is the discussions
home. It does not read GitHub Insights or Project 291 Insights.

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
