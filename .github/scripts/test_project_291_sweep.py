# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
Unit tests for project_291_sweep.py. No network.

Run from this folder: python3 -m unittest test_project_291_sweep
"""

import ast
import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import ingest_github as ingest
import project_291_sweep as sweep

FAKE_TOKEN = "ghs_FAKEtokenFORtestsONLY0123456789"
NOW = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "issue-taxonomy.yml"

# Distinctive strings: none of them may ever reach a default log line.
SECRET_TITLE = "ZZTITLE private words"
PRIVATE_NAME = "zz-private-repo-name"

FIELDS = {
    "Workstream": ("F_WS", ["RTL", "DV", "ROM", "NONFREE", "BOARDONLY"]),
    "Subsystem": ("F_SS", ["OCAH", "SEP", "SMC"]),
    "Component": ("F_CC", ["General", "TRNG", "KM"]),
    "Priority": ("F_PR", ["P0", "P1", "P2"]),
    "Target release": ("F_TR", ["v1.0.0", "Future"]),
}

TAX = {
    "Workstream": ["RTL", "DV", "ROM", "NONFREE"],
    "Subsystem": ["OCAH", "SEP", "SMC"],
    "Component": ["General", "TRNG", "KM"],
    "Priority": ["P0", "P1", "P2"],
    "Target release": ["v1.0.0", "Future"],
}


def option_id(field, value):
    return f"O_{field}_{value}"


def catalog():
    return {
        name: {"id": fid, "options": {v: option_id(name, v) for v in values}}
        for name, (fid, values) in FIELDS.items()
    }


def body(ws="DV", ss="SEP", cc="General", pr="P2", tr="Future"):
    parts = []
    for name, value in (
        ("Workstream", ws),
        ("Subsystem", ss),
        ("Component", cc),
        ("Priority", pr),
        ("Target release", tr),
    ):
        if value is not None:
            parts.append(f"### {name}\n\n{value}\n")
    return "\n".join(parts)


def item(item_id="ITEM1", values=None, archived=False, project=sweep.PROJECT_ID, more=False):
    nodes = []
    for name, value in (values or {}).items():
        nodes.append({"optionId": option_id(name, value), "field": {"id": FIELDS[name][0]}})
    nodes.append({})  # a field value of another type
    return {
        "id": item_id,
        "isArchived": archived,
        "project": {"id": project},
        "fieldValues": {"pageInfo": {"hasNextPage": more}, "nodes": nodes},
    }


def issue(
    number=7,
    node="ISSUE7",
    title=SECRET_TITLE,
    text=None,
    created="2026-11-18T11:30:00Z",
    edited=None,
    renamed=0,
    items=None,
    removed=None,
    removed_total=None,
    items_total=None,
):
    items = items or []
    removed = removed or []
    return {
        "id": node,
        "number": number,
        "title": title,
        "body": body() if text is None else text,
        "createdAt": created,
        "lastEditedAt": edited,
        "renamed": {"totalCount": renamed},
        "removed": {
            "totalCount": len(removed) if removed_total is None else removed_total,
            "nodes": [{"project": p} for p in removed],
        },
        "projectItems": {
            "totalCount": len(items) if items_total is None else items_total,
            "nodes": items,
        },
    }


SINCE = NOW - timedelta(hours=2)


class FakeClient:
    """Answers the sweep's queries. Records every call (query name, variables)."""

    def __init__(self, repos=None, private=(False, True, True), catalog_answer=None, backlog=None):
        self.repos = repos or {1: [], 2: [], 3: []}
        self.backlog = backlog or {}  # index -> all issues the catch-up listing pages through
        self.add_fail_for = set()  # issue node ids whose add always fails
        self.set_fail_for = set()  # board item ids whose field writes always fail
        self.private = private
        self.calls = []
        self.items = {}  # item id -> item (the board's truth for ITEM_QUERY)
        self.add_answer = None
        self.add_errors = None
        self.set_errors = None
        self.catalog_answer = catalog_answer
        self.rate = 4000
        self.errors_on = {}
        self.read_back_override = None
        self.item_reads = 0

    def post(self, query, variables, retry_server_errors=True):
        name = {
            sweep.CATALOG_QUERY: "catalog",
            sweep.ISSUES_QUERY: "issues",
            sweep.BACKLOG_QUERY: "backlog",
            sweep.ITEM_QUERY: "item",
            sweep.ADD_MUTATION: "add",
            sweep.SET_MUTATION: "set",
        }[query]
        self.calls.append((name, variables))
        if name in self.errors_on:
            return {"errors": self.errors_on[name]}
        rate = {"remaining": self.rate, "resetAt": "x"}
        if name == "catalog":
            if self.catalog_answer is not None:
                return self.catalog_answer
            nodes = [
                {
                    "id": fid,
                    "name": fname,
                    "dataType": "SINGLE_SELECT",
                    "options": [{"id": option_id(fname, v), "name": v} for v in values],
                }
                for fname, (fid, values) in FIELDS.items()
            ]
            nodes.append({})  # a field of another type
            nodes.append(
                {"id": "F_X", "name": "Status", "dataType": "SINGLE_SELECT", "options": []}
            )
            return {
                "data": {
                    "node": {
                        "number": 291,
                        "fields": {"pageInfo": {"hasNextPage": False}, "nodes": nodes},
                    },
                    "rateLimit": rate,
                }
            }
        if name == "issues":
            index = node_index(variables["repo"])
            return {
                "data": {
                    "node": {
                        "databaseId": sweep.REPOSITORY_IDS[index - 1],
                        "isPrivate": self.private[index - 1],
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": self.repos.get(index, []),
                        },
                    },
                    "rateLimit": rate,
                }
            }
        if name == "backlog":
            return backlog_answer(self.backlog, variables, rate, self.private)
        if name == "item":
            self.item_reads += 1
            if self.read_back_override is not None and self.item_reads >= 2:
                return {"data": {"node": self.read_back_override}}
            return {"data": {"node": self.items.get(variables["item"])}}
        if name == "add":
            if variables["content"] in self.add_fail_for:
                return {"errors": [{"type": "FORBIDDEN", "message": SECRET_TITLE}]}
            if self.add_errors:
                return {"errors": self.add_errors}
            answer = self.add_answer or {
                "id": f"NEW_{variables['content']}",
                "createdAt": "2026-11-18T12:00:00Z",
                "isArchived": False,
                "project": {"id": sweep.PROJECT_ID},
            }
            self.items.setdefault(answer["id"], item(answer["id"]))
            return {"data": {"addProjectV2ItemById": {"item": answer}}}
        if name == "set":
            if variables["item"] in self.set_fail_for:
                return {"errors": [{"type": "FORBIDDEN", "message": SECRET_TITLE}]}
            if self.set_errors:
                return {"errors": self.set_errors}
            target = self.items[variables["item"]]
            target["fieldValues"]["nodes"].append(
                {"optionId": variables["option"], "field": {"id": variables["field"]}}
            )
            return {
                "data": {
                    "updateProjectV2ItemFieldValue": {"projectV2Item": {"id": variables["item"]}}
                }
            }
        raise AssertionError(name)

    def names(self):
        return [c[0] for c in self.calls]


def node_index(node_id):
    return sweep.REPOSITORY_NODE_IDS.index(node_id) + 1


def backlog_answer(backlog, variables, rate, private=(False, True, True)):
    """Like Repository.issues(orderBy: CREATED_AT DESC): every issue, newest first, 50 a page."""
    index = node_index(variables["repo"])
    ordered = sorted(backlog.get(index, []), key=lambda i: i["createdAt"], reverse=True)
    number = int(variables["cursor"] or 0)
    chunk = ordered[number * sweep.PAGE_SIZE : (number + 1) * sweep.PAGE_SIZE]
    more = (number + 1) * sweep.PAGE_SIZE < len(ordered)
    return {
        "data": {
            "node": {
                "databaseId": sweep.REPOSITORY_IDS[index - 1],
                "isPrivate": private[index - 1],
                "issues": {
                    "pageInfo": {"hasNextPage": more, "endCursor": str(number + 1)},
                    "nodes": chunk,
                },
            },
            "rateLimit": rate,
        }
    }


def run(client, mode="write", cap=20, details=False, window="short", backfill=None):
    lines = []
    code = sweep.run(
        client,
        mode,
        window,
        TAX,
        out=lines.append,
        sleep=lambda s: None,
        now=lambda: NOW,
        cap=cap,
        details=details,
        backfill=backfill,
    )
    return code, lines


FULL = {
    "Workstream": "DV",
    "Subsystem": "SEP",
    "Component": "General",
    "Priority": "P2",
    "Target release": "Future",
}


def complete_issue(n, created):
    """On the board with every form value already set: nothing to do."""
    return issue(number=n, node=f"C{n}", created=created, items=[item(f"CI{n}", values=FULL)])


def paged(client, pages_of):
    """Make the fake client answer the issues query in pages. pages_of(index) -> list of pages."""
    original = client.post

    def post(query, variables, retry_server_errors=True):
        if query != sweep.ISSUES_QUERY:
            return original(query, variables, retry_server_errors)
        client.calls.append(("issues", variables))
        index = node_index(variables["repo"])
        pages = pages_of(index, variables)
        number = int(variables["cursor"] or 0)
        more = number + 1 < len(pages)
        return {
            "data": {
                "node": {
                    "databaseId": sweep.REPOSITORY_IDS[index - 1],
                    "isPrivate": index != 1,
                    "issues": {
                        "pageInfo": {"hasNextPage": more, "endCursor": str(number + 1)},
                        "nodes": pages[number] if pages else [],
                    },
                },
                "rateLimit": {"remaining": 4000, "resetAt": "x"},
            }
        }

    client.post = post
    return client


# ---------------------------------------------------------------------------


class ParityWithIngestGithub(unittest.TestCase):
    """The copied rules must give the same answers as ingest_github.py."""

    SAMPLES = [
        body(),
        body(ws="n/a"),
        body(ws=" RTL ", cc="_No response_"),
        "### Workstream\r\n\r\nDV\r\n\r\n### Subsystem\r\n\r\nSEP\r\n",
        "### Workstream\nDV\n### Subsystem\n\n# heading\n",
        "",
        "no headings at all",
    ]
    TITLES = [
        "[DV/SEP-TRNG] Title",
        "[ROM/SMC] Title",
        "[INVALID/SEP] Title",
        "freeform title",
        "  [RTL/OCAH-NOPE] x",
        "[Task]: [RTL/OCAH] y",
    ]

    def test_constants_identical(self):
        self.assertEqual(sweep.EMPTY_MARKERS, ingest.EMPTY_MARKERS)
        self.assertEqual(sweep.HEADING.pattern, ingest.HEADING.pattern)
        self.assertEqual(sweep.HEADING.flags, ingest.HEADING.flags)
        self.assertEqual(sweep.BRACKET_PREFIX.pattern, ingest.BRACKET_PREFIX.pattern)
        self.assertEqual(sweep.TAXONOMY_FIELDS, ingest.TAXONOMY_FIELDS)
        self.assertEqual(ingest.PROJECT_NUMBER, sweep.PROJECT_NUMBER)

    def test_form_fields_and_picked(self):
        for text in self.SAMPLES:
            self.assertEqual(sweep.form_fields(text), ingest.form_fields(text))
        for value in (None, "", " n/a ", "None", "SKIP", "P1", " P1 ", "p1", "X"):
            self.assertEqual(sweep.picked(value, ["P0", "P1"]), ingest.picked(value, ["P0", "P1"]))

    def test_title_prefix(self):
        fields = sweep.taxonomy_fields(TAXONOMY_PATH)
        for title in self.TITLES:
            self.assertEqual(
                sweep.wsc_from_title(title, fields), ingest.wsc_from_title(title, fields)
            )

    def test_taxonomy_file_read_the_same(self):
        expected = ingest._taxonomy_from_simple_yaml(TAXONOMY_PATH)["project"]["fields"]
        self.assertEqual(sweep.taxonomy_fields(TAXONOMY_PATH), expected)
        try:
            import yaml  # noqa: F401  (PyYAML: the event job uses it when the runner has it)
        except ImportError:
            return
        self.assertEqual(
            sweep.taxonomy_fields(TAXONOMY_PATH),
            ingest.load_taxonomy(TAXONOMY_PATH)["project"]["fields"],
        )

    def test_wanted_values_repo1_equals_ingest_rule(self):
        """Repository 1: same values as ingest_issue builds (before its board step)."""
        fields = sweep.taxonomy_fields(TAXONOMY_PATH)
        cat = {name: {"id": name, "options": {v: v for v in vals}} for name, vals in fields.items()}
        for text in self.SAMPLES:
            for title in self.TITLES:
                got = sweep.wanted_values(1, {"title": title, "body": text}, fields, cat)
                self.assertEqual(got, reference_values(title, text, fields))


def reference_values(title, text, fields):
    """ingest_github.ingest_issue's value selection, written out from its source."""
    found = ingest.form_fields(text)
    values = {
        name: ingest.picked(found.get(name), fields[name])
        for name in ingest.TAXONOMY_FIELDS
        if name in fields
    }
    ws, ss, cc = values.get("Workstream"), values.get("Subsystem"), values.get("Component")
    if not ws or not ss or not cc:
        ws, ss, cc = ingest.wsc_from_title(title, fields)
        if not ws:
            return None
        values["Workstream"], values["Subsystem"], values["Component"] = ws, ss, cc
    return {k: v for k, v in values.items() if v}


class PlanTests(unittest.TestCase):
    def plan(self, index, data):
        return sweep.plan_issue(index, data, SINCE, TAX, catalog())

    def test_new_issue_not_on_board_is_added_with_all_fields(self):
        outcome, actions = self.plan(1, issue())
        self.assertEqual(outcome, "to-do")
        self.assertEqual([a["op"] for a in actions], ["add", "set", "set", "set", "set", "set"])
        self.assertEqual(
            [a["field"] for a in actions[1:]],
            ["Workstream", "Subsystem", "Component", "Priority", "Target release"],
        )
        self.assertEqual(actions[1]["option_id"], option_id("Workstream", "DV"))

    def test_only_empty_fields_are_set(self):
        on_board = item(values={"Workstream": "RTL", "Priority": "P0"})
        outcome, actions = self.plan(1, issue(items=[on_board]))
        self.assertEqual(outcome, "to-do")
        self.assertEqual(
            [a["field"] for a in actions], ["Subsystem", "Component", "Target release"]
        )
        self.assertTrue(all(a["op"] == "set" and a["item"] == "ITEM1" for a in actions))

    def test_all_fields_set_is_up_to_date(self):
        full = item(
            values={
                "Workstream": "RTL",
                "Subsystem": "OCAH",
                "Component": "KM",
                "Priority": "P0",
                "Target release": "v1.0.0",
            }
        )
        self.assertEqual(self.plan(1, issue(items=[full])), ("up-to-date", []))

    def test_value_not_a_board_option_is_skipped(self):
        cat = catalog()
        del cat["Target release"]["options"]["Future"]
        outcome, actions = sweep.plan_issue(1, issue(), SINCE, TAX, cat)
        self.assertNotIn("Target release", [a.get("field") for a in actions])

    def test_field_missing_on_board_is_skipped(self):
        cat = catalog()
        del cat["Priority"]
        _outcome, actions = sweep.plan_issue(1, issue(), SINCE, TAX, cat)
        self.assertNotIn("Priority", [a.get("field") for a in actions])

    def test_repo1_title_fallback(self):
        data = issue(title="[ROM/SMC] fix", text=body(ws="n/a"))
        _outcome, actions = self.plan(1, data)
        sets = {a["field"]: a["value"] for a in actions if a["op"] == "set"}
        self.assertEqual(sets["Workstream"], "ROM")
        self.assertEqual(sets["Subsystem"], "SMC")
        self.assertEqual(sets["Component"], "General")
        self.assertEqual(sets["Priority"], "P2")

    def test_repo1_incomplete_and_no_prefix_is_skipped_without_add(self):
        data = issue(title="free text", text=body(cc=None))
        self.assertEqual(self.plan(1, data), ("no-taxonomy", []))

    def test_repo1_uses_taxonomy_not_board_options(self):
        # BOARDONLY is a board option but not in the taxonomy file: today's rule ignores it.
        data = issue(title="free text", text=body(ws="BOARDONLY"))
        self.assertEqual(self.plan(1, data), ("no-taxonomy", []))

    def test_private_repo_has_no_title_fallback(self):
        data = issue(title="[ROM/SMC] fix", text=body(ws="n/a"))
        self.assertEqual(self.plan(2, data), ("no-taxonomy", []))
        self.assertEqual(self.plan(3, data), ("no-taxonomy", []))

    def test_private_repo_checks_board_options(self):
        _outcome, actions = self.plan(2, issue(text=body(ws="BOARDONLY")))
        sets = {a["field"]: a["value"] for a in actions if a["op"] == "set"}
        self.assertEqual(sets["Workstream"], "BOARDONLY")
        self.assertEqual(self.plan(3, issue(text=body(ws="NOTANOPTION")))[0], "no-taxonomy")

    def test_only_updated_issue_is_not_in_scope(self):
        data = issue(created="2026-10-01T00:00:00Z", edited="2026-10-02T00:00:00Z")
        self.assertEqual(self.plan(1, data), ("not-opened-or-edited", []))

    def test_body_edit_and_title_rename_are_in_scope(self):
        edited = issue(created="2026-10-01T00:00:00Z", edited="2026-11-18T11:00:00Z")
        self.assertEqual(self.plan(1, edited)[0], "to-do")
        renamed = issue(created="2026-10-01T00:00:00Z", renamed=1)
        self.assertEqual(self.plan(1, renamed)[0], "to-do")

    def test_removed_from_board_is_never_added_back(self):
        self.assertEqual(
            self.plan(1, issue(removed=[{"id": sweep.PROJECT_ID}])), ("removed-from-board", [])
        )
        # A removal whose project cannot be read: do not add (safe side).
        self.assertEqual(self.plan(1, issue(removed=[None])), ("removed-from-board", []))
        # More removals than listed: do not add.
        self.assertEqual(self.plan(1, issue(removed_total=21)), ("removed-from-board", []))
        # A removal from another project does not block.
        self.assertEqual(self.plan(1, issue(removed=[{"id": "PVT_other"}]))[0], "to-do")

    def test_removed_then_back_on_board_still_gets_empty_fields(self):
        data = issue(removed=[{"id": sweep.PROJECT_ID}], items=[item(values={"Workstream": "DV"})])
        outcome, actions = self.plan(1, data)
        self.assertEqual(outcome, "to-do")
        self.assertNotIn("add", [a["op"] for a in actions])

    def test_archived_item_is_left_alone(self):
        self.assertEqual(self.plan(1, issue(items=[item(archived=True)])), ("archived", []))

    def test_unknown_board_state_is_skipped(self):
        self.assertEqual(self.plan(1, issue(items_total=11))[0], "board-state-unknown")
        self.assertEqual(self.plan(1, issue(items=[item(more=True)]))[0], "board-state-unknown")
        self.assertEqual(self.plan(1, issue(items=[None]))[0], "board-state-unknown")

    def test_item_on_another_project_only_means_not_on_this_board(self):
        data = issue(items=[item(project="PVT_other", values={"Workstream": "RTL"})])
        _outcome, actions = self.plan(1, data)
        self.assertEqual(actions[0]["op"], "add")
        self.assertIn("Workstream", [a.get("field") for a in actions])


class CapAndParsingTests(unittest.TestCase):
    def test_parse_max_writes(self):
        self.assertEqual(sweep.parse_max_writes(None), 20)
        self.assertEqual(sweep.parse_max_writes(" "), 20)
        self.assertEqual(sweep.parse_max_writes("1"), 1)
        self.assertEqual(sweep.parse_max_writes("300"), 300)
        for bad in ("0", "301", "-1", "1.5", "abc", "+5", "1e3"):
            with self.assertRaises(sweep.SweepStop) as ctx:
                sweep.parse_max_writes(bad)
            self.assertEqual(ctx.exception.code, sweep.EXIT_SETUP)

    def test_parse_choice(self):
        self.assertEqual(sweep.parse_choice("X", None, ("a", "b"), "a"), "a")
        self.assertEqual(sweep.parse_choice("X", " b ", ("a", "b"), "a"), "b")
        with self.assertRaises(sweep.SweepStop):
            sweep.parse_choice("X", "c", ("a", "b"), "a")

    def test_cap_counts_writes_and_keeps_adds_before_fields(self):
        older = issue(number=1, node="I1", created="2026-11-18T10:00:00Z")
        newer = issue(number=2, node="I2", created="2026-11-18T11:00:00Z")
        planned = [
            (newer, sweep.plan_issue(1, newer, SINCE, TAX, catalog())[1], 0),
            (older, sweep.plan_issue(1, older, SINCE, TAX, catalog())[1], 0),
        ]
        flat = sweep.order_actions(planned)
        todo, left = flat[:7], flat[7:]
        self.assertEqual(len(todo), 7)
        self.assertEqual(len(left), 5)
        self.assertEqual([a["content"] for a in todo[:6]], ["I1"] * 6)
        self.assertEqual((todo[6]["content"], todo[6]["op"]), ("I2", "add"))


class RunTests(unittest.TestCase):
    def test_write_run_adds_and_sets_with_read_back(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        code, lines = run(client)
        self.assertEqual(code, 0)
        names = client.names()
        self.assertEqual(names[:4], ["catalog", "issues", "issues", "issues"])
        self.assertEqual(
            [c[1]["repo"] for c in client.calls if c[0] == "issues"],
            list(sweep.REPOSITORY_NODE_IDS),
        )
        # add, then for each field: fresh read, set; the first set is read back once.
        writes = [n for n in names if n in ("add", "set", "item")]
        self.assertEqual(writes[:4], ["add", "item", "set", "item"])
        self.assertEqual(names.count("set"), 5)
        self.assertEqual(names.count("item"), 6)
        self.assertIn("items_added=1 fields_set=5", lines[-1])

    def test_dry_run_writes_nothing(self):
        client = FakeClient(repos={1: [issue()], 2: [issue(node="I9")], 3: []})
        code, lines = run(client, mode="dry-run")
        self.assertEqual(code, 0)
        self.assertNotIn("add", client.names())
        self.assertNotIn("set", client.names())
        self.assertNotIn("item", client.names())
        self.assertIn("wanted_adds=2 wanted_fields=10 items_added=0 fields_set=0", lines[-1])

    def test_cap_stops_writes_and_reports_left(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        code, lines = run(client, cap=2)
        self.assertEqual(code, 0)
        self.assertEqual(client.names().count("add"), 1)
        self.assertEqual(client.names().count("set"), 1)
        self.assertIn("left_for_next_run=4", lines[-1])

    def test_field_filled_meanwhile_is_skipped(self):
        on_board = item(values={})
        client = FakeClient(repos={1: [issue(items=[on_board])], 2: [], 3: []})
        client.items["ITEM1"] = item(values={"Workstream": "RTL", "Subsystem": "SEP"})
        code, lines = run(client)
        self.assertEqual(code, 0)
        sets = [c[1]["field"] for c in client.calls if c[0] == "set"]
        self.assertNotIn("F_WS", sets)
        self.assertNotIn("F_SS", sets)
        self.assertIn("skipped_at_write=2", lines[-1])

    def test_archived_meanwhile_is_skipped(self):
        client = FakeClient(repos={1: [issue(items=[item()])], 2: [], 3: []})
        client.items["ITEM1"] = item(archived=True)
        code, lines = run(client)
        self.assertEqual(code, 0)
        self.assertNotIn("set", client.names())

    def test_guard_add_returns_old_item(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        client.add_answer = {
            "id": "OLD",
            "createdAt": "2026-06-01T00:00:00Z",
            "isArchived": False,
            "project": {"id": sweep.PROJECT_ID},
        }
        code, lines = run(client)
        self.assertEqual(code, sweep.EXIT_GUARD)
        self.assertNotIn("set", client.names())
        self.assertTrue(any(line.startswith("STOP: GUARD:") for line in lines))
        self.assertIn("Disable", "\n".join(lines))

    def test_guard_add_answer_on_other_project(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        client.add_answer = {
            "id": "X",
            "createdAt": "2026-11-18T12:00:00Z",
            "isArchived": False,
            "project": {"id": "PVT_other"},
        }
        self.assertEqual(run(client)[0], sweep.EXIT_GUARD)

    def test_guard_item_on_other_project_before_write(self):
        client = FakeClient(repos={1: [issue(items=[item()])], 2: [], 3: []})
        client.items["ITEM1"] = item(project="PVT_other")
        code, _lines = run(client)
        self.assertEqual(code, sweep.EXIT_GUARD)
        self.assertNotIn("set", client.names())

    def test_guard_read_back_mismatch(self):
        client = FakeClient(repos={1: [issue(items=[item()])], 2: [], 3: []})
        client.items["ITEM1"] = item()
        client.read_back_override = item(values={})  # board does not show the value
        code, lines = run(client)
        self.assertEqual(code, sweep.EXIT_GUARD)
        self.assertEqual(client.names().count("set"), 1)
        self.assertIn("fields_set=1", lines[-1])

    def test_guard_read_back_fails(self):
        client = FakeClient(repos={1: [issue(items=[item()])], 2: [], 3: []})
        client.items["ITEM1"] = item()
        client.read_back_override = None
        original = client.post

        def post(query, variables, retry_server_errors=True):
            if query == sweep.ITEM_QUERY and client.names().count("set") == 1:
                client.calls.append(("item", variables))
                return {"errors": [{"type": "INTERNAL"}]}
            return original(query, variables, retry_server_errors)

        client.post = post
        code, lines = run(client)
        self.assertEqual(code, sweep.EXIT_GUARD)
        self.assertIn("cannot be read back", "\n".join(lines))

    def test_read_back_only_once_per_run(self):
        a = issue(number=1, node="I1", items=[item("A")])
        b = issue(number=2, node="I2", items=[item("B")])
        client = FakeClient(repos={1: [a, b], 2: [], 3: []})
        client.items["A"] = item("A")
        client.items["B"] = item("B")
        code, _lines = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(client.names().count("set"), 10)
        self.assertEqual(client.names().count("item"), 11)  # 10 fresh reads + 1 read back

    def test_write_errors_skip_then_stop(self):
        # One failed write per issue (the rest of that issue is skipped); 3 issues: stop.
        issues = [issue(number=n, node=f"I{n}", items=[item(f"T{n}")]) for n in range(4)]
        client = FakeClient(repos={1: issues, 2: [], 3: []})
        for n in range(4):
            client.items[f"T{n}"] = item(f"T{n}")
        client.set_errors = [{"type": "FORBIDDEN", "message": f"secret {SECRET_TITLE}"}]
        code, lines = run(client)
        self.assertEqual(code, sweep.EXIT_GRAPHQL)
        self.assertEqual(client.names().count("set"), 3)
        self.assertNotIn(SECRET_TITLE, "\n".join(lines))

    def test_failing_field_writes_skip_only_that_issue(self):
        first = issue(number=1, node="A", items=[item("IA")], created="2026-11-18T11:00:00Z")
        second = issue(number=2, node="B", created="2026-11-18T11:30:00Z")
        client = FakeClient(repos={1: [first, second], 2: [], 3: []})
        client.items["IA"] = item("IA")
        client.set_fail_for = {"IA"}
        code, lines = run(client)
        self.assertEqual(code, 0)
        self.assertEqual([c[1]["content"] for c in client.calls if c[0] == "add"], ["B"])
        self.assertIn("items_added=1 fields_set=5", lines[-1])
        self.assertIn("errors=1", lines[-1])
        self.assertIn("skipped_at_write=4", lines[-1])

    def test_add_error_skips_that_issues_fields(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        client.add_errors = [{"type": "FORBIDDEN"}]
        code, lines = run(client)
        self.assertEqual(code, 0)
        self.assertNotIn("set", client.names())
        self.assertIn("errors=1", lines[-1])
        self.assertIn("skipped_at_write=5", lines[-1])

    def test_rate_limited_write_stops(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        client.add_errors = [{"type": "RATE_LIMITED"}]
        self.assertEqual(run(client)[0], sweep.EXIT_RATE_LIMIT)

    def test_graphql_error_on_read_stops_before_any_write(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        client.errors_on["issues"] = [{"type": "FORBIDDEN", "message": PRIVATE_NAME}]
        code, lines = run(client)
        self.assertEqual(code, sweep.EXIT_GRAPHQL)
        self.assertNotIn("add", client.names())
        self.assertNotIn(PRIVATE_NAME, "\n".join(lines))
        self.assertIn("types=FORBIDDEN", "\n".join(lines))

    def test_low_budget_stops(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        client.rate = 100
        self.assertEqual(run(client)[0], sweep.EXIT_RATE_LIMIT)
        self.assertNotIn("add", client.names())

    def test_board_checks(self):
        wrong = {
            "data": {
                "node": {"number": 54, "fields": {"pageInfo": {"hasNextPage": False}, "nodes": []}},
                "rateLimit": {"remaining": 4000},
            }
        }
        self.assertEqual(run(FakeClient(catalog_answer=wrong))[0], sweep.EXIT_BOARD)
        more = {
            "data": {
                "node": {"number": 291, "fields": {"pageInfo": {"hasNextPage": True}, "nodes": []}},
                "rateLimit": {"remaining": 4000},
            }
        }
        self.assertEqual(run(FakeClient(catalog_answer=more))[0], sweep.EXIT_BOARD)
        gone = {"data": {"node": None, "rateLimit": {"remaining": 4000}}}
        self.assertEqual(run(FakeClient(catalog_answer=gone))[0], sweep.EXIT_UNREADABLE)

    def test_repository_mismatch_and_paging_errors(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        original = client.post

        def post(query, variables, retry_server_errors=True):
            data = original(query, variables, retry_server_errors)
            if query == sweep.ISSUES_QUERY:
                data["data"]["node"]["issues"]["pageInfo"] = {
                    "hasNextPage": True,
                    "endCursor": None,
                }
            return data

        client.post = post
        self.assertEqual(run(client)[0], sweep.EXIT_GRAPHQL)

        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        original2 = client.post

        def post2(query, variables, retry_server_errors=True):
            data = original2(query, variables, retry_server_errors)
            if query == sweep.ISSUES_QUERY:
                data["data"]["node"]["databaseId"] = 1
            return data

        client.post = post2
        self.assertEqual(run(client)[0], sweep.EXIT_UNREADABLE)
        self.assertNotIn("add", client.names())

    def test_unreadable_repository_named_by_number_only(self):
        client = FakeClient()
        original = client.post

        def post(query, variables, retry_server_errors=True):
            if query == sweep.ISSUES_QUERY:
                client.calls.append(("issues", variables))
                return {"data": {"node": None, "rateLimit": {"remaining": 4000}}}
            return original(query, variables, retry_server_errors)

        client.post = post
        code, lines = run(client)
        self.assertEqual(code, sweep.EXIT_UNREADABLE)
        self.assertIn("repository 1 cannot be read", "\n".join(lines))


class LogTests(unittest.TestCase):
    def sample_client(self):
        public = issue(number=4242, node="I1", title=SECRET_TITLE)
        private2 = issue(number=5353, node="I2", title=f"{SECRET_TITLE} two", text=body(ws="ROM"))
        private3 = issue(number=6464, node="I3", title=PRIVATE_NAME, text=body(ws="NONFREE"))
        return FakeClient(repos={1: [public], 2: [private2], 3: [private3]})

    def test_default_log_is_totals_only(self):
        for mode in ("write", "dry-run"):
            client = self.sample_client()
            code, lines = run(client, mode=mode)
            self.assertEqual(code, 0)
            text = "\n".join(lines)
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].startswith("Read: "))
            self.assertTrue(lines[1].startswith("SUMMARY "))
            for bad in (
                "4242",
                "5353",
                "6464",
                SECRET_TITLE,
                PRIVATE_NAME,
                "ROM",
                "NONFREE",
                "DV",
                "Workstream",
                "ITEM",
                "I1",
                "PVT_",
                str(sweep.REPOSITORY_IDS[1]),
                str(sweep.REPOSITORY_IDS[2]),
                FAKE_TOKEN,
                "removed",
                "archived",
            ):
                self.assertNotIn(bad, text, f"{bad!r} in default log ({mode})")

    def test_details_never_show_private_repositories(self):
        client = self.sample_client()
        code, lines = run(client, details=True)
        self.assertEqual(code, 0)
        text = "\n".join(lines)
        self.assertIn("issue=4242", text)
        for bad in ("5353", "6464", PRIVATE_NAME, "repository=2", "repository=3"):
            self.assertNotIn(bad, text)

    def test_details_off_when_repository_1_turns_private(self):
        client = self.sample_client()
        client.private = (True, True, True)
        _code, lines = run(client, details=True)
        self.assertNotIn("4242", "\n".join(lines))


class BackfillTests(unittest.TestCase):
    """SWEEP_BACKFILL_SINCE: the run also works on the issues created since then."""

    OLD = "2026-11-09T09:00:00Z"  # 9 days before NOW: outside the 2-hour and 7-day windows
    START = "2026-11-08T00:00:00Z"

    def since_sent(self, client):
        return {c[1]["since"] for c in client.calls if c[0] == "issues"}

    def searches(self, client):
        return [c[1] for c in client.calls if c[0] == "backlog"]

    def test_parse_unset_valid_old_bad_future(self):
        self.assertEqual(sweep.backfill_start(None, NOW), (None, None))
        self.assertEqual(sweep.backfill_start("  ", NOW), (None, None))
        start, note = sweep.backfill_start("2026-11-08T00:00:00Z", NOW)
        self.assertEqual(start, datetime(2026, 11, 8, tzinfo=timezone.utc))
        self.assertIsNone(note)
        self.assertEqual(
            sweep.backfill_start("2026-11-08", NOW)[0], datetime(2026, 11, 8, tzinfo=timezone.utc)
        )
        start, note = sweep.backfill_start("2026-09-01T00:00:00Z", NOW)
        self.assertIsNone(start)
        self.assertIn("older than 60 days", note)
        self.assertNotIn("2026-09", note)
        for bad in ("yesterday", "2026-13-01T00:00:00Z", "1700000000", "2026/11/08"):
            with self.assertRaises(sweep.SweepStop) as ctx:
                sweep.backfill_start(bad, NOW)
            self.assertEqual(ctx.exception.code, sweep.EXIT_SETUP)
            self.assertNotIn(bad, ctx.exception.message)
        with self.assertRaises(sweep.SweepStop) as ctx:
            sweep.backfill_start("2026-12-01T00:00:00Z", NOW)
        self.assertEqual(ctx.exception.code, sweep.EXIT_SETUP)

    def test_set_lists_the_backlog_by_creation_and_reaches_old_issues(self):
        client = FakeClient(backlog={1: [issue(created=self.OLD)]})
        code, lines = run(client, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertEqual(self.since_sent(client), {"2026-11-18T10:00:00Z"})  # normal window
        searches = self.searches(client)
        self.assertEqual(len(searches), 3)  # one page per repository
        self.assertEqual([v["repo"] for v in searches], list(sweep.REPOSITORY_NODE_IDS))
        self.assertTrue(all(v["since"] == self.START for v in searches))
        self.assertIn("backlog=on", lines[0])
        self.assertIn("backlog_issues=1", lines[0])
        self.assertIn("items_added=1 fields_set=5", lines[-1])

    def test_unset_has_no_backlog(self):
        client = FakeClient(backlog={1: [issue(created=self.OLD)]})
        for value in (None, ""):
            code, lines = run(client, backfill=value)
            self.assertEqual(code, 0)
            self.assertEqual(self.searches(client), [])
            self.assertIn("backlog=off", lines[-1])
        self.assertEqual(self.since_sent(client), {"2026-11-18T10:00:00Z"})
        self.assertNotIn("add", client.names())
        client = FakeClient()
        run(client, window="long")
        self.assertEqual(self.since_sent(client), {"2026-11-11T12:00:00Z"})

    def test_later_than_normal_window_needs_no_backlog(self):
        client = FakeClient()
        run(client, window="long", backfill="2026-11-17T00:00:00Z")
        self.assertEqual(self.since_sent(client), {"2026-11-11T12:00:00Z"})
        self.assertEqual(self.searches(client), [])

    def test_older_than_60_days_is_ignored_with_one_line(self):
        client = FakeClient(backlog={1: [issue(created=self.OLD)]})
        code, lines = run(client, backfill="2026-09-01T00:00:00Z")
        self.assertEqual(code, 0)
        self.assertEqual(self.searches(client), [])
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("Note: SWEEP_BACKFILL_SINCE is older than 60 days"))
        self.assertNotIn("2026", lines[0])
        self.assertNotIn("add", client.names())

    def test_bad_value_stops_before_any_read(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        code, lines = run(client, backfill="not-a-date")
        self.assertEqual(code, sweep.EXIT_SETUP)
        self.assertEqual(client.calls, [])
        self.assertNotIn("not-a-date", "\n".join(lines))

    def test_removed_rule_holds_in_the_backlog(self):
        gone = issue(created=self.OLD, removed=[{"id": sweep.PROJECT_ID}])
        client = FakeClient(backlog={1: [gone]})
        code, lines = run(client, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertNotIn("add", client.names())
        self.assertIn("wanted_adds=0", lines[-1])

    def test_issue_in_both_lists_is_planned_once(self):
        fresh = issue(number=9, node="I9")
        client = FakeClient(repos={1: [fresh], 2: [], 3: []}, backlog={1: [fresh]})
        code, lines = run(client, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertEqual(client.names().count("add"), 1)
        self.assertIn("backlog_issues=0", lines[0])

    def test_cleared_field_is_filled_again_while_set(self):
        # Documents the stated behaviour (pull request text): clearing a field on a
        # backlog issue does not stick while SWEEP_BACKFILL_SINCE is set.
        no_priority = dict(FULL)
        del no_priority["Priority"]
        on_board = issue(created=self.OLD, items=[item(values=no_priority)])
        client = FakeClient(backlog={1: [on_board]})
        client.items["ITEM1"] = item(values=no_priority)
        code, _lines = run(client, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertEqual([c[1]["field"] for c in client.calls if c[0] == "set"], ["F_PR"])
        client = FakeClient(repos={1: [on_board], 2: [], 3: []})
        run(client)
        self.assertNotIn("set", client.names())  # the normal window does not

    def test_backlog_drains_over_runs_under_the_cap(self):
        issues = [
            issue(number=n, node=f"I{n}", created=f"2026-11-09T0{n}:00:00Z") for n in range(4)
        ]
        client = FakeClient()
        totals = []
        for _ in range(4):
            client.backlog = {
                1: [
                    issue(
                        number=i["number"],
                        node=i["id"],
                        created=i["createdAt"],
                        items=[client.items[k] for k in client.items if k == f"NEW_{i['id']}"],
                    )
                    for i in issues
                ]
            }
            code, lines = run(client, cap=6, backfill=self.START)
            self.assertEqual(code, 0)
            totals.append(lines[-1].split("left_for_next_run=")[1])
        self.assertEqual(totals, ["18", "12", "6", "0"])
        self.assertEqual(client.names().count("add"), 4)
        self.assertEqual(client.names().count("set"), 20)


class ListingTests(unittest.TestCase):
    """The catch-up list: by node id, newest first by creation, until the start date."""

    START = "2026-11-08T00:00:00Z"

    def many(self, count, start=datetime(2026, 11, 8, tzinfo=timezone.utc), step=10):
        return [
            complete_issue(n, sweep.iso(start + timedelta(minutes=step * n))) for n in range(count)
        ]

    def calls(self, client, index):
        node = sweep.REPOSITORY_NODE_IDS[index - 1]
        return [c[1] for c in client.calls if c[0] == "backlog" and c[1]["repo"] == node]

    def test_stops_at_the_date_and_keeps_only_newer_issues(self):
        before = self.many(120, start=datetime(2026, 10, 1, tzinfo=timezone.utc))
        since = self.many(70)  # 2 pages of issues created since the date
        late = issue(number=900, node="LATE", created="2026-11-16T00:00:00Z")
        client = FakeClient(backlog={1: before + since + [late]})
        code, lines = run(client, cap=6, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls(client, 1)), 2)  # page 2 holds the first older issue
        self.assertIn("backlog_issues=71", lines[-2])
        self.assertEqual([c[1]["content"] for c in client.calls if c[0] == "add"], ["LATE"])

    def test_writes_go_oldest_first_after_the_newest_first_listing(self):
        a = issue(number=1, node="A", created="2026-11-09T00:00:00Z")
        b = issue(number=2, node="B", created="2026-11-12T00:00:00Z")
        c = issue(number=3, node="C", created="2026-11-10T00:00:00Z")
        client = FakeClient(backlog={1: [b, a, c]})
        code, _lines = run(client, cap=18, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertEqual([x[1]["content"] for x in client.calls if x[0] == "add"], ["A", "C", "B"])

    def test_issues_that_share_one_creation_second(self):
        second = "2026-11-10T00:00:00Z"
        same = [complete_issue(n, second) for n in range(120)]  # over 2 page borders
        todo = issue(number=999, node="TODO", created=second)
        client = FakeClient(backlog={2: same + [todo]})
        code, lines = run(client, cap=6, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls(client, 2)), 3)
        self.assertIn("backlog_issues=121", lines[-2])
        self.assertEqual([c[1]["content"] for c in client.calls if c[0] == "add"], ["TODO"])

    def test_empty_page_and_empty_repository(self):
        client = FakeClient()
        original = client.post
        sent = {"n": 0}

        def post(query, variables, retry_server_errors=True):
            if query == sweep.BACKLOG_QUERY and variables["repo"] == sweep.REPOSITORY_NODE_IDS[0]:
                client.calls.append(("backlog", variables))
                sent["n"] += 1
                nodes = [] if sent["n"] == 1 else [issue(created="2026-11-09T00:00:00Z")]
                more = sent["n"] == 1
                return {
                    "data": {
                        "node": {
                            "databaseId": sweep.REPOSITORY_IDS[0],
                            "isPrivate": False,
                            "issues": {
                                "pageInfo": {"hasNextPage": more, "endCursor": f"c{sent['n']}"},
                                "nodes": nodes,
                            },
                        },
                        "rateLimit": {"remaining": 4000},
                    }
                }
            return original(query, variables, retry_server_errors)

        client.post = post
        code, lines = run(client, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertEqual(sent["n"], 2)  # an empty page with more to come: read on
        self.assertEqual(len(self.calls(client, 3)), 1)  # empty repository: one page
        self.assertIn("items_added=1", lines[-1])

    def test_more_pages_than_the_limit_is_a_warning_and_exit_0(self):
        done = self.many(sweep.BACKLOG_MAX_PAGES * sweep.PAGE_SIZE + 100, step=1)
        fresh = issue(number=7, node="FRESH")
        client = FakeClient(repos={1: [fresh], 2: [], 3: []}, backlog={1: done})
        code, lines = run(client, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls(client, 1)), sweep.BACKLOG_MAX_PAGES)
        self.assertTrue(any(line.startswith("::warning::") for line in lines))
        self.assertIn("backlog=cut", lines[-1])
        self.assertEqual([c[1]["content"] for c in client.calls if c[0] == "add"], ["FRESH"])

    def test_malformed_backlog_answer_keeps_the_normal_writes(self):
        stray = issue(number=5, node="OLD", created="2026-11-09T00:00:00Z")
        fresh = issue(number=7, node="FRESH")
        client = FakeClient(repos={1: [fresh], 2: [], 3: []}, backlog={1: [stray]})
        original = client.post

        def post(query, variables, retry_server_errors=True):
            data = original(query, variables, retry_server_errors)
            if query == sweep.BACKLOG_QUERY:
                data["data"]["node"]["isPrivate"] = None
            return data

        client.post = post
        code, lines = run(client, backfill=self.START)
        self.assertEqual(code, sweep.EXIT_GRAPHQL)
        self.assertEqual([c[1]["content"] for c in client.calls if c[0] == "add"], ["FRESH"])
        self.assertIn("catch-up list", "\n".join(lines))

    def test_rate_limit_on_the_backlog_keeps_the_normal_writes(self):
        fresh = issue(number=7, node="FRESH")
        client = FakeClient(repos={1: [fresh], 2: [], 3: []}, backlog={1: [issue(node="OLD")]})
        client.errors_on["backlog"] = [{"type": "RATE_LIMITED"}]
        code, lines = run(client, backfill=self.START)
        self.assertEqual(code, sweep.EXIT_RATE_LIMIT)
        self.assertIn("items_added=1 fields_set=5", lines[-1])

    def test_commented_backlog_issue_is_not_lost_between_the_lists(self):
        # Created during the outage, only commented on lately: in the normal list, but not
        # opened or edited there. The backlog must still handle it.
        quiet = issue(number=3, node="QUIET", created="2026-11-10T00:00:00Z")
        client = FakeClient(repos={1: [quiet], 2: [], 3: []}, backlog={1: [quiet]})
        code, lines = run(client, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertEqual([c[1]["content"] for c in client.calls if c[0] == "add"], ["QUIET"])
        self.assertIn("backlog_issues=1", lines[-2])

    def test_cap_used_up_by_the_normal_window_skips_the_backlog_read(self):
        fresh = [issue(number=n, node=f"F{n}") for n in range(4)]
        client = FakeClient(repos={1: fresh, 2: [], 3: []}, backlog={1: [issue(node="OLD")]})
        code, lines = run(client, cap=6, backfill=self.START)
        self.assertEqual(code, 0)
        self.assertNotIn("backlog", client.names())
        self.assertIn("backlog=skipped", lines[-1])
        self.assertIn("left_for_next_run=18", lines[-1])


class NamePrivacyTests(unittest.TestCase):
    """No repository or owner name is ever selected, read, sent or printed."""

    SOURCE = Path(sweep.__file__).read_text(encoding="utf-8")

    @classmethod
    def code_words(cls):
        """Every identifier and string literal of the script, docstrings and comments left out."""
        tree = ast.parse(cls.SOURCE)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))
        words = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstrings:
                    words.append(node.value)
            elif isinstance(node, ast.Name):
                words.append(node.id)
            elif isinstance(node, ast.Attribute):
                words.append(node.attr)
            elif isinstance(node, ast.arg):
                words.append(node.arg)
            elif isinstance(node, ast.keyword) and node.arg:
                words.append(node.arg)
        return "\n".join(words)

    NAME_FIELDS = (
        "full_name",
        "nameWithOwner",
        "html_url",
        "resourcePath",
        "owner",
        "login",
        "repositories/",
        "search(",
    )
    QUERIES = ("CATALOG_QUERY", "ISSUES_QUERY", "BACKLOG_QUERY", "ITEM_QUERY")

    def test_source_selects_and_reads_no_name_field(self):
        code = self.code_words()
        self.assertIn("BACKLOG_QUERY", code)  # the scan sees the code
        for word in self.NAME_FIELDS:
            self.assertNotIn(word, code, word)
        for name in self.QUERIES + ("ADD_MUTATION", "SET_MUTATION"):
            text = getattr(sweep, name)
            for word in (" url", "\turl", "url ", "nameWithOwner", "owner", "repository {"):
                self.assertNotIn(word, text, (name, word))
        for name in ("ISSUES_QUERY", "BACKLOG_QUERY", "ITEM_QUERY"):
            words = getattr(sweep, name).replace("{", " ").replace("}", " ").split()
            self.assertNotIn("name", words, name)  # only the board catalog reads field names

    def test_no_request_carries_a_name(self):
        client = FakeClient(
            repos={1: [issue()], 2: [issue(node="I2")], 3: []},
            backlog={2: [issue(node="OLD", created="2026-11-09T00:00:00Z")]},
        )
        run(client, backfill="2026-11-08T00:00:00Z")
        sent = json.dumps([c[1] for c in client.calls])
        self.assertNotIn("/", sent.replace("\\/", ""))  # no owner/name pair in any variable
        self.assertNotIn(PRIVATE_NAME, sent)


class ErrorPathTests(unittest.TestCase):
    """GitHub's error text never reaches stdout, stderr, the outputs or the summary file."""

    REPO_NAME = "fake-owner/zz-private-repo-name"
    TITLE = "ZZTITLE private words"

    def answer_for(self, fake, request):
        payload = json.loads(request.data.decode("utf-8"))
        return json.dumps(fake.post(payload["query"], payload["variables"])).encode()

    TARGETS = {
        "board": lambda q, v: q == sweep.CATALOG_QUERY,
        "repository 2": lambda q, v: (
            q == sweep.ISSUES_QUERY and v["repo"] == sweep.REPOSITORY_NODE_IDS[1]
        ),
        "catch-up 2": lambda q, v: (
            q == sweep.BACKLOG_QUERY and v["repo"] == sweep.REPOSITORY_NODE_IDS[1]
        ),
        "write": lambda q, v: q == sweep.ADD_MUTATION,
    }

    def run_main(self, target, failure):
        fake = FakeClient(
            repos={1: [issue()], 2: [issue(node="I2", title=self.TITLE)], 3: []},
            backlog={
                2: [
                    issue(
                        node="OLD",
                        created=sweep.iso(datetime.now(timezone.utc) - timedelta(days=9)),
                    )
                ]
            },
        )
        sent = {"n": 0}

        def urlopen(request, timeout):
            sent["n"] += 1
            payload = json.loads(request.data.decode("utf-8"))
            if self.TARGETS[target](payload["query"], payload["variables"]):
                sent["hit"] = True
                if isinstance(failure, Exception):
                    raise failure
                return FakeResponse(failure)
            return FakeResponse(self.answer_for(fake, request))

        backfill = sweep.iso(datetime.now(timezone.utc) - timedelta(days=10))
        with tempfile.TemporaryDirectory() as folder:
            outputs = Path(folder) / "outputs"
            summary = Path(folder) / "summary"
            outputs.write_text("")
            summary.write_text("")
            env = {
                "PROJECT_BOARD_TOKEN": FAKE_TOKEN,
                "SWEEP_MODE": "write",
                "SWEEP_BACKFILL_SINCE": backfill,
                "GITHUB_OUTPUT": str(outputs),
                "GITHUB_STEP_SUMMARY": str(summary),
            }
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(sweep.urllib.request, "urlopen", urlopen),
                mock.patch.object(sweep.time, "sleep", lambda s: None),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                code = sweep.main()
            written = (
                stdout.getvalue() + stderr.getvalue() + outputs.read_text() + summary.read_text()
            )
        self.assertTrue(sent.get("hit"), target)  # the failing request was really sent
        return code, written, sent["n"]

    def leak_error(self, status):
        body = {
            "message": f"query repo:{self.REPO_NAME} failed for {self.TITLE}",
            "documentation_url": f"https://example.invalid/{self.REPO_NAME}",
            "errors": [{"message": self.TITLE, "resource": self.REPO_NAME}],
        }
        return urllib.error.HTTPError(
            "https://api.github.com/graphql",
            status,
            self.REPO_NAME,
            {},
            io.BytesIO(json.dumps(body).encode()),
        )

    def assert_clean(self, written):
        for bad in (
            self.REPO_NAME,
            "zz-private-repo-name",
            self.TITLE,
            "fake-owner",
            "query repo:",
        ):
            self.assertNotIn(bad, written)
        self.assertNotIn("api.github.com", written)
        self.assertNotIn(FAKE_TOKEN, written)

    def test_http_errors_print_the_status_only(self):
        for status in (400, 403, 422, 502):
            for target in self.TARGETS:
                code, written, _sent = self.run_main(target, self.leak_error(status))
                self.assertNotEqual(code, 0)
                self.assertIn(f"HTTP {status}", written)
                self.assert_clean(written)

    def test_graphql_errors_print_type_names_only(self):
        answer = json.dumps(
            {
                "errors": [
                    {"type": "FORBIDDEN", "message": f"{self.REPO_NAME} {self.TITLE}"},
                    {"type": f"{self.REPO_NAME}", "message": self.TITLE},
                    {"message": self.TITLE, "path": [self.REPO_NAME]},
                ]
            }
        ).encode()
        for target in self.TARGETS:
            code, written, _sent = self.run_main(target, answer)
            self.assertIn("types=FORBIDDEN,OTHER", written)
            self.assert_clean(written)


class ScheduleTests(unittest.TestCase):
    """The workflow gives SWEEP_BACKFILL_SINCE to the minute-4 run only."""

    WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "project-291-sweep.yml"

    def test_backlog_only_on_the_minute_4_schedule(self):
        text = self.WORKFLOW.read_text(encoding="utf-8")
        crons = [
            line.split("'")[1] for line in text.splitlines() if line.strip().startswith("- cron:")
        ]
        self.assertEqual(crons, ["4 * * * *", "19,34,49 * * * *", "57 2 * * *"])
        lines = [line.strip() for line in text.splitlines()]
        backfill = [line for line in lines if line.startswith("SWEEP_BACKFILL_SINCE:")]
        self.assertEqual(
            backfill,
            [
                "SWEEP_BACKFILL_SINCE: ${{ github.event.schedule == '4 * * * *'"
                " && '2026-11-08T00:00:00Z' || '' }}"
            ],
        )
        window = [line for line in lines if line.startswith("SWEEP_WINDOW:")]
        self.assertEqual(
            window,
            ["SWEEP_WINDOW: ${{ github.event.schedule == '57 2 * * *' && 'long' || 'short' }}"],
        )

    def test_what_each_schedule_gets(self):
        def env(schedule):  # the two expressions above, written out
            backfill = "2026-11-08T00:00:00Z" if schedule == "4 * * * *" else ""
            return ("long" if schedule == "57 2 * * *" else "short"), backfill

        self.assertEqual(env("4 * * * *"), ("short", "2026-11-08T00:00:00Z"))
        self.assertEqual(env("19,34,49 * * * *"), ("short", ""))
        self.assertEqual(env("57 2 * * *"), ("long", ""))
        for schedule in ("19,34,49 * * * *", "57 2 * * *"):
            client = FakeClient(backlog={1: [issue(created="2026-11-09T00:00:00Z")]})
            window, backfill = env(schedule)
            run(client, window=window, backfill=backfill)
            self.assertNotIn("backlog", client.names())


class OrderTests(unittest.TestCase):
    def test_backlog_oldest_created_first_across_repositories(self):
        a = issue(number=1, node="A", created="2026-11-10T00:00:00Z")
        b = issue(number=2, node="B", created="2026-11-09T00:00:00Z")
        c = issue(number=3, node="C", created="2026-11-11T00:00:00Z", text=body(ws="ROM"))
        client = FakeClient(backlog={1: [a], 2: [c], 3: [b]})
        code, lines = run(client, cap=12, backfill="2026-11-08T00:00:00Z")
        self.assertEqual(code, 0)
        adds = [x[1]["content"] for x in client.calls if x[0] == "add"]
        self.assertEqual(adds, ["B", "A"])
        self.assertIn("left_for_next_run=6", lines[-1])

    def test_fresh_issue_goes_before_a_backlog_larger_than_the_cap(self):
        backlog = [
            issue(number=n, node=f"B{n}", created=f"2026-11-09T0{n}:00:00Z") for n in range(5)
        ]
        fresh = issue(number=50, node="FRESH", created="2026-11-18T11:50:00Z")
        client = FakeClient(repos={1: [fresh], 2: [], 3: []}, backlog={1: backlog})
        code, lines = run(client, cap=8, backfill="2026-11-08T00:00:00Z")
        self.assertEqual(code, 0)
        adds = [c[1]["content"] for c in client.calls if c[0] == "add"]
        self.assertEqual(adds, ["FRESH", "B0"])
        self.assertIn("items_added=2 fields_set=6", lines[-1])
        self.assertIn("left_for_next_run=28", lines[-1])

    def test_failing_backlog_adds_do_not_block_the_fresh_issue(self):
        backlog = [
            issue(number=n, node=f"B{n}", created=f"2026-11-09T0{n}:00:00Z") for n in range(3)
        ]
        fresh = issue(number=50, node="FRESH", created="2026-11-18T11:50:00Z")
        client = FakeClient(repos={1: [fresh], 2: [], 3: []}, backlog={1: backlog})
        client.add_fail_for = {"B0", "B1", "B2"}
        code, lines = run(client, backfill="2026-11-08T00:00:00Z")
        self.assertEqual(code, sweep.EXIT_GRAPHQL)
        self.assertIn("items_added=1 fields_set=5", lines[-1])
        text = "\n".join(lines)
        self.assertEqual(text.count("Write error "), 3)
        self.assertNotIn(SECRET_TITLE, text)
        self.assertIn("The work before them is done", text)

    def test_one_failing_issue_does_not_block_the_next(self):
        bad = issue(number=1, node="BAD", created="2026-11-09T00:00:00Z")
        good = issue(number=2, node="GOOD", created="2026-11-10T00:00:00Z")
        client = FakeClient(backlog={1: [bad, good]})
        client.add_fail_for = {"BAD"}
        code, lines = run(client, backfill="2026-11-08T00:00:00Z")
        self.assertEqual(code, 0)
        self.assertIn("items_added=1 fields_set=5", lines[-1])
        self.assertIn("errors=1", lines[-1])
        self.assertIn("skipped_at_write=5", lines[-1])

    def test_complete_issues_do_not_block_the_ones_behind(self):
        done = [complete_issue(n, f"2026-11-08T{n % 24:02d}:{n // 24:02d}:00Z") for n in range(60)]
        late = issue(number=99, node="LATE", created="2026-11-12T00:00:00Z")
        client = FakeClient(backlog={1: done + [late]})
        code, lines = run(client, cap=6, backfill="2026-11-08T00:00:00Z")
        self.assertEqual(code, 0)
        self.assertEqual([c[1]["content"] for c in client.calls if c[0] == "add"], ["LATE"])
        self.assertIn("up_to_date=60", lines[0])
        self.assertIn("items_added=1 fields_set=5", lines[-1])

    def test_skipped_actions_take_no_write_of_the_cap(self):
        stale = [
            issue(number=n, node=f"S{n}", created=f"2026-11-09T0{n}:00:00Z", items=[item(f"SI{n}")])
            for n in (1, 2)
        ]
        late = issue(number=9, node="LATE", created="2026-11-12T00:00:00Z")
        client = FakeClient(backlog={1: stale + [late]})
        client.items["SI1"] = item("SI1", values=FULL)
        client.items["SI2"] = item("SI2", values=FULL)
        code, lines = run(client, cap=2, backfill="2026-11-08T00:00:00Z")
        self.assertEqual(code, 0)
        self.assertEqual([c[1]["content"] for c in client.calls if c[0] == "add"], ["LATE"])
        self.assertIn("skipped_at_write=10", lines[-1])
        self.assertIn("items_added=1 fields_set=1", lines[-1])
        self.assertIn("left_for_next_run=4", lines[-1])


class FailClosedTests(unittest.TestCase):
    def broken(self, mutate):
        bad = issue()
        mutate(bad)
        return FakeClient(repos={1: [issue(number=1, node="OK")], 2: [bad], 3: []})

    def test_pure_functions_fail_closed(self):
        for removed in (None, {}, {"totalCount": "1", "nodes": []}, {"totalCount": 0}):
            self.assertTrue(sweep.removed_from_board({"removed": removed}))
        for items in (
            None,
            {},
            {"totalCount": None, "nodes": []},
            {"totalCount": 0, "nodes": None},
        ):
            self.assertEqual(sweep.board_state({"projectItems": items}), ("unknown", None))
        node = item()
        node["project"] = None
        self.assertEqual(sweep.board_state(issue(items=[node]))[0], "unknown")
        self.assertEqual(sweep.plan_issue(1, issue(items=[node]), SINCE, TAX, catalog())[1], [])

    def test_malformed_issue_answer_stops_before_any_write(self):
        mutations = [
            lambda d: d.pop("removed"),
            lambda d: d.update(removed=None),
            lambda d: d.pop("projectItems"),
            lambda d: d.update(projectItems={"totalCount": "0", "nodes": []}),
            lambda d: d.update(renamed=None),
            lambda d: d.pop("createdAt"),
            lambda d: d.update(number="7"),
            lambda d: d.update(body={"text": SECRET_TITLE}),
            lambda d: d["projectItems"].update(
                nodes=[{"id": "X", "isArchived": False}], totalCount=1
            ),
        ]
        for mutate in mutations:
            client = self.broken(mutate)
            code, lines = run(client)
            self.assertEqual(code, sweep.EXIT_GRAPHQL)
            self.assertNotIn("add", client.names())
            self.assertNotIn("set", client.names())
            text = "\n".join(lines)
            self.assertIn("repository 2: an answer lacks the expected structure", text)
            self.assertNotIn(SECRET_TITLE, text)

    def test_malformed_page_or_rate_stops(self):
        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        original = client.post

        def post(query, variables, retry_server_errors=True):
            data = original(query, variables, retry_server_errors)
            if query == sweep.ISSUES_QUERY:
                data["data"]["node"]["issues"]["pageInfo"] = {}
            return data

        client.post = post
        self.assertEqual(run(client)[0], sweep.EXIT_GRAPHQL)
        self.assertNotIn("add", client.names())

        client = FakeClient(repos={1: [issue()], 2: [], 3: []})
        original2 = client.post

        def post2(query, variables, retry_server_errors=True):
            data = original2(query, variables, retry_server_errors)
            if query == sweep.ISSUES_QUERY:
                data["data"].pop("rateLimit")
            return data

        client.post = post2
        self.assertEqual(run(client)[0], sweep.EXIT_GRAPHQL)
        self.assertNotIn("add", client.names())

    def test_malformed_catalog_stops(self):
        answer = {
            "data": {
                "node": {
                    "number": 291,
                    "fields": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [
                            {"id": "F_WS", "name": "Workstream", "dataType": "SINGLE_SELECT"}
                        ],
                    },
                },
                "rateLimit": {"remaining": 4000},
            }
        }
        client = FakeClient(catalog_answer=answer)
        self.assertEqual(run(client)[0], sweep.EXIT_BOARD)
        self.assertEqual(client.names(), ["catalog"])

    def test_malformed_item_or_set_answer_stops_writing(self):
        client = FakeClient(repos={1: [issue(items=[item()])], 2: [], 3: []})
        client.items["ITEM1"] = {"id": "ITEM1", "project": {"id": sweep.PROJECT_ID}}
        code, lines = run(client)
        self.assertEqual(code, sweep.EXIT_GRAPHQL)
        self.assertNotIn("set", client.names())

        client = FakeClient(repos={1: [issue(items=[item()])], 2: [], 3: []})
        client.items["ITEM1"] = item()
        original = client.post

        def post(query, variables, retry_server_errors=True):
            if query == sweep.SET_MUTATION:
                client.calls.append(("set", variables))
                return {"data": {}}
            return original(query, variables, retry_server_errors)

        client.post = post
        code, lines = run(client)
        self.assertEqual(code, sweep.EXIT_GRAPHQL)
        self.assertEqual(client.names().count("set"), 1)


class DuplicateTests(unittest.TestCase):
    def test_issue_seen_on_two_pages_is_planned_once(self):
        a = issue(number=1, node="A")
        b = issue(number=2, node="B")

        def pages_of(index, variables):
            return [[a, b], [b]] if index == 1 else []

        client = paged(FakeClient(), pages_of)
        code, lines = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(c[1]["content"] for c in client.calls if c[0] == "add"), ["A", "B"])
        self.assertIn("issues=2", lines[0])


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_error(status, message="", headers=None):
    payload = json.dumps({"message": message}).encode()
    return urllib.error.HTTPError(
        "https://api.github.com/graphql", status, "x", headers or {}, io.BytesIO(payload)
    )


class ClientTests(unittest.TestCase):
    def client(self, answers):
        seen = []
        sleeps = []

        def urlopen(request, timeout):
            seen.append(request)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return FakeResponse(answer)

        return sweep.GitHubClient(FAKE_TOKEN, sleep=sleeps.append, urlopen=urlopen), seen, sleeps

    def test_ok_and_header(self):
        client, seen, _ = self.client([b'{"data": {}}'])
        self.assertEqual(client.post("q", {}), {"data": {}})
        self.assertEqual(seen[0].get_header("Authorization"), f"bearer {FAKE_TOKEN}")

    def test_status_codes(self):
        cases = [
            (http_error(401, "Bad credentials"), sweep.EXIT_SETUP),
            (http_error(403, "Resource not accessible by integration"), sweep.EXIT_SETUP),
            (http_error(403, "You have exceeded a secondary rate limit"), sweep.EXIT_RATE_LIMIT),
            (http_error(429), sweep.EXIT_RATE_LIMIT),
            (http_error(502, headers={"Retry-After": "60"}), sweep.EXIT_RATE_LIMIT),
            (http_error(404, "Not Found"), sweep.EXIT_UNREADABLE),
            (http_error(422, "Unprocessable"), sweep.EXIT_SERVER),
        ]
        for error, code in cases:
            client, _, _ = self.client([error])
            with self.assertRaises(sweep.SweepStop) as ctx:
                client.post("q", {})
            self.assertEqual(ctx.exception.code, code)
            self.assertNotIn(FAKE_TOKEN, ctx.exception.message)
            for word in ("credentials", "Resource", "secondary", "Not Found", "Unprocessable"):
                self.assertNotIn(word, ctx.exception.message)

    def test_server_errors_retry_twice_then_stop(self):
        client, _, sleeps = self.client([http_error(502), http_error(503), b'{"data": 1}'])
        self.assertEqual(client.post("q", {}), {"data": 1})
        self.assertEqual(sleeps, [5, 15])
        client, _, _ = self.client([http_error(502)] * 3)
        with self.assertRaises(sweep.SweepStop) as ctx:
            client.post("q", {})
        self.assertEqual(ctx.exception.code, sweep.EXIT_SERVER)

    def test_no_retry_on_write(self):
        client, _, sleeps = self.client([http_error(502)])
        with self.assertRaises(sweep.SweepStop):
            client.post("q", {}, retry_server_errors=False)
        self.assertEqual(sleeps, [])

    def test_network_and_bad_body(self):
        client, _, _ = self.client([OSError("x"), OSError("x"), OSError("x")])
        with self.assertRaises(sweep.SweepStop) as ctx:
            client.post("q", {})
        self.assertEqual(ctx.exception.code, sweep.EXIT_SERVER)
        client, _, _ = self.client([b"not json", b"[]", b"<html>"])
        with self.assertRaises(sweep.SweepStop) as ctx:
            client.post("q", {})
        self.assertEqual(ctx.exception.code, sweep.EXIT_SERVER)


class MainTests(unittest.TestCase):
    def call(self, env):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out):
            code = sweep.main()
        return code, out.getvalue()

    def test_setup_errors(self):
        self.assertEqual(self.call({"SWEEP_MODE": "apply"})[0], sweep.EXIT_SETUP)
        self.assertEqual(self.call({"SWEEP_WINDOW": "week"})[0], sweep.EXIT_SETUP)
        self.assertEqual(self.call({"SWEEP_MAX_WRITES": "500"})[0], sweep.EXIT_SETUP)
        code, text = self.call({"SWEEP_MODE": "write"})
        self.assertEqual(code, sweep.EXIT_SETUP)
        self.assertIn("PROJECT_BOARD_TOKEN is empty", text)

    def test_internal_error_prints_type_only(self):
        def boom(*args, **kwargs):
            raise KeyError(SECRET_TITLE)

        with mock.patch.object(sweep, "run", boom):
            code, text = self.call({"PROJECT_BOARD_TOKEN": FAKE_TOKEN})
        self.assertEqual(code, sweep.EXIT_INTERNAL)
        self.assertIn("internal error KeyError", text)
        self.assertNotIn(SECRET_TITLE, text)
        self.assertNotIn(FAKE_TOKEN, text)

    def test_main_reads_the_real_taxonomy_and_passes_settings(self):
        seen = {}

        def fake_run(client, mode, window, tax_fields, **kwargs):
            seen.update(mode=mode, window=window, fields=tax_fields, **kwargs)
            return 0

        env = {
            "PROJECT_BOARD_TOKEN": FAKE_TOKEN,
            "SWEEP_MODE": "write",
            "SWEEP_WINDOW": "long",
            "SWEEP_MAX_WRITES": "20",
            "SWEEP_BACKFILL_SINCE": "2026-11-08T00:00:00Z",
        }
        with mock.patch.object(sweep, "run", fake_run):
            code, _text = self.call(env)
        self.assertEqual(code, 0)
        self.assertEqual((seen["mode"], seen["window"], seen["cap"]), ("write", "long", 20))
        self.assertEqual(seen["backfill"], "2026-11-08T00:00:00Z")
        self.assertFalse(seen["details"])
        self.assertIn("AOU", seen["fields"]["Subsystem"])


if __name__ == "__main__":
    unittest.main()
