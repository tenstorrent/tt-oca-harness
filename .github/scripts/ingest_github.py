#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Copy picked issue-form fields onto Project 291 and apply W/S/C labels."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

PROJECT_NUMBER = 291
PROJECT_OWNER = "tenstorrent"
PROJECT_URL = "https://github.com/orgs/tenstorrent/projects/291"
REPO = "tenstorrent/tt-oca-harness"

EMPTY_MARKERS = {"", "_no response_", "none", "n/a", "skip"}
EXTERNAL_CODE = re.compile(r"^(TRC|JPP|OBR)-([A-Za-z0-9]+)(?:\s*:\s*|\s+)(.*)$", re.DOTALL)
ISSUE_TYPE_PREFIX = re.compile(r"^\[(Bug|Task|Feature)\]:\s*")
TAXONOMY_PREFIX = re.compile(r"^\[[A-Z]+/")
HEADING = re.compile(r"^### ([^\n]+)\n+([^\n#]+)", re.MULTILINE)
BRACKET_PREFIX = re.compile(r"^\[([A-Z]+)/([A-Z]+)(?:-([A-Z]+))?\]")
REVIEW_REQUEST_MARKER = "<!-- github-auto-review-request -->"
REVIEWER_REASONS = {
    "suggested": "GitHub suggested you based on the files it touches",
    "linked_issue": "you are assigned to an issue this pull request closes",
    "path_history": "you recently committed to files this pull request touches",
    "reviewer_pool": "you are next in the repository reviewer pool",
}
PR_REVIEW_COMMENT = (
    "@{login} — you've been automatically requested to review this pull "
    "request because {reason}.\n\n"
    "If someone else is a better fit, please feel free to reassign.\n\n"
    f"{REVIEW_REQUEST_MARKER}"
)
CLOSING_ISSUE = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)")
PATH_HISTORY_FILE_CAP = 8
PATH_HISTORY_COMMITS_PER_FILE = 10

TAXONOMY_FIELDS = (
    "Workstream",
    "Subsystem",
    "Component",
    "Priority",
    "Target release",
)


def run(args: list[str], *, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout


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


def load_taxonomy(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        # PyYAML is not on the runner by default; parse the small allow-lists.
        return _taxonomy_from_simple_yaml(path)
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _taxonomy_from_simple_yaml(path: Path) -> dict:
    """Read project.fields lists and curation.reviewer_pool without PyYAML."""
    text = path.read_text(encoding="utf-8")
    fields: dict[str, list[str]] = {}
    current: str | None = None
    in_fields = False
    pool: list[str] = []
    in_pool = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("  reviewer_pool:"):
            in_pool = True
            in_fields = False
            continue
        if in_pool:
            if line.startswith("    - "):
                pool.append(line[len("    - ") :].strip())
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
    return {"project": {"fields": fields}, "curation": {"reviewer_pool": pool}}


def title_with_prefix(title: str, workstream: str, subsystem: str, component: str) -> str:
    raw = title.strip()
    type_match = ISSUE_TYPE_PREFIX.match(raw)
    if type_match:
        raw = raw[type_match.end() :].lstrip()
    if TAXONOMY_PREFIX.match(raw):
        return raw
    prefix = f"[{workstream}/{subsystem}]"
    if component != "General":
        prefix = f"[{workstream}/{subsystem}-{component}]"
    match = EXTERNAL_CODE.match(raw)
    if match:
        code = f"{match.group(1)}-{match.group(2)}"
        rest = (match.group(3) or "").strip()
        if TAXONOMY_PREFIX.match(rest):
            return f"{code}: {rest}".strip()
        return f"{code}: {prefix} {rest}".strip()
    return f"{prefix} {raw}".strip()


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


def gh_json(args: list[str], token: str | None = None) -> object:
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
        env["GITHUB_TOKEN"] = token
    return json.loads(run(["gh", *args], env=env) or "null")


def field_catalog(token: str) -> tuple[str, dict[str, dict]]:
    project = gh_json(
        ["project", "view", str(PROJECT_NUMBER), "--owner", PROJECT_OWNER, "--format", "json"],
        token,
    )
    fields = gh_json(
        [
            "project",
            "field-list",
            str(PROJECT_NUMBER),
            "--owner",
            PROJECT_OWNER,
            "--format",
            "json",
        ],
        token,
    )
    catalog: dict[str, dict] = {}
    for field in fields["fields"]:
        options = {opt["name"]: opt["id"] for opt in field.get("options") or []}
        catalog[field["name"]] = {"id": field["id"], "options": options}
    return project["id"], catalog


def issue_project_item(owner: str, repo: str, number: int, token: str) -> dict | None:
    query = """
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        issue(number: $number) {
          projectItems(first: 50) {
            nodes {
              id
              project { id number }
              fieldValues(first: 40) {
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    name
                    field { ... on ProjectV2SingleSelectField { name } }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    payload = gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={repo}",
            "-F",
            f"number={number}",
        ],
        token,
    )
    nodes = (
        payload.get("data", {})
        .get("repository", {})
        .get("issue", {})
        .get("projectItems", {})
        .get("nodes")
        or []
    )
    for node in nodes:
        if node.get("project", {}).get("number") == PROJECT_NUMBER:
            current = {}
            for value in node.get("fieldValues", {}).get("nodes") or []:
                field = value.get("field") or {}
                name = field.get("name")
                if name and value.get("name"):
                    current[name] = value["name"]
            return {"id": node["id"], "fields": current}
    return None


def ensure_item(url: str, owner: str, repo: str, number: int, token: str) -> dict:
    existing = issue_project_item(owner, repo, number, token)
    if existing:
        return existing
    gh_json(
        [
            "project",
            "item-add",
            str(PROJECT_NUMBER),
            "--owner",
            PROJECT_OWNER,
            "--url",
            url,
            "--format",
            "json",
        ],
        token,
    )
    existing = issue_project_item(owner, repo, number, token)
    if not existing:
        raise RuntimeError(f"failed to add {url} to project {PROJECT_NUMBER}")
    return existing


def set_select(project_id: str, item_id: str, field: dict, value: str, token: str) -> None:
    option_id = field["options"][value]
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    env["GITHUB_TOKEN"] = token
    run(
        [
            "gh",
            "project",
            "item-edit",
            "--project-id",
            project_id,
            "--id",
            item_id,
            "--field-id",
            field["id"],
            "--single-select-option-id",
            option_id,
        ],
        env=env,
    )


def ingest_issue(number: int, taxonomy: dict) -> None:
    repo_full = os.environ.get("GITHUB_REPOSITORY", REPO)
    owner, repo = repo_full.split("/", 1)
    issue_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    project_token = os.environ.get("GH_AW_WRITE_PROJECT_TOKEN") or issue_token
    if not issue_token:
        raise SystemExit("GITHUB_TOKEN is required")

    issue = gh_json(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            repo_full,
            "--json",
            "title,body,url,labels,author,assignees,milestone",
        ],
        issue_token,
    )
    fields = taxonomy["project"]["fields"]
    picked_fields = form_fields(issue.get("body") or "")
    values = {
        name: picked(picked_fields.get(name), fields[name])
        for name in TAXONOMY_FIELDS
        if name in fields
    }
    workstream = values.get("Workstream")
    subsystem = values.get("Subsystem")
    component = values.get("Component")
    if not workstream or not subsystem or not component:
        workstream, subsystem, component = wsc_from_title(issue["title"], fields)
        if not workstream:
            print("no complete Workstream/Subsystem/Component; skipping")
            return
        values["Workstream"] = workstream
        values["Subsystem"] = subsystem
        values["Component"] = component

    author_login = (issue.get("author") or {}).get("login", "")
    is_protected = author_login in taxonomy.get("protection", {}).get("authors", [])

    if project_token:
        try:
            project_id, catalog = field_catalog(project_token)
            item = ensure_item(issue["url"], owner, repo, number, project_token)
            for name, value in values.items():
                if not value:
                    continue
                if item["fields"].get(name):
                    print(f"leave {name}={item['fields'][name]}")
                    continue
                if name not in catalog or value not in catalog[name]["options"]:
                    print(f"skip unknown {name}={value}")
                    continue
                set_select(project_id, item["id"], catalog[name], value, project_token)
                print(f"set {name}={value}")
        except (subprocess.CalledProcessError, RuntimeError, json.JSONDecodeError) as exc:
            detail = (getattr(exc, "stderr", None) or str(exc)).strip()
            print(
                "project write skipped (org Project 291 needs GH_AW_WRITE_PROJECT_TOKEN):",
                detail,
                file=sys.stderr,
            )
    else:
        print("no project token; skipped Project field writes")

    labels = [workstream, subsystem]
    if component != "General":
        labels.append(component)
    existing = {label["name"] for label in issue.get("labels") or []}
    to_add = [name for name in labels if name not in existing]
    if to_add:
        cmd = ["gh", "issue", "edit", str(number), "--repo", repo_full]
        for name in to_add:
            cmd.extend(["--add-label", name])
        try:
            run(cmd)
            print("labels", ",".join(to_add))
        except subprocess.CalledProcessError as exc:
            print("label apply failed:", exc.stderr, file=sys.stderr)

    new_title = title_with_prefix(issue["title"], workstream, subsystem, component)
    if new_title != issue["title"]:
        run(
            [
                "gh",
                "issue",
                "edit",
                str(number),
                "--repo",
                repo_full,
                "--title",
                new_title,
            ]
        )
        print("title", new_title)

    if not is_protected and not assignee_logins(issue):
        _assign_issue_mechanical(number, repo_full, issue)

    target_release = values.get("Target release")
    tr_map = taxonomy.get("release", {}).get("target_release_to_milestone", {})
    if (
        target_release in tr_map
        and not (issue.get("milestone") or {}).get("number")
        and not is_protected
    ):
        milestone_title = tr_map[target_release]
        try:
            run(
                [
                    "gh",
                    "issue",
                    "edit",
                    str(number),
                    "--repo",
                    repo_full,
                    "--milestone",
                    milestone_title,
                ]
            )
            print("milestone", milestone_title)
        except subprocess.CalledProcessError as exc:
            print("milestone set failed:", exc.stderr, file=sys.stderr)


ASSIGN_MARKER = "<!-- github-auto-assign -->"
PR_ASSIGN_COMMENT = (
    "@{login} — you've been automatically assigned to this pull request "
    "because you opened it.\n\n"
    "If someone else is a better fit, please feel free to reassign.\n\n"
    f"{ASSIGN_MARKER}"
)
UNSUBSCRIBE = """
mutation($id:ID!){
  updateSubscription(input:{subscribableId:$id, state:UNSUBSCRIBED}){
    subscribable { viewerSubscription }
  }
}
"""


def pr_human_opener(pr: dict) -> str | None:
    author = pr.get("author") or {}
    login = author.get("login")
    if not login or author.get("is_bot") or login.endswith("[bot]"):
        return None
    return login


def assignee_logins(pr: dict) -> set[str]:
    return {person.get("login") for person in (pr.get("assignees") or []) if person.get("login")}


def _comments_contain(repo_full: str, number: int, marker: str) -> bool:
    try:
        text = run(
            [
                "gh",
                "api",
                "--paginate",
                f"repos/{repo_full}/issues/{number}/comments",
                "-q",
                ".[].body",
            ]
        )
    except subprocess.CalledProcessError:
        return False
    return marker in (text or "")


def has_assign_marker(repo_full: str, number: int) -> bool:
    return _comments_contain(repo_full, number, ASSIGN_MARKER)


def login_is_assignable(repo_full: str, login: str) -> bool:
    try:
        run(["gh", "api", f"repos/{repo_full}/assignees/{login}"])
    except subprocess.CalledProcessError:
        return False
    return True


def unsubscribe_best_effort(node_id: str | None) -> None:
    if not node_id:
        return
    try:
        run(["gh", "api", "graphql", "-f", f"query={UNSUBSCRIBE}", "-F", f"id={node_id}"])
    except subprocess.CalledProcessError as exc:
        print("unsubscribe skipped:", exc.stderr, file=sys.stderr)


def _parent_issue_assignee(repo_full: str, number: int) -> str | None:
    owner, repo = repo_full.split("/", 1)
    query = (
        "query($owner:String!,$name:String!,$number:Int!){"
        "repository(owner:$owner,name:$name){"
        "issue(number:$number){"
        "trackedInIssues(first:1){nodes{assignees(first:1){nodes{login}}}}}}}"
    )
    try:
        payload = gh_json(
            [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={repo}",
                "-F",
                f"number={number}",
            ]
        )
        nodes = (
            payload.get("data", {})
            .get("repository", {})
            .get("issue", {})
            .get("trackedInIssues", {})
            .get("nodes")
            or []
        )
        for parent in nodes:
            for assignee in parent.get("assignees", {}).get("nodes") or []:
                login = assignee.get("login")
                if login and not login.endswith("[bot]"):
                    return login
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        pass
    return None


def _assign_issue_mechanical(number: int, repo_full: str, issue: dict) -> None:
    """Mechanical first-match assignment for issues (A2)."""
    if _comments_contain(repo_full, number, ASSIGN_MARKER):
        return
    author_login = (issue.get("author") or {}).get("login", "")
    body = issue.get("body") or ""
    mentions = {
        m
        for m in re.findall(r"@([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)", body)
        if m != author_login and not m.endswith("[bot]")
    }
    login = reason = None
    if len(mentions) == 1:
        candidate = next(iter(mentions))
        if login_is_assignable(repo_full, candidate):
            login, reason = candidate, "you were mentioned in the issue body"
    if not login:
        parent = _parent_issue_assignee(repo_full, number)
        if parent and parent != author_login and login_is_assignable(repo_full, parent):
            login, reason = parent, "you are assigned to the parent issue"
    if not login:
        return
    try:
        run(["gh", "issue", "edit", str(number), "--repo", repo_full, "--add-assignee", login])
    except subprocess.CalledProcessError as exc:
        print("issue assign failed:", exc.stderr, file=sys.stderr)
        return
    check = gh_json(["issue", "view", str(number), "--repo", repo_full, "--json", "assignees"])
    if login not in assignee_logins(check):
        return
    comment = (
        f"@{login} — you've been automatically assigned to this issue "
        f"because {reason}.\n\n"
        "If someone else is a better fit, please feel free to reassign.\n\n"
        f"{ASSIGN_MARKER}"
    )
    run(["gh", "issue", "comment", str(number), "--repo", repo_full, "--body", comment])
    print("issue assigned", login)


def pick_reviewer(
    author_login: str,
    suggested: list[str],
    linked_assignees: list[str],
    path_authors: list[str],
    pool: list[str],
    usable=None,
) -> tuple[str | None, str | None]:
    """Return the first usable reviewer and the rule that selected them."""

    def ok(login: str) -> bool:
        if not login or login.endswith("[bot]") or login == author_login:
            return False
        return True if usable is None else usable(login)

    for login in suggested:
        if ok(login):
            return login, "suggested"
    for login in linked_assignees:
        if ok(login):
            return login, "linked_issue"
    for login in path_authors:
        if ok(login):
            return login, "path_history"
    for login in pool:
        if ok(login):
            return login, "reviewer_pool"
    return None, None


def reviewer_pool(taxonomy: dict) -> list[str]:
    raw = (taxonomy.get("curation") or {}).get("reviewer_pool") or []
    return [str(login) for login in raw if login]


def closing_issue_numbers(body: str) -> list[int]:
    seen: list[int] = []
    seen_set: set[int] = set()
    for raw in CLOSING_ISSUE.findall(body or ""):
        number = int(raw)
        if number not in seen_set:
            seen_set.add(number)
            seen.append(number)
    return seen


def _suggested_reviewer_logins(pr: dict) -> list[str]:
    logins: list[str] = []
    for suggestion in pr.get("suggestedReviewers") or []:
        if suggestion.get("isAuthor"):
            continue
        login = (suggestion.get("reviewer") or {}).get("login")
        if login:
            logins.append(login)
    return logins


def _add_unique_login(logins: list[str], seen: set[str], login: str | None) -> None:
    if login and login not in seen:
        seen.add(login)
        logins.append(login)


def _linked_issue_assignees(repo_full: str, pr: dict) -> list[str]:
    logins: list[str] = []
    seen: set[str] = set()
    for issue in (pr.get("closingIssuesReferences") or {}).get("nodes") or []:
        for assignee in (issue.get("assignees") or {}).get("nodes") or []:
            _add_unique_login(logins, seen, assignee.get("login"))
    for number in closing_issue_numbers(pr.get("body") or ""):
        try:
            issue = gh_json(
                ["issue", "view", str(number), "--repo", repo_full, "--json", "assignees"]
            )
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        for assignee in issue.get("assignees") or []:
            _add_unique_login(logins, seen, assignee.get("login"))
    return logins


def _path_history_authors(repo_full: str, number: int, base: str) -> list[str]:
    try:
        files = gh_json(["api", "--paginate", f"repos/{repo_full}/pulls/{number}/files"])
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []
    if not isinstance(files, list):
        return []
    paths = [
        entry.get("filename")
        for entry in files
        if isinstance(entry, dict) and entry.get("filename")
    ]
    logins: list[str] = []
    seen: set[str] = set()
    for path in paths[:PATH_HISTORY_FILE_CAP]:
        endpoint = (
            f"repos/{repo_full}/commits?path={quote(path, safe='')}&sha={quote(base, safe='')}"
            f"&per_page={PATH_HISTORY_COMMITS_PER_FILE}"
        )
        try:
            commits = gh_json(["api", endpoint])
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        if not isinstance(commits, list):
            continue
        for commit in commits:
            if not isinstance(commit, dict):
                continue
            _add_unique_login(logins, seen, (commit.get("author") or {}).get("login"))
    return logins


def request_pr_reviewer(number: int, taxonomy_path: Path | None = None) -> None:
    repo_full = os.environ.get("GITHUB_REPOSITORY", REPO)
    owner, repo = repo_full.split("/", 1)
    query = (
        "query($owner:String!,$name:String!,$number:Int!){"
        "repository(owner:$owner,name:$name){"
        "pullRequest(number:$number){"
        "isDraft author{login} body baseRefName "
        "reviewRequests(first:10){nodes{requestedReviewer{...on User{login}}}} "
        "reviews(first:10){nodes{author{login}}} "
        "suggestedReviewers{isAuthor reviewer{login}} "
        "closingIssuesReferences(first:10){nodes{assignees(first:10){nodes{login}}}}"
        "}}}"
    )
    pr_data = gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={repo}",
            "-F",
            f"number={number}",
        ]
    )
    pr = pr_data.get("data", {}).get("repository", {}).get("pullRequest") or {}
    if pr.get("isDraft"):
        print("skip reviewer: PR is draft")
        return
    existing = {
        (n.get("requestedReviewer") or {}).get("login")
        for n in (pr.get("reviewRequests", {}).get("nodes") or [])
    } | {(n.get("author") or {}).get("login") for n in (pr.get("reviews", {}).get("nodes") or [])}
    if existing - {None}:
        print("skip reviewer: reviewer already requested or reviewed")
        return
    if _comments_contain(repo_full, number, REVIEW_REQUEST_MARKER):
        print("skip reviewer: review-request comment already present")
        return
    author_login = (pr.get("author") or {}).get("login", "")
    taxonomy = load_taxonomy(taxonomy_path or github_dir() / "issue-taxonomy.yml")
    login, rule = pick_reviewer(
        author_login,
        _suggested_reviewer_logins(pr),
        _linked_issue_assignees(repo_full, pr),
        _path_history_authors(repo_full, number, pr.get("baseRefName") or "main"),
        reviewer_pool(taxonomy),
        usable=lambda candidate: login_is_assignable(repo_full, candidate),
    )
    if not login or not rule:
        print("no usable reviewer")
        return
    try:
        run(["gh", "pr", "edit", str(number), "--repo", repo_full, "--add-reviewer", login])
    except subprocess.CalledProcessError as exc:
        print("reviewer request failed:", exc.stderr, file=sys.stderr)
        return
    run(
        [
            "gh",
            "pr",
            "comment",
            str(number),
            "--repo",
            repo_full,
            "--body",
            PR_REVIEW_COMMENT.format(login=login, reason=REVIEWER_REASONS[rule]),
        ]
    )
    print("reviewer requested", login, f"({rule})")


def assign_pr_author(number: int) -> None:
    repo_full = os.environ.get("GITHUB_REPOSITORY", REPO)
    pr = gh_json(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo_full,
            "--json",
            "author,assignees,id",
        ]
    )
    if assignee_logins(pr):
        print("PR already assigned")
        return
    if has_assign_marker(repo_full, number):
        print("skip assign: assign comment already present")
        return
    login = pr_human_opener(pr)
    if not login:
        print("skip assign: opener is not a human")
        return
    if not login_is_assignable(repo_full, login):
        print(f"skip assign: {login} is not an assignable collaborator")
        return
    try:
        run(
            [
                "gh",
                "pr",
                "edit",
                str(number),
                "--repo",
                repo_full,
                "--add-assignee",
                login,
            ]
        )
    except subprocess.CalledProcessError as exc:
        print("assign failed:", exc.stderr, file=sys.stderr)
        return
    check = gh_json(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo_full,
            "--json",
            "assignees,id",
        ]
    )
    if login not in assignee_logins(check):
        print("skip comment: assign did not stick")
        return
    run(
        [
            "gh",
            "pr",
            "comment",
            str(number),
            "--repo",
            repo_full,
            "--body",
            PR_ASSIGN_COMMENT.format(login=login),
        ]
    )
    unsubscribe_best_effort(check.get("id") or pr.get("id"))
    print("assigned", login)


def github_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def issue_form_options(path: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    current: str | None = None
    in_options = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("label:"):
            current = stripped[len("label:") :].strip()
            in_options = False
            continue
        if current and stripped == "options:":
            in_options = True
            found[current] = []
            continue
        if in_options and stripped.startswith("- "):
            found[current].append(stripped[2:].strip())
            continue
        if in_options and stripped:
            in_options = False
            current = None
    return found


def assert_templates_match_taxonomy(taxonomy: dict) -> None:
    fields = taxonomy["project"]["fields"]
    forms = sorted((github_dir() / "ISSUE_TEMPLATE").glob("0*.yml"))
    if not forms:
        raise AssertionError("no issue forms under .github/ISSUE_TEMPLATE")
    for form in forms:
        options = issue_form_options(form)
        for name in TAXONOMY_FIELDS:
            assert name in options, f"{form.name} missing {name}"
            assert options[name] == fields[name], (
                f"{form.name} {name} {options[name]!r} != taxonomy {fields[name]!r}"
            )


def self_test() -> None:
    body = """### Workstream

DV

### Subsystem

SEP

### Component

General

### Priority

P2

### Target release

Future
"""
    fields = form_fields(body)
    assert fields["Workstream"] == "DV"
    assert fields["Subsystem"] == "SEP"
    assert fields["Component"] == "General"
    assert fields["Priority"] == "P2"
    assert fields["Target release"] == "Future"
    assert picked("n/a", ["P0", "P1", "P2"]) is None
    assert picked("P1", ["P0", "P1", "P2"]) == "P1"
    taxonomy = load_taxonomy(github_dir() / "issue-taxonomy.yml")
    assert "AOU" in taxonomy["project"]["fields"]["Subsystem"]
    assert_templates_match_taxonomy(taxonomy)
    fields = taxonomy["project"]["fields"]
    assert wsc_from_title("[DV/SEP-TRNG] Title", fields) == ("DV", "SEP", "TRNG")
    assert wsc_from_title("[ROM/SMC] Title", fields) == ("ROM", "SMC", "General")
    assert wsc_from_title("[INVALID/SEP] Title", fields) == (None, None, None)
    assert wsc_from_title("freeform title", fields) == (None, None, None)
    assert (
        title_with_prefix("[Task]: Use upstream versions of lc_*_pkg's", "RTL", "OCAH", "General")
        == "[RTL/OCAH] Use upstream versions of lc_*_pkg's"
    )
    assert (
        title_with_prefix("[Task]: [RTL/OCAH] already prefixed", "RTL", "OCAH", "General")
        == "[RTL/OCAH] already prefixed"
    )
    simple = _taxonomy_from_simple_yaml(github_dir() / "issue-taxonomy.yml")
    pool = reviewer_pool(simple)
    assert pool == ["aottavianoTT", "nbetikTT", "nboettcher-tenstorrent"]
    assert reviewer_pool(taxonomy) == pool
    assert closing_issue_numbers("Fixes #339 and closes #12. Resolve #339 again.") == [339, 12]
    assert pick_reviewer("alice", ["alice", "bob"], ["carol"], ["dave"], pool) == (
        "bob",
        "suggested",
    )
    assert pick_reviewer("alice", [], ["alice", "carol"], ["dave"], pool) == (
        "carol",
        "linked_issue",
    )
    assert pick_reviewer("alice", [], ["alice"], ["alice", "dave"], pool) == (
        "dave",
        "path_history",
    )
    assert pick_reviewer("alice", [], [], [], ["alice", "erin"]) == ("erin", "reviewer_pool")
    assert pick_reviewer("alice", ["alice"], ["alice"], ["alice"], ["alice"]) == (None, None)
    assert pick_reviewer(
        "alice",
        ["bob"],
        [],
        [],
        pool,
        usable=lambda login: login == "aottavianoTT",
    ) == ("aottavianoTT", "reviewer_pool")
    print("self-test ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", type=int)
    parser.add_argument("--pr-assign", type=int)
    parser.add_argument("--pr-review", type=int)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=Path(".github/issue-taxonomy.yml"),
    )
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.issue:
        ingest_issue(args.issue, load_taxonomy(args.taxonomy))
    elif args.pr_assign:
        assign_pr_author(args.pr_assign)
    elif args.pr_review:
        request_pr_reviewer(args.pr_review, args.taxonomy)
    else:
        raise SystemExit("pass --issue, --pr-assign, --pr-review, or --self-test")


if __name__ == "__main__":
    main()
