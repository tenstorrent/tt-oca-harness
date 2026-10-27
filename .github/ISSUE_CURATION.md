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
assignee), sets the `v1.0.0` milestone when Target release = v1.0.0 and
the author is not protected, and assigns a PR to its opener without a comment.
On PR open, reopen, or ready-for-review it runs `curator_notify.py --on-open`,
which requests a reviewer under the rules in
[Reviewer requests and reminders](#reviewer-requests-and-reminders).

## Files

- `issue-taxonomy.yml` — allow-lists, `automation.enabled`, and `curation.reviewer_pool`
- `scripts/curator_notify.py` — every reviewer request and reminder; `--self-test` replays the rules
- `workflows/curator-notify.yml` — runs `curator_notify.py` each weekday
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
assignments, milestone backstop (`v1.0.0` only for clearly TT-owned issues), and
title/body consistency. Issue titles keep `[WORKSTREAM/SUBSYSTEM]`. PR
titles use a path-like scope (`hw/smc:`, `dv:`), or `treewide:`; a PR body
gains `## Summary` and `## Test plan` when missing, and never an unused
`## Closes` or `## Notes`. It never requests a reviewer or posts a reminder,
and `add_reviewer` is not among its safe outputs. Its only comment is the
assignment comment; it does not re-assign anyone the timeline shows was
unassigned. gh-aw strips HTML comments from agent output, so the curator
recognizes its own earlier comments by wording, not by marker.
Comment bodies pass through `.github/scripts/unwrap_github_mentions.py` so a
login wrapped in a code span becomes a real @mention before posting. gh-aw
`add_comment` then keeps mentions in `safe-outputs.mentions.allowed` (human
repository collaborators) plus the parent issue or PR author. Refresh that
list when someone new should be pingable. The
Actions run conclusion is the `noop` safe-output; the agent emits one every run.

```bash
gh aw compile ocah-project-curator --validate
```

## Reviewer requests and reminders

`.github/scripts/curator_notify.py` decides every reviewer request and
reminder from the item's timeline: reviews, review requests and their
removal, pushes, draft changes, comments, and earlier automation comments.
It is plain code, not an agent, so the same history always gives the same
answer, and `--self-test` replays the rules on recorded pull request
timelines. `.github/workflows/curator-notify.yml` runs it at 08:00 PDT
(`0 15 * * 1-5` UTC) on weekdays; a manual dispatch prints the plan unless
`apply` is set. Locally, `python3 .github/scripts/curator_notify.py --verbose`
prints what it would post and why it skips the rest, and `--now` plans for
another time.

Durations are business days unless stated. On every item:

- At most one comment per item per run, and no reminder within 1 business
  day of the previous automation notice on that item.
- At most 3 reminders per person per run; the rest wait for a later run.
- No reminder on weekends, to bots, to protected authors, or on items whose
  Curation state is Locked.
- Its comments end in `<!-- ocah-notify:KIND:LOGINS -->`. Earlier curator
  comments, which lost their markers, are recognized by wording.

| Notice | Who | When | Never when |
|---|---|---|---|
| Reviewer request | First of: GitHub suggestion, linked-issue assignee, recent committer, `reviewer_pool` | On ready-for-review; else after a 1-day grace | Any review exists, any request is pending, an automatic request was already made on the PR, or the person reviewed or was removed from the PR |
| Request withdrawal (silent) | — | Automation requested someone who had already reviewed or been removed | The author or a reviewer made the request |
| Review reminder | Pending requested reviewers | 2 days after the request, then 3; at most 2 per request | The reviewer commented or reviewed since, the PR is approved, or it waits on the author's response to a change request |
| Reviewer unresponsive | Assignee, else author | 3 days after the second review reminder, once | — |
| Changes requested | Author | 3 days after the newest unanswered change request, once per request | The author pushed, commented, or reviewed since |
| Merge | Assignee, else author | 3 days after the newest approval, then 5; at most 2 | Pushed after the approval, changes requested, checks running, `DO NOT MERGE`/`WIP` title, base not `main`, body says it depends on another PR, or the owner gave a standing reason since the last nudge |
| Unreviewed | Assignee, else author | 3 days ready with no reviewer, then 5; at most 2 | An automatic reviewer request is still possible, or the owner gave a standing reason (blocked, waiting, out) |
| Draft | Author | 10 days a draft, once per draft period | `DO NOT MERGE`/`WIP` title, or the author pushed or commented in the second half |
| Due | Assignees | Milestone due within 3 calendar days, once per date | — |
| Stale issue | Assignees | 21 calendar days without human activity, at most 2 until someone responds | Unscheduled (no milestone) or in a protected milestone, or milestone due within a week |

## Weekly issue activity

Catalog source: `githubnext/agentics/weekly-issue-activity`
(`source:` in the markdown). Overlay: Tuesday 12:00 PDT
(`0 19 * * 2` UTC), discussion category `Weekly issue activity`,
`fallback-to-issue: false`, Copilot credit caps.

`.github/workflows/weekly-issue-activity.lock.yml` reads repository
issues from the Issues API, plots opened/closed volume and
time-to-close, and opens a discussion in that category. A new
summary closes earlier discussions in the category as outdated, so
they leave the discussions home. The category
name must match a repository discussion category exactly. A name that
does not match falls back to Announcements, which is the discussions
home. It does not read GitHub Insights or Project 291 Insights.

The `upload_assets` checkout in the lockfile is `fetch-depth: 1`.
`gh aw compile` writes `0`. A full clone of this repository exceeds that
job's 10 minute limit, the chart files are never pushed, and the
discussion images 404. Set the depth back to 1 before committing.

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
