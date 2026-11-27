#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scheduled sweep for org Project 291: add new and edited issues, fill empty fields.

This is the board part of ingest_github.py --issue, run on a schedule for the issues
of three repositories. It imports nothing from ingest_github.py, so the event job
(issue-pr-ingest.yml) keeps its own code unchanged. The parsing rules are copies;
test_project_291_sweep.py checks that they give the same results as the originals.

What it does, for each repository:
- list the issues updated since T (2 hours; 7 days on the daily long run);
- when SWEEP_BACKFILL_SINCE is set (the workflow sets it on one run an hour), after the
  writes of the normal window, also list the issues CREATED since that moment (the
  catch-up backlog) and work on them oldest first;
- keep only issues that were opened or edited since T (created, body edited, or
  title renamed). These are the events that start the event job today;
- read the form fields Workstream, Subsystem, Component, Priority, Target release;
- add the issue to Project 291 when it is not on the board;
- set a field only when it is EMPTY on the board and only to a value that is an
  option of that board field.

It never writes a label, a title, an assignee or a milestone: the event job does
that at once with the built-in token. It never changes a field that has a value,
never touches an archived item, and never adds back an issue that someone removed
from the board (its timeline shows the removal).

Repositories are known by id and node id only. Repository 1 is this one (public).
Repositories 2 and 3 are private; their names are not in this file, no request carries
them, and no query selects a field that holds a repository or owner name or an URL.

Logs: this repository is public, so its run logs are public. Project 291 and two of
the repositories are private. By default the script prints totals only. With
SWEEP_LOG_DETAILS=1 (never set in the workflow) it also prints skip reasons and one
line per write, and even then only for repository 1. Error messages hold only an HTTP
status code, GraphQL error type names and fixed text: never GitHub's message text, a
URL, a query, variables or an answer body. The token is only sent in the Authorization
header and is never printed.

Guard: the sweep never writes over a value, so the danger is a wrong read.
- Each add: the board must answer with a NEW item. If it returns an item that is older
  than a few minutes, the read said "not on the board" but it was: stop (exit 8).
- Each field write: the item is read again right before the write. If the field now
  has a value, or the item is archived, the write is skipped. If the item is on
  another project, stop (exit 8).
- The first field write of a run is read back. If the board does not show the value
  just written, stop (exit 8).

Environment:
  PROJECT_BOARD_TOKEN  Token with organization_projects write and issues read on the
                       three repositories.
  SWEEP_MODE           "dry-run" (default: count, write nothing) or "write".
  SWEEP_MAX_WRITES     Writes per run (adds plus field writes), 1 to 300. Default 20.
  SWEEP_WINDOW         "short" (default, 2 hours) or "long" (7 days).
  SWEEP_BACKFILL_SINCE ISO date and time, for example 2026-11-08T00:00:00Z. When it is
                       set and not older than 60 days, the run also works on the issues
                       created since then, oldest first, after the normal window. Empty:
                       unset. Older than 60 days: ignored, with one log line. Not a date,
                       or in the future: exit 2 before any read.
  SWEEP_LOG_DETAILS    "1" prints skip reasons and per-write lines for repository 1.

Exit codes: 0 done; 1 internal error; 2 bad setup or auth error; 3 rate limit (the
next run continues); 4 network or server error; 5 GraphQL error or too many write
errors; 6 a repository or the board cannot be read; 7 the board is not the expected
one or its fields cannot be read in full; 8 guard (disable the workflow, tell OSPO).
"""

from __future__ import annotations

import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

GRAPHQL_URL = "https://api.github.com/graphql"
USER_AGENT = "tt-oca-harness-project-291-sweep"

PROJECT_ID = "PVT_kwDOA9MHEM4BQ_VB"  # org Project 291
PROJECT_NUMBER = 291

# 1 = tenstorrent/tt-oca-harness (public). 2 and 3 = the two private companion
# repositories, by id only. Ids also survive a rename.
REPOSITORY_IDS = (1172837287, 1273626625, 980240239)
REPOSITORY_NODE_IDS = ("R_kgDORegTpw", "R_kgDOS-oAAQ", "R_kgDOOm1Hbw")  # same order
TAXONOMY_REPOSITORY = 1  # only repository 1's taxonomy file is on this runner

DEFAULT_MAX_WRITES = 20
MAX_WRITES_LIMIT = 300
MAX_WRITE_ERRORS = 3
WRITE_INTERVAL_SECONDS = 1.0
READ_BACK_WAIT_SECONDS = 2.0
WINDOWS = {"short": timedelta(hours=2), "long": timedelta(days=7)}
BACKFILL_MAX_AGE = timedelta(days=60)
# Catch-up list: the repository's issues by creation time, newest first, paged until an
# issue is older than SWEEP_BACKFILL_SINCE. At most BACKLOG_MAX_PAGES pages (2,000
# issues) per repository and run; beyond that, a warning and exit 0.
BACKLOG_MAX_PAGES = 40
# An item that the add mutation returns must be newer than this, else it existed.
NEW_ITEM_TOLERANCE = timedelta(minutes=5)
PAGE_SIZE = 50
MAX_PAGES = 40  # 2,000 changed issues per repository and window
MIN_RATE_REMAINING = 500
HTTP_TIMEOUT_SECONDS = 60
SERVER_RETRY_WAITS = (5, 15)

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_SETUP = 2
EXIT_RATE_LIMIT = 3
EXIT_SERVER = 4
EXIT_GRAPHQL = 5
EXIT_UNREADABLE = 6
EXIT_BOARD = 7
EXIT_GUARD = 8

WRITE_ERRORS_STOP = (
    f"{MAX_WRITE_ERRORS} write errors in this run; stopped. The work before them is done."
    " The next run tries the same writes again; if this repeats, tell OSPO (open an OSPO ticket)."
)

GUARD_ADVICE = (
    " No further write in this run. This job cannot remember this between runs: the team"
    " must disable the workflow 'Project 291 sweep' now (Actions, Project 291 sweep, Disable"
    " workflow) and tell OSPO (open an OSPO ticket)."
)

# ---------------------------------------------------------------------------
# Copied from ingest_github.py. Keep identical (the unit tests compare them).
# ---------------------------------------------------------------------------

EMPTY_MARKERS = {"", "_no response_", "none", "n/a", "skip"}
HEADING = re.compile(r"^### ([^\n]+)\n+([^\n#]+)", re.MULTILINE)
BRACKET_PREFIX = re.compile(r"^\[([A-Z]+)/([A-Z]+)(?:-([A-Z]+))?\]")

TAXONOMY_FIELDS = (
    "Workstream",
    "Subsystem",
    "Component",
    "Priority",
    "Target release",
)


def form_fields(body: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in HEADING.finditer(body or ""):
        found[match.group(1).strip()] = match.group(2).strip()
    return found


def picked(value: str | None, allowed: list[str]) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned.lower() in EMPTY_MARKERS:
        return None
    if cleaned in allowed:
        return cleaned
    return None


def wsc_from_title(title: str, fields: dict) -> tuple[str | None, str | None, str | None]:
    """Extract (workstream, subsystem, component) from a [WS/SS] or [WS/SS-CC] title prefix."""
    m = BRACKET_PREFIX.match(title.strip())
    if not m:
        return None, None, None
    ws, ss, cc = m.group(1), m.group(2), m.group(3)
    if ws not in fields.get("Workstream", []) or ss not in fields.get("Subsystem", []):
        return None, None, None
    component = cc if cc and cc in fields.get("Component", []) else "General"
    return ws, ss, component


def taxonomy_fields(path: Path) -> dict[str, list[str]]:
    """project.fields lists, read like ingest_github._taxonomy_from_simple_yaml."""
    text = path.read_text(encoding="utf-8")
    fields: dict[str, list[str]] = {}
    current: str | None = None
    in_fields = False
    in_pool = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("  reviewer_pool:"):
            in_pool = True
            in_fields = False
            continue
        if in_pool:
            if line.startswith("    - "):
                continue
            if line and not line.startswith("    "):
                in_pool = False
        if line.startswith("  fields:"):
            in_fields = True
            continue
        if in_fields and line and not line.startswith(" "):
            in_fields = False
            current = None
            continue
        if (
            in_fields
            and line.startswith("    ")
            and not line.startswith("      ")
            and line.endswith(":")
        ):
            current = line.strip()[:-1]
            fields[current] = []
            continue
        if in_fields and current and line.startswith("      - "):
            fields[current].append(line[len("      - ") :].strip())
    return fields


# ---------------------------------------------------------------------------
# Pure logic (unit tested).
# ---------------------------------------------------------------------------


class SweepStop(Exception):
    """Stop the run with an exit code. The message never holds item data or a body."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_max_writes(value: str | None) -> int:
    """SWEEP_MAX_WRITES -> int. Missing or empty: 20. Refuses non-numbers, 0 and above 300."""
    if value is None or not str(value).strip():
        return DEFAULT_MAX_WRITES
    text = str(value).strip()
    if not text.isdigit():
        raise SweepStop(EXIT_SETUP, "SWEEP_MAX_WRITES must be a whole number from 1 to 300")
    number = int(text)
    if number < 1 or number > MAX_WRITES_LIMIT:
        raise SweepStop(
            EXIT_SETUP, f"SWEEP_MAX_WRITES={number} is refused; allowed: 1 to {MAX_WRITES_LIMIT}"
        )
    return number


def parse_choice(name: str, value: str | None, allowed: tuple[str, ...], default: str) -> str:
    text = (value or "").strip() or default
    if text not in allowed:
        raise SweepStop(EXIT_SETUP, f"{name} must be one of: {', '.join(allowed)}")
    return text


def backfill_start(value: str | None, now: datetime) -> tuple[datetime | None, str | None]:
    """SWEEP_BACKFILL_SINCE -> (start or None, log note or None). Never echoes the value."""
    if value is None or not str(value).strip():
        return None, None
    try:
        start = parse_time(str(value))
    except ValueError:
        start = None
    if start is None:
        raise SweepStop(
            EXIT_SETUP, "SWEEP_BACKFILL_SINCE is not an ISO date and time; no read was made"
        )
    if start > now:
        raise SweepStop(EXIT_SETUP, "SWEEP_BACKFILL_SINCE is in the future; no read was made")
    if start < now - BACKFILL_MAX_AGE:
        return None, (
            "Note: SWEEP_BACKFILL_SINCE is older than 60 days and is ignored; "
            "the normal window is used."
        )
    return start, None


def _count(value) -> int | None:
    """An int totalCount, else None. bool is not a count."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _connection_ok(value, need_nodes: bool = True) -> bool:
    if not isinstance(value, dict) or _count(value.get("totalCount")) is None:
        return False
    return not need_nodes or isinstance(value.get("nodes"), list)


def _field_values_ok(item: dict) -> bool:
    values = item.get("fieldValues")
    return (
        isinstance(values, dict)
        and isinstance(values.get("nodes"), list)
        and isinstance(values.get("pageInfo"), dict)
        and all(node is None or isinstance(node, dict) for node in values["nodes"])
    )


def issue_shape_ok(issue) -> bool:
    """True when an issue answer has every part the plan reads, with the right types."""
    if not isinstance(issue, dict):
        return False
    if not isinstance(issue.get("id"), str) or _count(issue.get("number")) is None:
        return False
    if not isinstance(issue.get("createdAt"), str):
        return False
    for key in ("lastEditedAt", "title", "body"):
        if issue.get(key) is not None and not isinstance(issue.get(key), str):
            return False
    if not _connection_ok(issue.get("renamed"), need_nodes=False):
        return False
    for key in ("removed", "projectItems"):
        if not _connection_ok(issue.get(key)):
            return False
    if not all(node is None or isinstance(node, dict) for node in issue["removed"]["nodes"]):
        return False
    for node in issue["projectItems"]["nodes"]:
        if node is None:
            continue  # board_state answers "unknown" for it
        if not isinstance(node, dict) or not isinstance(node.get("isArchived"), bool):
            return False
        if not _field_values_ok(node):
            return False
    return True


def item_shape_ok(item) -> bool:
    """True when a board item answer has every part the write step reads."""
    return (
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("isArchived"), bool)
        and isinstance(item.get("project"), dict)
        and _field_values_ok(item)
    )


def opened_or_edited_since(issue: dict, since: datetime) -> bool:
    """The events that start the event job today: opened, edited (body or title)."""
    for key in ("createdAt", "lastEditedAt"):
        moment = parse_time(issue.get(key))
        if moment is not None and moment >= since:
            return True
    return ((issue.get("renamed") or {}).get("totalCount") or 0) > 0


def removed_from_board(issue: dict) -> bool:
    """True when the timeline shows a removal from Project 291, or cannot rule one out."""
    removed = issue.get("removed")
    if not _connection_ok(removed):
        return True  # malformed: fail closed (do not add)
    nodes = removed["nodes"]
    if removed["totalCount"] > len(nodes):
        return True
    for node in nodes:
        project = (node or {}).get("project")
        if project is None or project.get("id") == PROJECT_ID:
            return True
    return False


def board_state(issue: dict) -> tuple[str, dict | None]:
    """("none" | "found" | "archived" | "unknown", item)."""
    items = issue.get("projectItems")
    if not _connection_ok(items):
        return "unknown", None  # malformed: fail closed (no add, no write)
    nodes = items["nodes"]
    if items["totalCount"] > len(nodes):
        return "unknown", None
    for node in nodes:
        if not isinstance(node, dict):
            return "unknown", None
        project = node.get("project")
        if not isinstance(project, dict) or not isinstance(project.get("id"), str):
            return "unknown", None  # the item's project cannot be read
        if project["id"] == PROJECT_ID:
            if node.get("isArchived"):
                return "archived", node
            if ((node.get("fieldValues") or {}).get("pageInfo") or {}).get("hasNextPage"):
                return "unknown", None
            return "found", node
    return "none", None


def current_options(item: dict) -> dict[str, str]:
    """Single-select values on a board item: field id -> option id."""
    found = {}
    for value in (item.get("fieldValues") or {}).get("nodes") or []:
        if not value:
            continue
        field_id = (value.get("field") or {}).get("id")
        if field_id and value.get("optionId"):
            found[field_id] = value["optionId"]
    return found


def wanted_values(
    index: int, issue: dict, tax_fields: dict[str, list[str]], catalog: dict[str, dict]
) -> dict[str, str] | None:
    """
    The values the event job would pick, or None when it would skip the issue.

    Repository 1: exactly ingest_github.ingest_issue (allow-list = the taxonomy file,
    then the [WS/SS-CC] title prefix as a fallback for Workstream, Subsystem, Component).
    Repositories 2 and 3: their own ingest_github.py reads the form only, with no title
    fallback, and checks values against their own taxonomy file, which is not on this
    runner. Here the allow-list is the board's option list for that field.
    """
    if index == TAXONOMY_REPOSITORY:
        allowed = tax_fields
    else:
        allowed = {name: sorted(field["options"]) for name, field in catalog.items()}
    found = form_fields(issue.get("body") or "")
    values = {
        name: picked(found.get(name), allowed[name]) for name in TAXONOMY_FIELDS if name in allowed
    }
    workstream = values.get("Workstream")
    subsystem = values.get("Subsystem")
    component = values.get("Component")
    if not workstream or not subsystem or not component:
        if index != TAXONOMY_REPOSITORY:
            return None
        workstream, subsystem, component = wsc_from_title(issue.get("title") or "", tax_fields)
        if not workstream:
            return None
        values["Workstream"] = workstream
        values["Subsystem"] = subsystem
        values["Component"] = component
    return {name: value for name, value in values.items() if value}


def plan_issue(
    index: int,
    issue: dict,
    since: datetime,
    tax_fields: dict[str, list[str]],
    catalog: dict[str, dict],
) -> tuple[str, list[dict]]:
    """(outcome, actions). Outcome is "to-do", "up-to-date" or a skip reason."""
    if not opened_or_edited_since(issue, since):
        return "not-opened-or-edited", []
    values = wanted_values(index, issue, tax_fields, catalog)
    if values is None:
        return "no-taxonomy", []
    state, item = board_state(issue)
    if state == "unknown":
        return "board-state-unknown", []
    if state == "archived":
        return "archived", []
    actions: list[dict] = []
    base = {"repository": index, "number": issue.get("number"), "content": issue.get("id")}
    current: dict[str, str] = {}
    if state == "none":
        if removed_from_board(issue):
            return "removed-from-board", []
        actions.append(dict(base, op="add"))
    else:
        current = current_options(item)
        base["item"] = item["id"]
    for name, value in values.items():
        field = catalog.get(name)
        if not field or value not in field["options"]:
            continue  # "skip unknown" in ingest_github.py
        if current.get(field["id"]):
            continue  # "leave": the field has a value
        actions.append(
            dict(
                base,
                op="set",
                field=name,
                field_id=field["id"],
                option_id=field["options"][value],
                value=value,
            )
        )
    if not actions:
        return "up-to-date", []
    return "to-do", actions


def order_actions(planned: list[tuple[dict, list[dict], int]]) -> list[dict]:
    """
    planned: (issue, actions, group); group 0 = the normal window, 1 = the catch-up backlog.
    First the normal window (new needs), then the backlog. Inside each group: oldest issue
    first by creation time (it never changes), then repository and number, so the backlog
    drains in a fixed order. An add always comes before the fields of the same issue.
    Issues with nothing to do are not in `planned`, so they take no place and no write.
    """
    ordered = sorted(
        planned,
        key=lambda entry: (
            entry[2],
            parse_time(entry[0].get("createdAt")) or datetime.min.replace(tzinfo=timezone.utc),
            entry[1][0]["repository"],
            entry[1][0]["number"] or 0,
        ),
    )
    return [action for _issue, actions, _group in ordered for action in actions]


ERROR_TYPE = re.compile(r"^[A-Z][A-Z_]{0,39}$")


def error_summary(errors: list) -> str:
    """Count and type names only: GitHub's messages can name items or repositories."""
    types = set()
    for err in errors:
        value = err.get("type") if isinstance(err, dict) else None
        types.add(value if isinstance(value, str) and ERROR_TYPE.match(value) else "OTHER")
    return f"{len(errors)} error(s), types={','.join(sorted(types))}"


def is_rate_limited(errors: list) -> bool:
    return any(isinstance(err, dict) and err.get("type") == "RATE_LIMITED" for err in errors)


def detail_allowed(index: int, private: bool) -> bool:
    """Per-item lines only ever for repository 1, and only while it is public."""
    return index == TAXONOMY_REPOSITORY and not private


def action_line(action: dict, mode: str) -> str:
    verb = "WRITE" if mode == "write" else "WOULD-WRITE"
    head = f"{verb} repository={action['repository']} issue={action['number']}"
    if action["op"] == "add":
        return f"{head} add"
    return f'{head} field="{action["field"]}" value={action["value"]}'


# ---------------------------------------------------------------------------
# GitHub client.
# ---------------------------------------------------------------------------


class GitHubClient:
    def __init__(self, token: str, sleep=None, urlopen=None):
        self._token = token
        self._sleep = sleep or time.sleep
        self._urlopen = urlopen or urllib.request.urlopen

    def post(self, query: str, variables: dict, retry_server_errors: bool = True) -> dict:
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        return self._send(GRAPHQL_URL, "POST", body, retry_server_errors)

    def _send(self, url: str, method: str, body: bytes | None, retry: bool) -> dict:
        waits = list(SERVER_RETRY_WAITS) if retry else []
        while True:
            request = urllib.request.Request(url, data=body, method=method)
            request.add_header("Authorization", f"bearer {self._token}")
            request.add_header("Accept", "application/json")
            request.add_header("User-Agent", USER_AGENT)
            if body is not None:
                request.add_header("Content-Type", "application/json")
            try:
                with self._urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                    data = json.loads(response.read().decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("answer is not a JSON object")
                return data
            except urllib.error.HTTPError as err:
                # Only the status code and fixed text are printed. GitHub's message is read
                # only to see a rate limit; it is never printed (it could repeat a request).
                status = int(err.code)
                headers = err.headers or {}
                limited = _says_rate_limit(err)
                if headers.get("Retry-After") or status == 429 or limited:
                    raise SweepStop(
                        EXIT_RATE_LIMIT,
                        f"rate limit (HTTP {status}). Stopped; the next scheduled run continues.",
                    )
                if status in (401, 403):
                    raise SweepStop(EXIT_SETUP, f"auth error (HTTP {status})")
                if status == 404:
                    raise SweepStop(EXIT_UNREADABLE, "HTTP 404: not found or no access")
                if status >= 500 and waits:
                    self._sleep(waits.pop(0))
                    continue
                raise SweepStop(EXIT_SERVER, f"HTTP {status}")
            except (OSError, http.client.HTTPException, ValueError) as err:
                # OSError includes URLError, ConnectionError, TimeoutError and ssl.SSLError.
                if waits:
                    self._sleep(waits.pop(0))
                    continue
                raise SweepStop(EXIT_SERVER, f"network or answer error: {type(err).__name__}")


def _says_rate_limit(err: urllib.error.HTTPError) -> bool:
    """True when GitHub's message mentions a rate limit. The message is never printed."""
    try:
        data = json.loads(err.read().decode("utf-8"))
        return "rate limit" in str(data.get("message", "")).lower()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Queries.
# ---------------------------------------------------------------------------

CATALOG_QUERY = """
query($project: ID!) {
  node(id: $project) {
    ... on ProjectV2 {
      number
      fields(first: 100) {
        pageInfo { hasNextPage }
        nodes { ... on ProjectV2SingleSelectField { id name dataType options { id name } } }
      }
    }
  }
  rateLimit { remaining resetAt }
}
"""

ISSUES_QUERY = """
query($repo: ID!, $since: DateTime!, $cursor: String, $first: Int!) {
  node(id: $repo) {
    ... on Repository {
      databaseId
      isPrivate
      issues(first: $first, after: $cursor, filterBy: {since: $since},
             orderBy: {field: UPDATED_AT, direction: DESC}) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          number
          title
          body
          createdAt
          lastEditedAt
          renamed: timelineItems(itemTypes: [RENAMED_TITLE_EVENT], since: $since, first: 1) {
            totalCount
          }
          removed: timelineItems(itemTypes: [REMOVED_FROM_PROJECT_V2_EVENT], first: 20) {
            totalCount
            nodes { ... on RemovedFromProjectV2Event { project { id } } }
          }
          projectItems(first: 10, includeArchived: true) {
            totalCount
            nodes {
              id
              isArchived
              project { id }
              fieldValues(first: 50) {
                pageInfo { hasNextPage }
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    optionId
                    field { ... on ProjectV2SingleSelectField { id } }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
  rateLimit { remaining resetAt }
}
"""

BACKLOG_QUERY = """
query($repo: ID!, $since: DateTime!, $cursor: String, $first: Int!) {
  node(id: $repo) {
    ... on Repository {
      databaseId
      isPrivate
      issues(first: $first, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          number
          title
          body
          createdAt
          lastEditedAt
          renamed: timelineItems(itemTypes: [RENAMED_TITLE_EVENT], since: $since, first: 1) {
            totalCount
          }
          removed: timelineItems(itemTypes: [REMOVED_FROM_PROJECT_V2_EVENT], first: 20) {
            totalCount
            nodes { ... on RemovedFromProjectV2Event { project { id } } }
          }
          projectItems(first: 10, includeArchived: true) {
            totalCount
            nodes {
              id
              isArchived
              project { id }
              fieldValues(first: 50) {
                pageInfo { hasNextPage }
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    optionId
                    field { ... on ProjectV2SingleSelectField { id } }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
  rateLimit { remaining resetAt }
}
"""

ITEM_QUERY = """
query($item: ID!) {
  node(id: $item) {
    ... on ProjectV2Item {
      id
      isArchived
      project { id }
      fieldValues(first: 50) {
        pageInfo { hasNextPage }
        nodes {
          ... on ProjectV2ItemFieldSingleSelectValue {
            optionId
            field { ... on ProjectV2SingleSelectField { id } }
          }
        }
      }
    }
  }
}
"""

ADD_MUTATION = """
mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) {
    item { id createdAt isArchived project { id } }
  }
}
"""

SET_MUTATION = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {projectId: $project, itemId: $item, fieldId: $field,
                                        value: {singleSelectOptionId: $option}}) {
    projectV2Item { id }
  }
}
"""


# ---------------------------------------------------------------------------
# The run.
# ---------------------------------------------------------------------------


def check_rate(data: dict) -> None:
    rate = (data.get("data") or {}).get("rateLimit")
    remaining = _count(rate.get("remaining")) if isinstance(rate, dict) else None
    if remaining is None:
        raise SweepStop(EXIT_GRAPHQL, "an answer lacks the expected structure; no write was made")
    if remaining < MIN_RATE_REMAINING:
        raise SweepStop(
            EXIT_RATE_LIMIT,
            f"GraphQL budget low (remaining={remaining}). Stopped; the next scheduled run continues.",
        )


def stop_on_errors(data: dict, what: str) -> None:
    errors = data.get("errors")
    if errors:
        if is_rate_limited(errors):
            raise SweepStop(
                EXIT_RATE_LIMIT, "GraphQL RATE_LIMITED. Stopped; the next run continues."
            )
        raise SweepStop(EXIT_GRAPHQL, f"GraphQL error {what}: {error_summary(errors)}")


def read_catalog(client: GitHubClient) -> dict[str, dict]:
    data = client.post(CATALOG_QUERY, {"project": PROJECT_ID})
    stop_on_errors(data, "reading the board fields")
    node = (data.get("data") or {}).get("node")
    if not node:
        raise SweepStop(
            EXIT_UNREADABLE, "the board cannot be read with this token; no write was made"
        )
    if node.get("number") != PROJECT_NUMBER:
        raise SweepStop(
            EXIT_BOARD, "the board id does not belong to Project 291; no write was made"
        )
    fields = node.get("fields")
    if (
        not isinstance(fields, dict)
        or not isinstance(fields.get("pageInfo"), dict)
        or not isinstance(fields.get("nodes"), list)
    ):
        raise SweepStop(
            EXIT_BOARD, "the board answer lacks the expected structure; no write was made"
        )
    if fields["pageInfo"].get("hasNextPage"):
        raise SweepStop(
            EXIT_BOARD, "the board field list is longer than one page; no write was made"
        )
    catalog = {}
    for field in fields["nodes"]:
        if not field or field.get("dataType") != "SINGLE_SELECT" or not field.get("name"):
            continue
        if field["name"] in TAXONOMY_FIELDS:
            options = field.get("options")
            if not isinstance(field.get("id"), str) or not isinstance(options, list):
                raise SweepStop(
                    EXIT_BOARD, "the board answer lacks the expected structure; no write was made"
                )
            if not all(
                isinstance(opt, dict)
                and isinstance(opt.get("id"), str)
                and isinstance(opt.get("name"), str)
                for opt in options
            ):
                raise SweepStop(
                    EXIT_BOARD, "the board answer lacks the expected structure; no write was made"
                )
            catalog[field["name"]] = {
                "id": field["id"],
                "options": {opt["name"]: opt["id"] for opt in options},
            }
    check_rate(data)
    return catalog


def _issue_page(data: dict, repo_id: int, what: str) -> tuple[bool, list[dict], dict]:
    """(private flag, issue nodes, pageInfo) of one page, checked; stops on any gap."""
    stop_on_errors(data, f"reading {what}")
    node = (data.get("data") or {}).get("node")
    if not node:
        raise SweepStop(EXIT_UNREADABLE, f"{what} cannot be read with this token")
    if node.get("databaseId") != repo_id:
        raise SweepStop(EXIT_UNREADABLE, f"{what}: the answer does not match its id")
    connection = node.get("issues")
    if (
        not isinstance(node.get("isPrivate"), bool)
        or not isinstance(connection, dict)
        or not isinstance(connection.get("nodes"), list)
        or not isinstance(connection.get("pageInfo"), dict)
        or not isinstance(connection["pageInfo"].get("hasNextPage"), bool)
        or not all(issue_shape_ok(issue) for issue in connection["nodes"])
    ):
        # Fail closed: a part the plan needs is missing. The message holds no data.
        raise SweepStop(
            EXIT_GRAPHQL, f"{what}: an answer lacks the expected structure; no write was made"
        )
    check_rate(data)
    return node["isPrivate"], connection["nodes"], connection["pageInfo"]


def _next_cursor(page: dict, cursor: str | None, what: str) -> str:
    next_cursor = page.get("endCursor")
    if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
        raise SweepStop(EXIT_GRAPHQL, f"{what}: paging error; no write was made")
    return next_cursor


def read_repository(client: GitHubClient, index: int, since: datetime):
    """(private flag, issues) of the normal window. Each issue at most once. By node id."""
    repo_id, node_id = REPOSITORY_IDS[index - 1], REPOSITORY_NODE_IDS[index - 1]
    what = f"repository {index}"
    issues: list[dict] = []
    seen: set[str] = set()
    cursor = None
    for _ in range(MAX_PAGES):
        data = client.post(
            ISSUES_QUERY,
            {"repo": node_id, "since": iso(since), "cursor": cursor, "first": PAGE_SIZE},
        )
        private, nodes, page = _issue_page(data, repo_id, what)
        for issue in nodes:
            if issue["id"] in seen:
                continue  # the list moved while paging (an issue was updated): keep one copy
            seen.add(issue["id"])
            issues.append(issue)
        if not page["hasNextPage"]:
            return private, issues
        cursor = _next_cursor(page, cursor, what)
    raise SweepStop(
        EXIT_GRAPHQL, f"repository {index}: more than {MAX_PAGES} pages; no write was made"
    )


def read_backlog(client: GitHubClient, index: int, start: datetime) -> tuple[list[dict], bool]:
    """
    (issues created since `start`, True when cut at BACKLOG_MAX_PAGES). By node id.

    No state between runs: every run pages the repository's issues from the newest down,
    by creation time (it never changes, so paging is stable), and stops at the first page
    whose last issue was created before `start`. Only issues created since `start` are
    kept. One page per 50 issues created since `start`, plus one.
    """
    repo_id, node_id = REPOSITORY_IDS[index - 1], REPOSITORY_NODE_IDS[index - 1]
    what = f"repository {index} (catch-up list)"
    issues: list[dict] = []
    seen: set[str] = set()
    cursor = None
    for _ in range(BACKLOG_MAX_PAGES):
        data = client.post(
            BACKLOG_QUERY,
            {"repo": node_id, "since": iso(start), "cursor": cursor, "first": PAGE_SIZE},
        )
        _private, nodes, page = _issue_page(data, repo_id, what)
        reached_start = False
        for issue in nodes:
            created = parse_time(issue["createdAt"])
            if created is None or created < start:
                reached_start = True
                continue
            if issue["id"] not in seen:
                seen.add(issue["id"])
                issues.append(issue)
        if reached_start or not page["hasNextPage"]:
            return issues, False
        cursor = _next_cursor(page, cursor, what)
    return issues, True


def read_item(client: GitHubClient, item_id: str) -> dict:
    data = client.post(ITEM_QUERY, {"item": item_id})
    stop_on_errors(data, "reading a board item")
    node = (data.get("data") or {}).get("node")
    if not node:
        raise SweepStop(EXIT_GRAPHQL, "a board item cannot be read")
    if not item_shape_ok(node):
        raise SweepStop(EXIT_GRAPHQL, "a board item answer lacks the expected structure; stopped")
    return node


def write(client: GitHubClient, query: str, variables: dict) -> tuple[dict | None, str | None]:
    """(data, None) on success; (None, error types) for a write error that is skipped."""
    data = client.post(query, variables, retry_server_errors=False)
    errors = data.get("errors")
    if errors:
        if is_rate_limited(errors):
            raise SweepStop(EXIT_RATE_LIMIT, "GraphQL RATE_LIMITED on a write. Stopped.")
        return None, error_summary(errors)
    return data.get("data") or {}, None


def run(
    client: GitHubClient,
    mode: str,
    window: str,
    tax_fields: dict[str, list[str]],
    out=print,
    sleep=None,
    now=None,
    cap: int = DEFAULT_MAX_WRITES,
    details: bool = False,
    backfill: str | None = None,
) -> int:
    """
    1. Read the normal window, plan it, and write it (up to the cap).
    2. Only then, with SWEEP_BACKFILL_SINCE, read the catch-up list, plan it, and write
       it with what is left of the cap. A stop while reading the catch-up list cannot
       lose the writes of step 1. Each step reads everything it needs before its writes.
    """
    sleep = sleep or time.sleep
    clock = now or (lambda: datetime.now(timezone.utc))
    counts = {"repositories": 0, "issues": 0, "backlog": 0, "to-do": 0, "up-to-date": 0}
    reasons: dict[str, int] = {}
    tally = {"add": 0, "set": 0, "skipped": 0, "errors": 0, "writes": 0, "left": 0}
    planned: list[tuple[dict, list[dict], int]] = []
    private_of: dict[int, bool] = {}
    queue = {"actions": [], "next": 0}  # the phase being written; the rest is left over
    added_items: dict[str, str] = {}  # issue node id -> new item id
    failed_contents: set[str] = set()
    checked = {"first_set": False}
    backlog = "off"
    code = EXIT_OK
    catalog: dict[str, dict] = {}

    def plan(index: int, issue: dict, since: datetime, group: int, into: list) -> str:
        outcome, actions = plan_issue(index, issue, since, tax_fields, catalog)
        if outcome in ("to-do", "up-to-date"):
            counts[outcome] += 1
        else:
            reasons[outcome] = reasons.get(outcome, 0) + 1
        if actions:
            planned.append((issue, actions, group))
            into.append((issue, actions, group))
        return outcome

    def write_error(content: str, error: str) -> None:
        # Count it, print count and type names only, skip the rest of that issue, go on.
        tally["errors"] += 1
        failed_contents.add(content)
        out(f"Write error {tally['errors']} of at most {MAX_WRITE_ERRORS}: {error}")
        if tally["errors"] >= MAX_WRITE_ERRORS:
            raise SweepStop(EXIT_GRAPHQL, WRITE_ERRORS_STOP)

    def write_phase(ordered: list[dict]) -> None:
        # The cap counts write calls only (an add or a field write, also one that fails),
        # over both phases. A skipped action takes no write, so it never holds back others.
        tally["left"] += len(queue["actions"]) - queue["next"]
        queue["actions"], queue["next"] = ordered, 0
        for position, action in enumerate(ordered):
            queue["next"] = position
            if tally["writes"] >= cap:
                return
            queue["next"] = position + 1
            show = details and detail_allowed(
                action["repository"], private_of.get(action["repository"], True)
            )
            if mode != "write":
                tally["writes"] += 1
                if show:
                    out(action_line(action, mode))
                continue
            if action["content"] in failed_contents:
                tally["skipped"] += 1
                continue
            if action["op"] == "add":
                if tally["writes"]:
                    sleep(WRITE_INTERVAL_SECONDS)
                tally["writes"] += 1
                started = clock()
                data, error = write(
                    client, ADD_MUTATION, {"project": PROJECT_ID, "content": action["content"]}
                )
                if error:
                    write_error(action["content"], error)
                    continue  # the next issue goes on
                item = (data.get("addProjectV2ItemById") or {}).get("item") or {}
                created = parse_time(item.get("createdAt"))
                if (item.get("project") or {}).get("id") != PROJECT_ID or not item.get("id"):
                    raise SweepStop(
                        EXIT_GUARD,
                        "GUARD: the add answer is not an item of Project 291." + GUARD_ADVICE,
                    )
                if (
                    created is None
                    or created < started - NEW_ITEM_TOLERANCE
                    or item.get("isArchived")
                ):
                    raise SweepStop(
                        EXIT_GUARD,
                        "GUARD: the board already held an issue that this run read as missing, so the"
                        " reads of this run cannot be trusted." + GUARD_ADVICE,
                    )
                added_items[action["content"]] = item["id"]
                tally["add"] += 1
                if show:
                    out(action_line(action, mode))
                continue

            item_id = action.get("item") or added_items.get(action["content"])
            if not item_id:
                tally["skipped"] += 1
                continue
            if tally["writes"]:
                sleep(WRITE_INTERVAL_SECONDS)
            fresh = read_item(client, item_id)
            if (fresh.get("project") or {}).get("id") != PROJECT_ID:
                raise SweepStop(
                    EXIT_GUARD, "GUARD: a board item belongs to another project." + GUARD_ADVICE
                )
            if (
                fresh["isArchived"]
                or fresh["fieldValues"]["pageInfo"].get("hasNextPage")
                or current_options(fresh).get(action["field_id"])
            ):
                tally["skipped"] += 1  # archived, not fully readable, or the field got a value
                continue
            variables = {
                "project": PROJECT_ID,
                "item": item_id,
                "field": action["field_id"],
                "option": action["option_id"],
            }
            tally["writes"] += 1
            data, error = write(client, SET_MUTATION, variables)
            if error:
                write_error(action["content"], error)
                continue  # the next issue goes on
            answer = (data.get("updateProjectV2ItemFieldValue") or {}).get("projectV2Item")
            if not isinstance(answer, dict) or not answer.get("id"):
                raise SweepStop(
                    EXIT_GRAPHQL, "a write answer lacks the expected structure; stopped"
                )
            tally["set"] += 1
            if show:
                out(action_line(action, mode))
            if not checked["first_set"]:
                sleep(READ_BACK_WAIT_SECONDS)
                try:
                    back = read_item(client, item_id)
                except SweepStop:
                    raise SweepStop(
                        EXIT_GUARD,
                        "GUARD: the first field write of this run cannot be read back."
                        + GUARD_ADVICE,
                    )
                if current_options(back).get(action["field_id"]) != action["option_id"]:
                    raise SweepStop(
                        EXIT_GUARD,
                        "GUARD: the board does not show the first field value this run wrote."
                        + GUARD_ADVICE,
                    )
                checked["first_set"] = True
        queue["next"] = len(ordered)

    try:
        started_at = clock()
        since = started_at - WINDOWS[window]
        backfill_since, note = backfill_start(backfill, started_at)
        if note:
            out(note)
        catalog = read_catalog(client)
        # 1. The normal window: read all three repositories, then write.
        in_window: set[str] = set()
        normal: list[tuple[dict, list[dict], int]] = []
        for index in range(1, len(REPOSITORY_IDS) + 1):
            private, issues = read_repository(client, index, since)
            private_of[index] = private
            counts["repositories"] += 1
            for issue in issues:
                counts["issues"] += 1
                if plan(index, issue, since, 0, normal) != "not-opened-or-edited":
                    in_window.add(issue["id"])  # handled here, not again in the backlog
        write_phase(order_actions(normal))
        # 2. The catch-up backlog: issues created since SWEEP_BACKFILL_SINCE, oldest first.
        if backfill_since is not None and backfill_since < since:
            if tally["writes"] >= cap:
                backlog = "skipped"  # no write left in this run; the next minute-4 run reads it
            else:
                backlog = "on"
                cut = False
                later: list[tuple[dict, list[dict], int]] = []
                for index in range(1, len(REPOSITORY_IDS) + 1):
                    issues, truncated = read_backlog(client, index, backfill_since)
                    cut = cut or truncated
                    for issue in issues:
                        if issue["id"] in in_window:
                            continue  # already planned with the normal window
                        counts["backlog"] += 1
                        plan(index, issue, backfill_since, 1, later)
                if cut:
                    backlog = "cut"
                    out(
                        "::warning::the catch-up list of a repository is longer than "
                        f"{BACKLOG_MAX_PAGES * PAGE_SIZE} issues; this run used the newest "
                        f"{BACKLOG_MAX_PAGES * PAGE_SIZE}. Tell OSPO (open an OSPO ticket)."
                    )
                write_phase(order_actions(later))
    except SweepStop as stop:
        out(f"STOP: {stop.message}")
        code = stop.code
    left = tally["left"] + len(queue["actions"]) - queue["next"]
    out(
        f"Read: window={window} backlog={backlog} repositories={counts['repositories']} "
        f"issues={counts['issues']} backlog_issues={counts['backlog']} "
        f"to_do={counts['to-do']} up_to_date={counts['up-to-date']} "
        f"skipped={sum(reasons.values())}"
    )
    if details:
        text = " ".join(f"{key}={reasons[key]}" for key in sorted(reasons)) or "none"
        out(f"Skipped by reason (all repositories): {text}")
    wanted_adds = sum(1 for _i, actions, _g in planned for a in actions if a["op"] == "add")
    wanted_sets = sum(1 for _i, actions, _g in planned for a in actions if a["op"] == "set")
    out(
        f"SUMMARY mode={mode} exit={code} window={window} backlog={backlog} cap={cap} "
        f"repositories_read={counts['repositories']} issues_read={counts['issues']} "
        f"skipped={sum(reasons.values())} wanted_adds={wanted_adds} wanted_fields={wanted_sets} "
        f"items_added={tally['add']} fields_set={tally['set']} "
        f"skipped_at_write={tally['skipped']} errors={tally['errors']} left_for_next_run={left}"
    )
    return code


def main() -> int:
    def out(line: str) -> None:
        print(line, flush=True)

    try:
        mode = parse_choice(
            "SWEEP_MODE", os.environ.get("SWEEP_MODE"), ("dry-run", "write"), "dry-run"
        )
        window = parse_choice(
            "SWEEP_WINDOW", os.environ.get("SWEEP_WINDOW"), ("short", "long"), "short"
        )
        cap = parse_max_writes(os.environ.get("SWEEP_MAX_WRITES"))
    except SweepStop as stop:
        out(f"STOP: {stop.message}")
        return stop.code
    details = os.environ.get("SWEEP_LOG_DETAILS", "").strip() == "1"
    token = os.environ.get("PROJECT_BOARD_TOKEN", "")
    if not token:
        out("STOP: PROJECT_BOARD_TOKEN is empty")
        return EXIT_SETUP
    taxonomy_path = Path(__file__).resolve().parents[1] / "issue-taxonomy.yml"
    try:
        tax_fields = taxonomy_fields(taxonomy_path)
    except OSError:
        out("STOP: .github/issue-taxonomy.yml cannot be read")
        return EXIT_SETUP
    if not all(name in tax_fields for name in ("Workstream", "Subsystem", "Component")):
        out("STOP: .github/issue-taxonomy.yml has no Workstream, Subsystem or Component list")
        return EXIT_SETUP
    try:
        return run(
            GitHubClient(token),
            mode,
            window,
            tax_fields,
            out=out,
            cap=cap,
            details=details,
            backfill=os.environ.get("SWEEP_BACKFILL_SINCE"),
        )
    except Exception as err:  # noqa: BLE001 - never print a traceback (it can hold item data)
        out(f"STOP: internal error {type(err).__name__}")
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
