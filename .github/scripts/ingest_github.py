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

PROJECT_NUMBER = 291
PROJECT_OWNER = "tenstorrent"
PROJECT_URL = "https://github.com/orgs/tenstorrent/projects/291"
REPO = "tenstorrent/tt-oca-harness"

EMPTY_MARKERS = {"", "_no response_", "none", "n/a", "skip"}
EXTERNAL_CODE = re.compile(r"^(TRC|JPP|OBR)-([A-Za-z0-9]+)(?:\s*:\s*|\s+)(.*)$", re.DOTALL)
ISSUE_TYPE_PREFIX = re.compile(r"^\[(Bug|Task|Feature)\]:\s*")
TAXONOMY_PREFIX = re.compile(r"^\[[A-Z]+/")
HEADING = re.compile(r"^### ([^\n]+)\n+([^\n#]+)", re.MULTILINE)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

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
    """Read project.fields lists without PyYAML."""
    text = path.read_text(encoding="utf-8")
    fields: dict[str, list[str]] = {}
    current: str | None = None
    in_fields = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("  fields:"):
            in_fields = True
            continue
        if in_fields and line and not line.startswith(" "):
            break
        if in_fields and line.startswith("    ") and not line.startswith("      ") and line.endswith(":"):
            current = line.strip()[:-1]
            fields[current] = []
            continue
        if in_fields and current and line.startswith("      - "):
            fields[current].append(line[len("      - "):].strip())
    return {"project": {"fields": fields}}


def title_with_prefix(title: str, workstream: str, subsystem: str, component: str) -> str:
    raw = title.strip()
    type_prefix = ""
    type_match = ISSUE_TYPE_PREFIX.match(raw)
    if type_match:
        type_prefix = type_match.group(0)
        raw = raw[type_match.end():].lstrip()
    if TAXONOMY_PREFIX.match(raw):
        return title.strip()
    prefix = f"[{workstream}/{subsystem}]"
    if component != "General":
        prefix = f"[{workstream}/{subsystem}-{component}]"
    match = EXTERNAL_CODE.match(raw)
    if match:
        code = f"{match.group(1)}-{match.group(2)}"
        rest = (match.group(3) or "").strip()
        if TAXONOMY_PREFIX.match(rest):
            return title.strip()
        body = f"{code}: {prefix} {rest}".rstrip()
        return f"{type_prefix}{body}".strip()
    return f"{type_prefix}{prefix} {raw}".strip()


def section_text(body: str, heading: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(body or "")
    if not match:
        return ""
    text = HTML_COMMENT.sub("", match.group(1))
    return text.strip()


def pr_headings_ok(body: str) -> tuple[bool, str]:
    missing = []
    for heading in ("Summary", "Test plan"):
        text = section_text(body, heading)
        text = re.sub(r"^-\s*\[[ xX]\]\s*", "", text).strip()
        if not text:
            missing.append(heading)
    if missing:
        return False, "PR body is missing filled sections: " + ", ".join(missing)
    return True, ""


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
        ["project", "field-list", str(PROJECT_NUMBER), "--owner", PROJECT_OWNER, "--format", "json"],
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
        ["issue", "view", str(number), "--repo", repo_full, "--json", "title,body,url,labels"],
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
        print("no complete Workstream/Subsystem/Component on the form; skipping")
        return

    if project_token:
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
            "author,assignees",
        ]
    )
    if pr.get("assignees"):
        print("PR already assigned")
        return
    login = (pr.get("author") or {}).get("login")
    if not login:
        print("no PR author")
        return
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
    print("assigned", login)


def check_pr_template(number: int) -> None:
    repo_full = os.environ.get("GITHUB_REPOSITORY", REPO)
    pr = gh_json(["pr", "view", str(number), "--repo", repo_full, "--json", "body"])
    ok, message = pr_headings_ok(pr.get("body") or "")
    if not ok:
        raise SystemExit(message)
    print("PR template headings present")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", type=int)
    parser.add_argument("--pr-assign", type=int)
    parser.add_argument("--pr-template", type=int)
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=Path(".github/issue-taxonomy.yml"),
    )
    args = parser.parse_args()
    if args.issue:
        ingest_issue(args.issue, load_taxonomy(args.taxonomy))
    elif args.pr_assign:
        assign_pr_author(args.pr_assign)
    elif args.pr_template:
        check_pr_template(args.pr_template)
    else:
        raise SystemExit("pass --issue, --pr-assign, or --pr-template")


if __name__ == "__main__":
    main()
