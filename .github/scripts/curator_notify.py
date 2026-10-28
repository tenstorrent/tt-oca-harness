#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Request PR reviewers and post curation reminders from the item's history.

Every reviewer request and reminder that OCAH automation posts is decided
here. Each rule reads the pull request or issue timeline -- reviews,
review requests and their removal, pushes, draft changes, comments, and
earlier automation comments -- so a person who reviewed, declined, or was
already reminded is not pinged again. ISSUE_CURATION.md lists the rules.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest_github import (  # noqa: E402
    REPO,
    REVIEWER_REASONS,
    _linked_issue_assignees,
    _path_history_authors,
    _suggested_reviewer_logins,
    gh_json,
    github_dir,
    load_taxonomy,
    login_is_assignable,
    pick_reviewer,
    reviewer_pool,
    run,
)

# Logins whose comments and review requests are automation, never a person.
AUTOMATION_LOGINS = {"github-actions", "github-actions[bot]", "tenstorrent-gh-bot-adm"}

# Business days unless the name says otherwise.
REVIEWER_GRACE = 1  # the author may pick a reviewer before the scheduled backfill does
REVIEW_REMINDER_FIRST = 2
REVIEW_REMINDER_REPEAT = 3
REVIEW_REMINDER_MAX = 2  # per reviewer per request; then the author is told once
CHANGES_REQUESTED_IDLE = 3
MERGE_NUDGE_FIRST = 3
MERGE_NUDGE_REPEAT = 5
MERGE_NUDGE_MAX = 2
UNREVIEWED_FIRST = 3
UNREVIEWED_REPEAT = 5
UNREVIEWED_MAX = 2
DRAFT_IDLE = 10
QUIET_AFTER_NOTICE = 1  # no reminder of any kind this soon after another one
STALE_ISSUE_DAYS = 21  # calendar days
STALE_ISSUE_MAX = 2
DUE_SOON_DAYS = 3  # calendar days
STALE_SKIP_DUE_DAYS = 7  # calendar days
PER_PERSON_PER_RUN = 3  # reminders, not reviewer requests; the rest wait for a later run

MARKER = "<!-- ocah-notify:{kind}:{logins} -->"
MARKER_RE = re.compile(r"<!-- ocah-notify:([a-z_]+):([^ ]*) -->")
LEGACY_MARKERS = {
    "review_request": "<!-- github-auto-review-request -->",
    "review_reminder": "<!-- github-curator-review-reminder -->",
    "unreviewed": "<!-- github-curator-unreviewed-pr -->",
    "draft": "<!-- github-curator-draft-reminder -->",
    "changes_requested": "<!-- github-curator-changes-pending -->",
    "merge": "<!-- github-curator-merge-nudge -->",
    "stale_issue": "<!-- github-curator-stale-assignee -->",
    "due": "<!-- github-curator-due-reminder -->",
}
# gh-aw strips HTML comments from agent output, so earlier curator comments
# carry no marker; their wording identifies them.
LEGACY_PHRASES = {
    "review_request": "automatically requested to review this pull request",
    "review_reminder": "requested to review this pull request and it has been",
    "unreviewed": "this pull request has had no review for",
    "draft": "this pull request has been a draft for",
    "changes_requested": "a reviewer has requested changes",
    "merge": "this pull request has been approved for",
    "stale_issue": "this issue has had no activity in",
    "due": " is due on ",
}
TEMPLATES = {
    "review_request": (
        "{mentions} — you've been automatically requested to review this pull request "
        "because {reason}.\n\nIf someone else is a better fit, please reassign it."
    ),
    "review_reminder": (
        "{mentions} — your review on this pull request was requested {days} business "
        "days ago. Please review it, or remove yourself from the reviewers if you cannot."
    ),
    "reviewer_unresponsive": (
        "{mentions} — {who} has not responded to the review request after "
        f"{REVIEW_REMINDER_MAX} reminders. Consider asking someone else to review."
    ),
    "unreviewed": (
        "{mentions} — this pull request has been ready for review for {days} business "
        "days and has no reviewer. Please request one, or say here if it is blocked."
    ),
    "changes_requested": (
        "{mentions} — {who} requested changes {days} business days ago and there has "
        "been no push or reply since. Please address the feedback or reply to the review."
    ),
    "merge_green": (
        "{mentions} — this pull request was approved {days} business days ago and its "
        "checks pass. Please merge it.{pending}"
    ),
    "merge_failing": (
        "{mentions} — this pull request was approved {days} business days ago but its "
        "checks fail. Please fix them and merge it.{pending}"
    ),
    "draft": (
        "{mentions} — this pull request has been a draft for {days} business days. "
        "Mark it ready for review when it is, or close it if it is no longer needed."
    ),
    "stale_issue": (
        "{mentions} — this issue has had no activity in {days} days. A short status "
        "update would help, or unassign yourself if it is on hold."
    ),
    "due": (
        "{mentions} — {milestone} is due on {date}. Please land this work, or move the "
        "issue to a later milestone if it will not make it."
    ),
}
STANDING_REASON = re.compile(
    r"(?i)\b(blocked|waiting|on hold|depends on|out of (the )?office|ooo|on leave|vacation)\b"
)
DEPENDENT = re.compile(r"(?i)\b(depends on|stacked on|blocked by|based on) (#\d+|pr|the)")
DO_NOT_MERGE = re.compile(r"(?i)do not merge|\bdnm\b|\bwip\b")
MENTION = re.compile(r"@([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?)")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def add_business_days(start: datetime, days: int) -> datetime:
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def business_days_between(start: datetime, end: datetime) -> int:
    count = 0
    day = start.date() + timedelta(days=1)
    while day <= end.date():
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count


def is_automation(login: str | None) -> bool:
    return not login or login in AUTOMATION_LOGINS or login.endswith("[bot]")


@dataclass
class Comment:
    login: str
    at: datetime
    body: str


@dataclass
class Review:
    login: str
    state: str
    at: datetime


@dataclass
class RequestEvent:
    at: datetime
    actor: str
    reviewer: str
    removed: bool


@dataclass
class Notice:
    kind: str
    at: datetime
    logins: list[str]


@dataclass
class Item:
    number: int
    title: str
    author: str
    created: datetime
    assignees: list[str]
    comments: list[Comment] = field(default_factory=list)
    is_pr: bool = True
    body: str = ""
    draft: bool = False
    base: str = "main"
    requested_users: list[str] = field(default_factory=list)
    requested_teams: list[str] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    requests: list[RequestEvent] = field(default_factory=list)
    ready_at: datetime | None = None
    draft_at: datetime | None = None
    last_push: datetime | None = None
    checks: str | None = None
    activity: list[tuple[datetime, str]] = field(default_factory=list)
    milestone: str | None = None
    milestone_number: int | None = None
    milestone_due: datetime | None = None


@dataclass
class Action:
    kind: str
    number: int
    logins: list[str]
    body: str
    request_reviewer: str | None = None
    is_pr: bool = True
    withdraw: list[str] = field(default_factory=list)


def classify(comment: Comment) -> Notice | None:
    if not is_automation(comment.login):
        return None
    match = MARKER_RE.search(comment.body)
    if match:
        return Notice(match.group(1), comment.at, [x for x in match.group(2).split(",") if x])
    kinds = [k for k, marker in LEGACY_MARKERS.items() if marker in comment.body]
    lowered = comment.body.lower()
    kinds += [k for k, phrase in LEGACY_PHRASES.items() if phrase in lowered]
    if not kinds:
        return None
    first_line = comment.body.split("—", 1)[0]
    return Notice(kinds[0], comment.at, MENTION.findall(first_line))


def notices(item: Item, kind: str, since: datetime | None = None) -> list[Notice]:
    found = []
    for comment in item.comments:
        notice = classify(comment)
        if notice and notice.kind == kind and (since is None or notice.at > since):
            found.append(notice)
    return sorted(found, key=lambda n: n.at)


def last_notice(item: Item) -> datetime | None:
    times = [n.at for c in item.comments if (n := classify(c))]
    return max(times) if times else None


def replied(item: Item, logins: set[str], since: datetime) -> bool:
    return any(c.login in logins and c.at > since for c in item.comments)


def standing_reason(item: Item, logins: set[str], since: datetime) -> bool:
    return any(
        c.login in logins and c.at > since and STANDING_REASON.search(c.body) for c in item.comments
    )


def mentions(logins: list[str]) -> str:
    return ", ".join(f"@{login}" for login in logins)


def render(
    kind: str,
    logins: list[str],
    template: str | None = None,
    about: list[str] | None = None,
    **values,
) -> str:
    """Mention LOGINS; the marker records ABOUT, the people the notice concerns."""
    text = TEMPLATES[template or kind].format(mentions=mentions(logins), **values)
    return f"{text}\n\n{MARKER.format(kind=kind, logins=','.join(about or logins))}"


def human_reviews(item: Item) -> list[Review]:
    return [r for r in item.reviews if not is_automation(r.login) and r.login != item.author]


def latest_verdicts(item: Item) -> dict[str, Review]:
    """Latest approving, change-requesting, or dismissed review per reviewer."""
    verdicts: dict[str, Review] = {}
    for review in sorted(human_reviews(item), key=lambda r: r.at):
        if review.state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            verdicts[review.login] = review
    return {login: r for login, r in verdicts.items() if r.state != "DISMISSED"}


def engaged_since(item: Item, login: str, since: datetime) -> bool:
    return any(r.login == login and r.at > since for r in item.reviews) or replied(
        item, {login}, since
    )


def removed_reviewers(item: Item) -> set[str]:
    return {e.reviewer for e in item.requests if e.removed}


def automatic_requests(item: Item) -> bool:
    return bool(notices(item, "review_request")) or any(
        not e.removed and is_automation(e.actor) for e in item.requests
    )


def author_active_since(item: Item, since: datetime) -> bool:
    if item.last_push and item.last_push > since:
        return True
    return replied(item, {item.author}, since) or any(
        r.login == item.author and r.at > since for r in item.reviews
    )


def owners(item: Item) -> list[str]:
    people = [login for login in item.assignees if not is_automation(login)]
    if people:
        return people
    return [] if is_automation(item.author) else [item.author]


def reviewer_exclusions(item: Item) -> set[str]:
    return {item.author} | removed_reviewers(item) | {r.login for r in item.reviews}


def stale_automatic_requests(item: Item) -> list[str]:
    """Pending requests automation made for someone who had already reviewed or declined."""
    stale = []
    for login in item.requested_users:
        asked = [e for e in item.requests if e.reviewer == login and not e.removed]
        if not asked or not is_automation(asked[-1].actor):
            continue
        at = asked[-1].at
        declined = any(e.reviewer == login and e.removed and e.at < at for e in item.requests)
        reviewed = any(r.login == login and r.at < at for r in item.reviews)
        if declined or reviewed:
            stale.append(login)
    return stale


def plan_reviewer_request(
    item: Item,
    now: datetime,
    pick: Callable[[Item, set[str]], tuple[str | None, str | None]],
    on_open: bool = False,
) -> tuple[Action | None, str]:
    if item.draft:
        return None, "draft"
    if item.requested_users or item.requested_teams:
        return None, "a reviewer is requested"
    if human_reviews(item):
        return None, "already reviewed"
    if automatic_requests(item):
        return None, "an automatic request was already made"
    ready = item.ready_at or item.created
    if not on_open and now < add_business_days(ready, REVIEWER_GRACE):
        return None, "author still has time to pick a reviewer"
    login, rule = pick(item, reviewer_exclusions(item))
    if not login or not rule:
        return None, "no eligible reviewer"
    body = render("review_request", [login], reason=REVIEWER_REASONS[rule])
    return Action("review_request", item.number, [login], body, request_reviewer=login), rule


def waiting_on_author(item: Item) -> datetime | None:
    """Time of the newest unanswered change request, if the author owes a response."""
    requested = [r.at for r in latest_verdicts(item).values() if r.state == "CHANGES_REQUESTED"]
    if not requested:
        return None
    newest = max(requested)
    return None if author_active_since(item, newest) else newest


def plan_review_reminder(item: Item, now: datetime) -> tuple[Action | None, str]:
    if item.draft:
        return None, "draft"
    if not item.requested_users:
        return None, "no pending reviewer"
    if waiting_on_author(item):
        return None, "waiting on the author to address requested changes"
    if any(r.state == "APPROVED" for r in latest_verdicts(item).values()):
        return None, "already approved"
    due: list[str] = []
    exhausted: list[str] = []
    oldest = now
    for login in item.requested_users:
        if is_automation(login):
            continue
        asked = [e.at for e in item.requests if e.reviewer == login and not e.removed]
        since = max(asked) if asked else (item.ready_at or item.created)
        if engaged_since(item, login, since):
            continue
        prior = [n for n in notices(item, "review_reminder", since) if login in n.logins]
        if len(prior) >= REVIEW_REMINDER_MAX:
            told = [n for n in notices(item, "reviewer_unresponsive", since) if login in n.logins]
            if not told and now >= add_business_days(prior[-1].at, REVIEW_REMINDER_REPEAT):
                exhausted.append(login)
            continue
        wait = REVIEW_REMINDER_REPEAT if prior else REVIEW_REMINDER_FIRST
        if now >= add_business_days(prior[-1].at if prior else since, wait):
            due.append(login)
            oldest = min(oldest, since)
    if due:
        days = business_days_between(oldest, now)
        return Action(
            "review_reminder", item.number, due, render("review_reminder", due, days=days)
        ), "reviewer overdue"
    if exhausted and owners(item):
        who = ", ".join(f"`{login}`" for login in exhausted)
        targets = owners(item)
        body = render("reviewer_unresponsive", targets, about=exhausted, who=who)
        return Action("reviewer_unresponsive", item.number, targets, body), (
            "reviewer did not respond to reminders"
        )
    return None, "no reviewer overdue"


def plan_changes_requested(item: Item, now: datetime) -> tuple[Action | None, str]:
    since = waiting_on_author(item)
    if not since:
        return None, "no unanswered change request"
    if notices(item, "changes_requested", since):
        return None, "author already reminded for this review"
    if now < add_business_days(since, CHANGES_REQUESTED_IDLE):
        return None, "change request is recent"
    if is_automation(item.author):
        return None, "author is automation"
    who = ", ".join(
        f"`{login}`" for login, r in latest_verdicts(item).items() if r.state == "CHANGES_REQUESTED"
    )
    days = business_days_between(since, now)
    body = render("changes_requested", [item.author], who=who, days=days)
    return Action("changes_requested", item.number, [item.author], body), "author idle"


def plan_merge(item: Item, now: datetime, default_branch: str) -> tuple[Action | None, str]:
    if item.draft:
        return None, "draft"
    verdicts = latest_verdicts(item)
    approvals = [r.at for r in verdicts.values() if r.state == "APPROVED"]
    if not approvals:
        return None, "not approved"
    if any(r.state == "CHANGES_REQUESTED" for r in verdicts.values()):
        return None, "changes still requested"
    approved = max(approvals)
    if item.last_push and item.last_push > approved:
        return None, "pushed after the last approval"
    if DO_NOT_MERGE.search(item.title):
        return None, "marked do-not-merge"
    if item.base != default_branch or DEPENDENT.search(item.body):
        return None, "depends on another branch or pull request"
    if item.checks in (None, "PENDING", "EXPECTED"):
        return None, "checks still running"
    targets = owners(item)
    if not targets:
        return None, "no human owner"
    prior = notices(item, "merge", approved)
    if len(prior) >= MERGE_NUDGE_MAX:
        return None, "merge reminders exhausted for this approval"
    if prior and standing_reason(item, set(targets), prior[-1].at):
        return None, "owner gave a standing reason"
    wait = MERGE_NUDGE_REPEAT if prior else MERGE_NUDGE_FIRST
    if now < add_business_days(prior[-1].at if prior else approved, wait):
        return None, "approval is recent"
    template = "merge_green" if item.checks == "SUCCESS" else "merge_failing"
    days = business_days_between(approved, now)
    waiting = [f"`{x}`" for x in item.requested_users + item.requested_teams]
    pending = (
        f" Review is still requested from {', '.join(waiting)}; remove the request if it "
        "is not needed."
        if waiting
        else ""
    )
    body = render("merge", targets, template=template, days=days, pending=pending)
    return Action("merge", item.number, targets, body), "approved and idle"


def plan_unreviewed(
    item: Item, now: datetime, backfill_possible: bool
) -> tuple[Action | None, str]:
    if item.draft:
        return None, "draft"
    if item.requested_users or item.requested_teams or human_reviews(item):
        return None, "has a reviewer"
    if backfill_possible:
        return None, "automatic reviewer request still possible"
    targets = owners(item)
    if not targets:
        return None, "no human owner"
    ready = item.ready_at or item.created
    prior = notices(item, "unreviewed", ready)
    if len(prior) >= UNREVIEWED_MAX:
        return None, "unreviewed reminders exhausted"
    if prior and standing_reason(item, set(targets), prior[-1].at):
        return None, "owner gave a standing reason"
    wait = UNREVIEWED_REPEAT if prior else UNREVIEWED_FIRST
    if now < add_business_days(prior[-1].at if prior else ready, wait):
        return None, "ready recently"
    body = render("unreviewed", targets, days=business_days_between(ready, now))
    return Action("unreviewed", item.number, targets, body), "no reviewer"


def plan_draft(item: Item, now: datetime) -> tuple[Action | None, str]:
    if not item.draft:
        return None, "not a draft"
    if DO_NOT_MERGE.search(item.title):
        return None, "marked do-not-merge"
    since = item.draft_at or item.created
    if notices(item, "draft", since):
        return None, "already reminded for this draft"
    if author_active_since(item, add_business_days(since, DRAFT_IDLE // 2)):
        return None, "author is still working on it"
    if now < add_business_days(since, DRAFT_IDLE):
        return None, "draft is recent"
    if is_automation(item.author):
        return None, "author is automation"
    days = business_days_between(since, now)
    return Action(
        "draft", item.number, [item.author], render("draft", [item.author], days=days)
    ), "long-running draft"


def plan_pr(
    item: Item,
    now: datetime,
    default_branch: str,
    pick: Callable[[Item, set[str]], tuple[str | None, str | None]],
) -> tuple[Action | None, list[str]]:
    """Return at most one action per pull request, with the reasons for every skip.

    Withdrawn requests ride on the returned action, or on a silent one.
    """
    skipped: list[str] = []
    withdraw = stale_automatic_requests(item)
    if withdraw:
        item.requested_users = [x for x in item.requested_users if x not in withdraw]
    action, skipped = plan_pr_notice(item, now, default_branch, pick)
    if withdraw:
        action = action or Action("withdraw_request", item.number, [], "")
        action.withdraw = withdraw
    return action, skipped


def plan_pr_notice(
    item: Item,
    now: datetime,
    default_branch: str,
    pick: Callable[[Item, set[str]], tuple[str | None, str | None]],
) -> tuple[Action | None, list[str]]:
    skipped: list[str] = []
    action, why = plan_reviewer_request(item, now, pick)
    if action:
        return action, skipped
    skipped.append(f"review_request: {why}")
    backfill_possible = why == "author still has time to pick a reviewer"
    recent = last_notice(item)
    if recent and now < add_business_days(recent, QUIET_AFTER_NOTICE):
        skipped.append("reminders: another notice was posted recently")
        return None, skipped
    for name, plan in (
        ("review_reminder", lambda: plan_review_reminder(item, now)),
        ("changes_requested", lambda: plan_changes_requested(item, now)),
        ("merge", lambda: plan_merge(item, now, default_branch)),
        ("unreviewed", lambda: plan_unreviewed(item, now, backfill_possible)),
        ("draft", lambda: plan_draft(item, now)),
    ):
        action, why = plan()
        if action:
            return action, skipped
        skipped.append(f"{name}: {why}")
    return None, skipped


def plan_issue(
    item: Item, now: datetime, protected_milestones: set[int] = frozenset()
) -> tuple[Action | None, list[str]]:
    skipped: list[str] = []
    targets = [login for login in item.assignees if not is_automation(login)]
    if not targets:
        return None, ["unassigned"]
    recent = last_notice(item)
    if recent and now < add_business_days(recent, QUIET_AFTER_NOTICE):
        return None, ["another notice was posted recently"]
    due = item.milestone_due
    if due and now <= due <= now + timedelta(days=DUE_SOON_DAYS):
        date = due.date().isoformat()
        if any(date in c.body for c in item.comments if classify(c) and classify(c).kind == "due"):
            skipped.append("due: already reminded for this date")
        else:
            body = render("due", targets, milestone=item.milestone, date=date)
            return Action("due", item.number, targets, body, is_pr=False), skipped
    else:
        skipped.append("due: no milestone due soon")
    if item.milestone_number is None or item.milestone_number in protected_milestones:
        return None, [*skipped, "stale_issue: not scheduled in an OCAH milestone"]
    if due and now <= due <= now + timedelta(days=STALE_SKIP_DUE_DAYS):
        return None, [*skipped, "stale_issue: milestone due within a week"]
    human = [at for at, login in item.activity if not is_automation(login)]
    human += [c.at for c in item.comments if not is_automation(c.login)]
    last = max([item.created, *human])
    prior = notices(item, "stale_issue", last)
    if len(prior) >= STALE_ISSUE_MAX:
        return None, [*skipped, "stale_issue: reminders exhausted until someone responds"]
    since = prior[-1].at if prior else last
    if now < since + timedelta(days=STALE_ISSUE_DAYS):
        return None, [*skipped, "stale_issue: recent activity"]
    body = render("stale_issue", targets, days=(now - last).days)
    return Action("stale_issue", item.number, targets, body, is_pr=False), skipped


# --------------------------------------------------------------------------
# GitHub reads
# --------------------------------------------------------------------------

ACTOR_FIELDS = "createdAt actor{login}"
REVIEWER_FIELDS = "requestedReviewer{__typename ... on User{login} ... on Team{slug}}"
PR_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String){
 repository(owner:$owner,name:$name){pullRequest(number:$number){
  number title body isDraft createdAt baseRefName author{login}
  assignees(first:20){nodes{login}}
  reviewRequests(first:20){nodes{%(reviewer)s}}
  commits(last:1){nodes{commit{committedDate statusCheckRollup{state}}}}
  timelineItems(first:100,after:$cursor,itemTypes:[ISSUE_COMMENT,PULL_REQUEST_REVIEW,
   REVIEW_REQUESTED_EVENT,REVIEW_REQUEST_REMOVED_EVENT,READY_FOR_REVIEW_EVENT,
   CONVERT_TO_DRAFT_EVENT,HEAD_REF_FORCE_PUSHED_EVENT,PULL_REQUEST_COMMIT]){
   pageInfo{hasNextPage endCursor}
   nodes{__typename
    ... on IssueComment{createdAt author{login} body}
    ... on PullRequestReview{submittedAt state author{login}}
    ... on ReviewRequestedEvent{%(actor)s %(reviewer)s}
    ... on ReviewRequestRemovedEvent{%(actor)s %(reviewer)s}
    ... on ReadyForReviewEvent{createdAt}
    ... on ConvertToDraftEvent{createdAt}
    ... on HeadRefForcePushedEvent{createdAt}
    ... on PullRequestCommit{commit{committedDate}}
   }}}}}
""" % {"actor": ACTOR_FIELDS, "reviewer": REVIEWER_FIELDS}
ISSUE_EVENT_TYPES = (
    "AssignedEvent UnassignedEvent CrossReferencedEvent ReferencedEvent RenamedTitleEvent "
    "MilestonedEvent DemilestonedEvent LabeledEvent ReopenedEvent ConnectedEvent"
).split()
ISSUES_QUERY = """
query($owner:String!,$name:String!,$cursor:String){
 repository(owner:$owner,name:$name){issues(states:OPEN,first:25,after:$cursor){
  pageInfo{hasNextPage endCursor}
  nodes{number title createdAt author{login} assignees(first:10){nodes{login}}
   milestone{number title dueOn}
   timelineItems(last:60,itemTypes:[ISSUE_COMMENT,%(types)s]){nodes{__typename
    ... on IssueComment{createdAt author{login} body}
    %(events)s
   }}}}}}
""" % {
    "types": ",".join(re.sub(r"(?<!^)(?=[A-Z])", "_", t).upper() for t in ISSUE_EVENT_TYPES),
    "events": " ".join(f"... on {t}{{{ACTOR_FIELDS}}}" for t in ISSUE_EVENT_TYPES),
}
OPEN_PRS_QUERY = """
query($owner:String!,$name:String!,$cursor:String){
 repository(owner:$owner,name:$name){defaultBranchRef{name}
  pullRequests(states:OPEN,first:100,after:$cursor){
   pageInfo{hasNextPage endCursor} nodes{number}}}}
"""
CURATION_QUERY = """
query($owner:String!,$name:String!,$number:Int!){
 repository(owner:$owner,name:$name){issueOrPullRequest(number:$number){
  ... on Issue{projectItems(first:10){nodes{%(field)s}}}
  ... on PullRequest{projectItems(first:10){nodes{%(field)s}}}}}}
""" % {
    "field": 'project{number} fieldValueByName(name:"Curation state")'
    "{... on ProjectV2ItemFieldSingleSelectValue{name}}"
}


def graphql(query: str, token: str | None, **variables) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is not None:
            args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    return gh_json(args, token)["data"]["repository"]


def login_of(node: dict | None) -> str:
    return ((node or {}).get("login")) or ""


def reviewer_of(node: dict) -> str:
    reviewer = node.get("requestedReviewer") or {}
    return reviewer.get("login") or reviewer.get("slug") or ""


def normalize_pr(pages: list[dict]) -> Item:
    pr = pages[0]
    head = ((pr.get("commits") or {}).get("nodes") or [{}])[-1].get("commit") or {}
    item = Item(
        number=pr["number"],
        title=pr.get("title") or "",
        author=login_of(pr.get("author")),
        created=parse_time(pr["createdAt"]),
        assignees=[n["login"] for n in pr["assignees"]["nodes"]],
        body=pr.get("body") or "",
        draft=bool(pr.get("isDraft")),
        base=pr.get("baseRefName") or "main",
        checks=(head.get("statusCheckRollup") or {}).get("state"),
    )
    for node in pr["reviewRequests"]["nodes"]:
        reviewer = node.get("requestedReviewer") or {}
        if reviewer.get("__typename") == "Team":
            item.requested_teams.append(reviewer.get("slug") or "")
        elif reviewer.get("login"):
            item.requested_users.append(reviewer["login"])
    pushes: list[datetime] = []
    for page in pages:
        for node in page["timelineItems"]["nodes"]:
            kind = node.get("__typename")
            if kind == "IssueComment":
                item.comments.append(
                    Comment(
                        login_of(node.get("author")),
                        parse_time(node["createdAt"]),
                        node.get("body") or "",
                    )
                )
            elif kind == "PullRequestReview" and node.get("submittedAt"):
                item.reviews.append(
                    Review(
                        login_of(node.get("author")), node["state"], parse_time(node["submittedAt"])
                    )
                )
            elif kind in ("ReviewRequestedEvent", "ReviewRequestRemovedEvent"):
                item.requests.append(
                    RequestEvent(
                        parse_time(node["createdAt"]),
                        login_of(node.get("actor")),
                        reviewer_of(node),
                        kind == "ReviewRequestRemovedEvent",
                    )
                )
            elif kind == "ReadyForReviewEvent":
                item.ready_at = parse_time(node["createdAt"])
            elif kind == "ConvertToDraftEvent":
                item.draft_at = parse_time(node["createdAt"])
            elif kind == "HeadRefForcePushedEvent":
                pushes.append(parse_time(node["createdAt"]))
            elif kind == "PullRequestCommit":
                pushes.append(parse_time(node["commit"]["committedDate"]))
    item.last_push = max(pushes) if pushes else None
    return item


def normalize_issue(node: dict) -> Item:
    milestone = node.get("milestone") or {}
    item = Item(
        number=node["number"],
        title=node.get("title") or "",
        author=login_of(node.get("author")),
        created=parse_time(node["createdAt"]),
        assignees=[n["login"] for n in node["assignees"]["nodes"]],
        is_pr=False,
        milestone=milestone.get("title"),
        milestone_number=milestone.get("number"),
        milestone_due=parse_time(milestone.get("dueOn")),
    )
    for event in node["timelineItems"]["nodes"]:
        if event.get("__typename") == "IssueComment":
            item.comments.append(
                Comment(
                    login_of(event.get("author")),
                    parse_time(event["createdAt"]),
                    event.get("body") or "",
                )
            )
        elif event.get("createdAt"):
            item.activity.append((parse_time(event["createdAt"]), login_of(event.get("actor"))))
    return item


def fetch_pr(owner: str, name: str, number: int, token: str | None) -> Item:
    pages, cursor = [], None
    while True:
        page = graphql(PR_QUERY, token, owner=owner, name=name, number=number, cursor=cursor)
        pages.append(page["pullRequest"])
        info = page["pullRequest"]["timelineItems"]["pageInfo"]
        if not info["hasNextPage"]:
            return normalize_pr(pages)
        cursor = info["endCursor"]


def fetch_open_prs(owner: str, name: str, token: str | None) -> tuple[str, list[int]]:
    numbers, cursor, default = [], None, "main"
    while True:
        repo = graphql(OPEN_PRS_QUERY, token, owner=owner, name=name, cursor=cursor)
        default = (repo.get("defaultBranchRef") or {}).get("name") or default
        numbers += [n["number"] for n in repo["pullRequests"]["nodes"]]
        if not repo["pullRequests"]["pageInfo"]["hasNextPage"]:
            return default, numbers
        cursor = repo["pullRequests"]["pageInfo"]["endCursor"]


def fetch_open_issues(owner: str, name: str, token: str | None) -> list[Item]:
    items, cursor = [], None
    while True:
        repo = graphql(ISSUES_QUERY, token, owner=owner, name=name, cursor=cursor)
        items += [normalize_issue(n) for n in repo["issues"]["nodes"]]
        if not repo["issues"]["pageInfo"]["hasNextPage"]:
            return items
        cursor = repo["issues"]["pageInfo"]["endCursor"]


def curation_locked(owner: str, name: str, number: int, project: int, token: str | None) -> bool:
    if not token:
        return False
    try:
        repo = graphql(CURATION_QUERY, token, owner=owner, name=name, number=number)
    except (subprocess.CalledProcessError, KeyError, TypeError):
        return False
    for node in ((repo.get("issueOrPullRequest") or {}).get("projectItems") or {}).get(
        "nodes"
    ) or []:
        value = node.get("fieldValueByName") or {}
        if (node.get("project") or {}).get("number") == project and value.get("name") == "Locked":
            return True
    return False


def taxonomy_list(text: str, section: str, key: str) -> list[str]:
    """Read a two-level `section: key: - value` list without PyYAML."""
    values, in_section, in_key = [], False, False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            in_section, in_key = line.rstrip() == f"{section}:", False
        elif in_section and line.startswith("  ") and not line.startswith("    "):
            in_key = line.strip() == f"{key}:"
        elif in_key and line.strip().startswith("- "):
            values.append(line.strip()[2:].strip().strip('"'))
    return values


def automation_enabled(text: str) -> bool:
    match = re.search(r"(?m)^automation:\n(?:  .*\n)*?  enabled:\s*(\S+)", text)
    return bool(match) and match.group(1).lower() == "true"


# --------------------------------------------------------------------------
# GitHub writes
# --------------------------------------------------------------------------


def make_picker(repo_full: str, pool: list[str], token: str | None):
    owner, name = repo_full.split("/", 1)
    query = (
        "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){"
        "pullRequest(number:$number){body suggestedReviewers{isAuthor reviewer{login}} "
        "closingIssuesReferences(first:10){nodes{assignees(first:10){nodes{login}}}}}}}"
    )

    def pick(item: Item, excluded: set[str]) -> tuple[str | None, str | None]:
        pr = graphql(query, token, owner=owner, name=name, number=item.number)["pullRequest"]
        return pick_reviewer(
            item.author,
            _suggested_reviewer_logins(pr),
            _linked_issue_assignees(repo_full, pr),
            _path_history_authors(repo_full, item.number, item.base),
            pool,
            usable=lambda login: (
                login not in excluded
                and not is_automation(login)
                and login_is_assignable(repo_full, login)
            ),
        )

    return pick


def apply(action: Action, repo_full: str) -> bool:
    noun = "pr" if action.is_pr else "issue"
    for login in action.withdraw:
        try:
            run(
                [
                    "gh",
                    "pr",
                    "edit",
                    str(action.number),
                    "--repo",
                    repo_full,
                    "--remove-reviewer",
                    login,
                ]
            )
        except subprocess.CalledProcessError as exc:
            print(f"#{action.number}: withdraw {login} failed: {exc.stderr}", file=sys.stderr)
    if not action.body:
        return True
    if action.request_reviewer:
        try:
            run(
                [
                    "gh",
                    "pr",
                    "edit",
                    str(action.number),
                    "--repo",
                    repo_full,
                    "--add-reviewer",
                    action.request_reviewer,
                ]
            )
        except subprocess.CalledProcessError as exc:
            print(f"#{action.number}: reviewer request failed: {exc.stderr}", file=sys.stderr)
            return False
    run(["gh", noun, "comment", str(action.number), "--repo", repo_full, "--body", action.body])
    return True


def report(lines: list[str]) -> None:
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"```\n{text}\n```\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="post; default prints the plan")
    parser.add_argument("--pr", type=int, help="only this pull request")
    parser.add_argument(
        "--on-open",
        action="store_true",
        help="with --pr: request a reviewer without the scheduled grace period",
    )
    parser.add_argument("--now", help="ISO time to plan for; default is the current time")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="also print every skip reason")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return

    repo_full = os.environ.get("GITHUB_REPOSITORY", REPO)
    owner, name = repo_full.split("/", 1)
    read_token = os.environ.get("CURATOR_READ_TOKEN") or None
    taxonomy_path = github_dir() / "issue-taxonomy.yml"
    text = taxonomy_path.read_text(encoding="utf-8")
    if not automation_enabled(text):
        print("automation.enabled is not true; nothing to do")
        return
    protected = set(taxonomy_list(text, "protection", "authors"))
    protected_milestones = {int(n) for n in taxonomy_list(text, "protection", "milestone_numbers")}
    pool = reviewer_pool(load_taxonomy(taxonomy_path))
    pick = make_picker(repo_full, pool, read_token)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)

    if args.pr:
        item = fetch_pr(owner, name, args.pr, read_token)
        if args.on_open:
            action, why = plan_reviewer_request(item, now, pick, on_open=True)
            plans = [(item, action, [] if action else [f"review_request: {why}"])]
        else:
            default, _ = fetch_open_prs(owner, name, read_token)
            plans = [(item, *plan_pr(item, now, default, pick))]
    else:
        default, numbers = fetch_open_prs(owner, name, read_token)
        plans = []
        for number in numbers:
            item = fetch_pr(owner, name, number, read_token)
            plans.append((item, *plan_pr(item, now, default, pick)))
        if now.weekday() < 5:
            plans += [
                (i, *plan_issue(i, now, protected_milestones))
                for i in fetch_open_issues(owner, name, read_token)
            ]

    lines = [f"curator-notify {now.isoformat()} {'apply' if args.apply else 'dry run'}"]
    per_person: dict[str, int] = {}
    for item, action, skipped in sorted(plans, key=lambda p: (not p[0].is_pr, p[0].number)):
        if item.author in protected:
            action, skipped = None, ["protected author"]
        if (
            action
            and now.weekday() >= 5
            and action.kind not in ("review_request", "withdraw_request")
        ):
            action, skipped = None, [*skipped, "weekend"]
        if action and action.kind not in ("review_request", "withdraw_request"):
            if any(per_person.get(login, 0) >= PER_PERSON_PER_RUN for login in action.logins):
                withdraw = action.withdraw
                action = Action("withdraw_request", item.number, [], "") if withdraw else None
                if action:
                    action.withdraw = withdraw
                skipped = [*skipped, "deferred: per-person limit for this run"]
        if action and curation_locked(owner, name, item.number, 291, read_token):
            action, skipped = None, [*skipped, "Curation state is Locked"]
        if action and action.kind != "review_request":
            for login in action.logins:
                per_person[login] = per_person.get(login, 0) + 1
        if action:
            done = apply(action, repo_full) if args.apply else True
            state = "posted" if args.apply and done else ("failed" if args.apply else "would post")
            withdrawn = f" (withdraw {', '.join(action.withdraw)})" if action.withdraw else ""
            lines.append(
                f"#{item.number} {action.kind} -> {', '.join(action.logins)}{withdrawn}: {state}"
            )
        elif args.verbose:
            lines.append(f"#{item.number} skip: {'; '.join(skipped)}")
    report(lines)


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------


def t(value: str) -> datetime:
    return parse_time(value)


def no_pick(item: Item, excluded: set[str]) -> tuple[str | None, str | None]:
    return None, None


def pool_pick(pool: list[str]) -> Callable[[Item, set[str]], tuple[str | None, str | None]]:
    def pick(item: Item, excluded: set[str]) -> tuple[str | None, str | None]:
        return pick_reviewer(item.author, [], [], [], pool, usable=lambda x: x not in excluded)

    return pick


def bot_comment(at: str, body: str) -> Comment:
    return Comment("tenstorrent-gh-bot-adm", t(at), body)


def pr_3315(**changes) -> Item:
    """PR #3315 as of 2026-10-25: the author swapped the automatic reviewer for
    minshaohoTT, who requested changes; the curator then re-requested the
    removed reviewer three times."""
    pool_line = (
        "@aottavianoTT — you've been automatically requested to review this pull request "
        "because you are next in the repository reviewer pool."
    )
    item = Item(
        number=3315,
        title="hw/ip/efuse: Move the eFuse guard before the request issuer",
        author="nboettcher-tenstorrent",
        created=t("2026-10-21T20:42:09Z"),
        assignees=["nboettcher-tenstorrent"],
        comments=[
            Comment(
                "github-actions[bot]",
                t("2026-10-21T20:42:40Z"),
                "@aottavianoTT — you've been automatically requested to review this pull "
                "request because you recently committed to files this pull request "
                "touches.\n\n<!-- github-auto-review-request -->",
            ),
            bot_comment("2026-10-23T12:24:02Z", pool_line),
            bot_comment("2026-10-23T23:20:26Z", pool_line),
        ],
        requests=[
            RequestEvent(t("2026-10-21T20:42:39Z"), "github-actions[bot]", "aottavianoTT", False),
            RequestEvent(t("2026-10-21T21:25:52Z"), "nboettcher-tenstorrent", "aottavianoTT", True),
            RequestEvent(t("2026-10-22T18:27:39Z"), "nboettcher-tenstorrent", "minshaohoTT", False),
            RequestEvent(
                t("2026-10-23T12:24:00Z"), "tenstorrent-gh-bot-adm", "aottavianoTT", False
            ),
            RequestEvent(t("2026-10-23T17:32:09Z"), "aottavianoTT", "aottavianoTT", True),
            RequestEvent(
                t("2026-10-23T23:20:24Z"), "tenstorrent-gh-bot-adm", "aottavianoTT", False
            ),
        ],
        reviews=[
            Review("minshaohoTT", "CHANGES_REQUESTED", t("2026-10-23T01:00:43Z")),
            Review("aottavianoTT", "APPROVED", t("2026-10-24T21:55:34Z")),
        ],
        last_push=t("2026-10-21T20:30:00Z"),
        checks="SUCCESS",
    )
    for key, value in changes.items():
        setattr(item, key, value)
    return item


def pr_3362(**changes) -> Item:
    """PR #3362 as of 2026-10-25: approved by its requested reviewer, then the
    curator requested a pool reviewer because no request was pending."""
    item = Item(
        number=3362,
        title="hw/smc: Add SMC cluster MMIO I3C support",
        author="TT-kqin",
        created=t("2026-10-23T22:49:27Z"),
        assignees=["TT-kqin"],
        requests=[
            RequestEvent(t("2026-10-23T22:49:27Z"), "TT-kqin", "minshaohoTT", False),
        ],
        reviews=[
            Review("minshaohoTT", "CHANGES_REQUESTED", t("2026-10-24T05:46:56Z")),
            Review("minshaohoTT", "APPROVED", t("2026-10-24T05:47:54Z")),
        ],
        last_push=t("2026-10-23T22:40:00Z"),
        checks="SUCCESS",
    )
    for key, value in changes.items():
        setattr(item, key, value)
    return item


def kinds(item: Item, now: str, pick=None) -> str | None:
    action, _ = plan_pr(item, t(now), "main", pick or pool_pick(["aottavianoTT", "nbetikTT"]))
    return action.kind if action else None


def self_test() -> None:
    assert add_business_days(t("2026-10-23T10:00:00Z"), 1) == t("2026-10-26T10:00:00Z")
    assert business_days_between(t("2026-10-23T10:00:00Z"), t("2026-10-27T09:00:00Z")) == 2
    text = (github_dir() / "issue-taxonomy.yml").read_text(encoding="utf-8")
    assert automation_enabled(text)
    assert taxonomy_list(text, "protection", "authors") == ["bonnie-banks123", "DanielG-lowRISC"]

    # The incidents: an approved PR and a PR whose author removed the
    # automatic reviewer get no reviewer request, at any time.
    for when in ("2026-10-25T23:18:00Z", "2026-10-27T12:00:00Z"):
        assert kinds(pr_3362(), when) != "review_request"
        assert kinds(pr_3315(), when) != "review_request"
    # The curator's last re-request on #3315, for a reviewer who had approved,
    # is withdrawn silently; nobody is pinged for it.
    rerequested = pr_3315(
        requested_users=["aottavianoTT"],
        requests=[
            *pr_3315().requests,
            RequestEvent(
                t("2026-10-25T23:18:15Z"), "tenstorrent-gh-bot-adm", "aottavianoTT", False
            ),
        ],
    )
    action, _ = plan_pr(rerequested, t("2026-10-26T12:00:00Z"), "main", no_pick)
    assert action.kind == "withdraw_request" and action.withdraw == ["aottavianoTT"]
    assert not action.body
    action, _ = plan_pr(
        pr_3315(requested_users=["aottavianoTT"], requests=rerequested.requests),
        t("2026-10-28T12:00:00Z"),
        "main",
        no_pick,
    )
    assert action.kind == "changes_requested" and action.withdraw == ["aottavianoTT"]
    asked_again = pr_3315(
        requested_users=["aottavianoTT"],
        requests=[
            *pr_3315().requests,
            RequestEvent(
                t("2026-10-25T10:00:00Z"), "nboettcher-tenstorrent", "aottavianoTT", False
            ),
        ],
    )
    assert not stale_automatic_requests(asked_again), "the author may ask again"
    # #3315 waits on its author after minshaohoTT's change request.
    assert kinds(pr_3315(), "2026-10-26T12:00:00Z") is None
    assert kinds(pr_3315(), "2026-10-28T12:00:00Z") == "changes_requested"
    late = pr_3315(
        comments=[
            *pr_3315().comments,
            Comment(
                "tenstorrent-gh-bot-adm",
                t("2026-10-28T12:00:00Z"),
                "@nboettcher-tenstorrent — x\n\n<!-- ocah-notify:changes_requested:nboettcher-tenstorrent -->",
            ),
        ]
    )
    assert kinds(late, "2026-11-04T12:00:00Z") is None, "one nudge per change request"
    # #3362 is approved with green checks: one merge nudge after 3 business days.
    assert kinds(pr_3362(), "2026-10-27T12:00:00Z") is None
    action, _ = plan_pr(pr_3362(), t("2026-10-29T12:00:00Z"), "main", no_pick)
    assert action and action.kind == "merge" and action.logins == ["TT-kqin"]
    assert action.body.endswith("<!-- ocah-notify:merge:TT-kqin -->")
    assert kinds(pr_3362(last_push=t("2026-10-26T00:00:00Z")), "2026-11-02T12:00:00Z") is None
    assert kinds(pr_3362(checks="PENDING"), "2026-10-29T12:00:00Z") is None
    assert kinds(pr_3362(title="[DO NOT MERGE] x"), "2026-10-29T12:00:00Z") is None
    assert kinds(pr_3362(body="Depends on #3300"), "2026-10-29T12:00:00Z") is None

    fresh = dict(reviews=[], requests=[], comments=[], last_push=None, checks=None)
    # Backfill waits a business day, then never picks the author, a removed
    # reviewer, or anyone who already reviewed.
    opened = pr_3362(**fresh)
    assert kinds(opened, "2026-10-23T23:00:00Z") is None
    action, _ = plan_pr(opened, t("2026-10-26T23:00:00Z"), "main", pool_pick(["aottavianoTT"]))
    assert action.kind == "review_request" and action.request_reviewer == "aottavianoTT"
    declined = pr_3362(
        **{
            **fresh,
            "requests": [
                RequestEvent(t("2026-10-23T23:00:00Z"), "TT-kqin", "aottavianoTT", False),
                RequestEvent(t("2026-10-23T23:30:00Z"), "TT-kqin", "aottavianoTT", True),
            ],
        }
    )
    action, _ = plan_pr(
        declined, t("2026-10-26T23:00:00Z"), "main", pool_pick(["aottavianoTT", "nbetikTT"])
    )
    assert action.request_reviewer == "nbetikTT"
    # One automatic request per PR: once it is declined, the owner is told.
    auto_declined = pr_3362(
        **{
            **fresh,
            "requests": [
                RequestEvent(
                    t("2026-10-23T23:00:00Z"), "github-actions[bot]", "aottavianoTT", False
                ),
                RequestEvent(t("2026-10-24T10:00:00Z"), "aottavianoTT", "aottavianoTT", True),
            ],
        }
    )
    assert kinds(auto_declined, "2026-10-27T23:00:00Z") is None
    assert kinds(auto_declined, "2026-10-28T23:00:00Z") == "unreviewed"

    # Review reminders: 2 business days after the request, then every 3, at
    # most twice; then the owner hears once. A reply stops them.
    pending = pr_3362(
        **{
            **fresh,
            "requested_users": ["minshaohoTT"],
            "requests": [RequestEvent(t("2026-10-23T22:49:27Z"), "TT-kqin", "minshaohoTT", False)],
        }
    )
    assert kinds(pending, "2026-10-26T23:00:00Z") is None
    assert kinds(pending, "2026-10-27T23:00:00Z") == "review_reminder"
    replied_pr = pr_3362(
        **{
            **fresh,
            "requested_users": ["minshaohoTT"],
            "requests": pending.requests,
            "comments": [Comment("minshaohoTT", t("2026-10-26T09:00:00Z"), "looking")],
        }
    )
    assert kinds(replied_pr, "2026-10-28T23:00:00Z") is None

    def reminded(*times: str) -> Item:
        notes = [
            bot_comment(at, "@minshaohoTT — r\n\n<!-- ocah-notify:review_reminder:minshaohoTT -->")
            for at in times
        ]
        return pr_3362(
            **{
                **fresh,
                "requested_users": ["minshaohoTT"],
                "requests": pending.requests,
                "comments": notes,
            }
        )

    assert kinds(reminded("2026-10-27T23:00:00Z"), "2026-10-30T22:00:00Z") is None
    assert kinds(reminded("2026-10-27T23:00:00Z"), "2026-10-30T23:00:00Z") == "review_reminder"
    both = reminded("2026-10-27T23:00:00Z", "2026-10-30T23:00:00Z")
    assert kinds(both, "2026-11-04T22:00:00Z") is None
    action, _ = plan_pr(both, t("2026-11-04T23:00:00Z"), "main", no_pick)
    assert action.kind == "reviewer_unresponsive"
    assert action.body.startswith("@TT-kqin — `minshaohoTT`")
    assert action.body.endswith("<!-- ocah-notify:reviewer_unresponsive:minshaohoTT -->")
    told = Item(
        **{
            **both.__dict__,
            "comments": [*both.comments, bot_comment("2026-11-04T23:00:00Z", action.body)],
        }
    )
    assert kinds(told, "2026-11-20T23:00:00Z") is None, "the owner is told once"

    # An approved PR stops reviewer reminders; the merge nudge names the
    # leftover request without pinging it.
    approved_pending = pr_3362(
        requested_users=["hliaott"],
        requests=[
            *pr_3362().requests,
            RequestEvent(t("2026-10-23T22:49:27Z"), "TT-kqin", "hliaott", False),
        ],
    )
    assert kinds(approved_pending, "2026-10-27T12:00:00Z") is None
    action, _ = plan_pr(approved_pending, t("2026-10-29T12:00:00Z"), "main", no_pick)
    assert action.kind == "merge" and "`hliaott`" in action.body and "@hliaott" not in action.body

    # Legacy curator comments without a marker still count.
    legacy = bot_comment(
        "2026-10-25T23:18:30Z",
        "@aottavianoTT — you've been automatically "
        "requested to review this pull request because x.\n\n"
        "<!-- gh-aw-agentic-workflow: OCAH Project Curator -->",
    )
    assert classify(legacy).kind == "review_request"
    assert classify(legacy).logins == ["aottavianoTT"]
    assert classify(Comment("someone", t("2026-10-25T00:00:00Z"), legacy.body)) is None

    # Drafts: one reminder after 10 quiet business days.
    draft = pr_3362(**{**fresh, "draft": True})
    assert kinds(draft, "2026-11-05T23:00:00Z") is None
    assert kinds(draft, "2026-11-06T23:00:00Z") == "draft"
    assert (
        kinds(
            pr_3362(**{**fresh, "draft": True, "last_push": t("2026-11-04T00:00:00Z")}),
            "2026-11-06T23:00:00Z",
        )
        is None
    )

    # Issues: due reminder once per date, stale reminder after 21 quiet days.
    issue = Item(
        number=1,
        title="x",
        author="a",
        created=t("2026-09-01T00:00:00Z"),
        assignees=["bob"],
        is_pr=False,
        milestone="v1.0.0",
        milestone_number=26,
        milestone_due=t("2026-10-28T00:00:00Z"),
    )
    action, _ = plan_issue(issue, t("2026-10-26T12:00:00Z"))
    assert action.kind == "due" and "2026-10-28" in action.body
    issue.comments.append(bot_comment("2026-10-26T12:00:00Z", action.body))
    assert plan_issue(issue, t("2026-10-27T13:00:00Z"))[0] is None
    issue.milestone_due = None
    action, _ = plan_issue(issue, t("2026-10-27T13:00:00Z"))
    assert action and action.kind == "stale_issue"
    assert plan_issue(issue, t("2026-10-27T13:00:00Z"), {26})[0] is None, "protected milestone"
    backlog = Item(**{**issue.__dict__, "milestone": None, "milestone_number": None})
    assert plan_issue(backlog, t("2026-10-27T13:00:00Z"))[0] is None, "unscheduled backlog"
    issue.activity.append((t("2026-10-20T00:00:00Z"), "bob"))
    assert plan_issue(issue, t("2026-10-27T13:00:00Z"))[0] is None
    print("self-test ok")


if __name__ == "__main__":
    main()
