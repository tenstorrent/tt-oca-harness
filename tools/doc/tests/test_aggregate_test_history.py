# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import contextlib
import gzip
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

# Add the tools under test to the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aggregate_test_history  # noqa: E402
from aggregate_test_history import cell, run_id, run_stamp, tally  # noqa: E402


class RunStampTests(unittest.TestCase):
    """An archive is named by publish time, which can fall after the run."""

    ARCHIVE = "data/runs/2026-08-08-run1.result.json.gz"
    RAN_AT = "2026-08-07T23:30:00+00:00"

    def test_takes_the_first_candidate_it_can_read(self):
        # run_metadata, then the record, then the publish date in the name.
        for record, expected in (
            ({"run_metadata": {"generated_at": self.RAN_AT}}, "2026-08-07"),
            ({"generated_at": self.RAN_AT}, "2026-08-07"),
            ({}, "2026-08-08"),
            ({"run_metadata": {"generated_at": "not a date"}}, "2026-08-08"),
            ({"run_metadata": [1]}, "2026-08-08"),
            ({"run_metadata": None, "generated_at": 20260807}, "2026-08-08"),
        ):
            with self.subTest(record=record):
                self.assertEqual(run_stamp(record, self.ARCHIVE).date().isoformat(), expected)

    def test_assumes_utc_and_sorts_an_undatable_archive_last(self):
        self.assertEqual(
            run_stamp({"generated_at": "2026-08-07T23:30:00"}, "x.gz").tzinfo, timezone.utc
        )
        self.assertEqual(run_stamp({}, "undatable.gz"), datetime.min.replace(tzinfo=timezone.utc))


class RunIdTests(unittest.TestCase):
    """Two runs of one day are told apart by the identifier in the name."""

    def test_reads_the_identifier_either_publisher_records(self):
        for name, expected in (
            ("2026-08-08-run31205938306.result.json.gz", "31205938306"),
            ("2026-09-17-build81.summary.json.gz", "81"),
            ("2026-09-17-build82.summary.json.gz", "82"),
            ("2026-09-17.summary.json.gz", ""),
        ):
            with self.subTest(name=name):
                self.assertEqual(run_id(f"data/runs/{name}"), expected)


class TallyTests(unittest.TestCase):
    def test_groups_every_seed_under_its_test_in_order(self):
        record = {
            "tests_detail": [
                {"name": "a", "seed": 1, "status": "PASS"},
                {"name": "b", "seed": 2, "status": "PASS"},
                {"name": "a", "seed": 3, "status": "PASS"},
            ]
        }
        self.assertEqual(
            tally(record),
            {"a": [{"seed": 1}, {"seed": 3}], "b": [{"seed": 2}]},
        )

    def test_carries_a_reason_only_for_a_seed_that_did_not_pass(self):
        record = {
            "tests_detail": [
                {"name": "a", "seed": 1, "status": "PASS"},
                {"name": "a", "seed": 2, "status": "FAIL", "reason": "timeout"},
                {"name": "a", "seed": 3, "status": "ERROR"},
            ]
        }
        self.assertEqual(
            tally(record),
            {
                "a": [
                    {"seed": 1},
                    {"seed": 2, "reason": "timeout"},
                    {"seed": 3, "reason": "ERROR"},
                ]
            },
        )

    def test_ignores_anything_that_is_not_a_named_test(self):
        for detail in (
            [{"seed": 1, "status": "PASS"}, "not a dict", {"name": ""}],
            ["a", "b"],
            {"a": 1},
            None,
        ):
            with self.subTest(detail=detail):
                self.assertEqual(tally({"tests_detail": detail}), {})


class CellTests(unittest.TestCase):
    def test_counts_the_seeds_that_passed(self):
        seeds = [{"seed": 1}, {"seed": 2, "reason": "timeout"}, {"seed": 3}]
        self.assertEqual(cell(seeds), {"pass": 2, "total": 3, "seeds": seeds})
        self.assertEqual(cell([{"seed": 1, "reason": "timeout"}])["pass"], 0)


class ArchivePathsTests(unittest.TestCase):
    def list_tree(self, listing):
        """Return the paths archive_paths() keeps, and the command it ran."""
        with mock.patch.object(
            aggregate_test_history.subprocess, "check_output", return_value=listing
        ) as ran:
            paths = aggregate_test_history.archive_paths("origin/data", "data/runs/")
        return paths, ran.call_args.args[0]

    def test_keeps_the_archives_and_nothing_else(self):
        paths, _ = self.list_tree(
            "data/runs/2026-08-01-run1.result.json.gz\ndata/runs/notes.txt\ndata/runs/nested\n"
        )
        self.assertEqual(paths, ["data/runs/2026-08-01-run1.result.json.gz"])

    def test_an_unreadable_ref_lists_nothing(self):
        with mock.patch.object(
            aggregate_test_history.subprocess,
            "check_output",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            self.assertEqual(aggregate_test_history.archive_paths("no-such-ref", "data/runs/"), [])

    def test_git_cannot_reinterpret_the_ref_or_the_prefix(self):
        _, argv = self.list_tree("")
        self.assertIn("--literal-pathspecs", argv)
        self.assertEqual(argv[argv.index("--end-of-options") + 1], "origin/data")
        self.assertEqual(argv[argv.index("--") + 1], "data/runs/")


class ReadArchiveTests(unittest.TestCase):
    def read(self, blob):
        with mock.patch.object(aggregate_test_history.subprocess, "run") as ran:
            ran.return_value = mock.Mock(stdout=blob)
            return aggregate_test_history.read_archive("origin/data", "data/runs/a.gz")

    def test_reads_a_gzipped_record(self):
        self.assertEqual(
            self.read(gzip.compress(json.dumps({"flow": "dtp"}).encode())), {"flow": "dtp"}
        )

    def test_skips_anything_it_cannot_parse(self):
        for blob in (b"not gzip at all", gzip.compress(b"[]"), gzip.compress(b"{not json")):
            with self.subTest(blob=blob[:12]):
                self.assertIsNone(self.read(blob))

    def test_an_archive_git_cannot_show_is_skipped(self):
        with mock.patch.object(
            aggregate_test_history.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            self.assertIsNone(aggregate_test_history.read_archive("origin/data", "missing.gz"))


def record(flow, name, stamp, statuses, framework="cocotb", tool="vcs"):
    """One archived run of a single test, with a seed per status given."""
    return {
        "flow": flow,
        "framework": framework,
        "tool": tool,
        "run_metadata": {"generated_at": stamp},
        "tests_detail": [
            {"name": name, "seed": i, "status": status} for i, status in enumerate(statuses)
        ],
    }


def summary_archive(*records):
    """An archive that wraps one record per DUT rather than being one itself."""
    return {"generated_at": "2026-08-01T00:00:00+00:00", "results": list(records)}


def series_for(history, flow, framework="cocotb"):
    """The one series in the written history naming this flow and framework."""
    return next(
        entry
        for entry in history["series"]
        if entry["flow"] == flow and entry["framework"] == framework
    )


class MainTests(unittest.TestCase):
    """Aggregates published archives into the test-history grid."""

    ARCHIVES = {
        "data/runs/2026-08-02-run2.result.json.gz": record(
            "dtp", "a", "2026-08-02T00:00:00+00:00", ["PASS", "FAIL"]
        ),
        "data/runs/2026-08-01-run1.result.json.gz": record(
            "dtp", "a", "2026-08-01T00:00:00+00:00", ["PASS"]
        ),
    }

    def replace(self, name, **kwargs):
        """Replace an attribute of the tool under test for this test."""
        self.enterContext(mock.patch.object(aggregate_test_history, name, **kwargs))

    def aggregate(self, archives=None, limit=0, publishers=None):
        """
        Run main() over the given archives, returning the history it wrote.

        Pass `publishers` as {runs-dir: {path: record}} to aggregate several at
        once, one --runs-dir each.
        """
        by_dir = publishers or {"data/runs/": self.ARCHIVES if archives is None else archives}
        # read_archive is given a path alone, whichever publisher it came from.
        every = {path: rec for group in by_dir.values() for path, rec in group.items()}

        out = Path(self.enterContext(tempfile.TemporaryDirectory())) / "test-history.json"
        argv = [__name__, str(out), "--limit", str(limit)]
        # Naming no publisher leaves the default runs directory in use.
        for runs_dir in publishers or {}:
            argv += ["--runs-dir", runs_dir]

        self.enterContext(mock.patch.object(sys, "argv", argv))
        # Stand in for the two functions that reach the data branch through git.
        self.replace("archive_paths", side_effect=lambda ref, runs_dir: sorted(by_dir[runs_dir]))
        self.replace("read_archive", side_effect=lambda ref, path: every[path])
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

        self.assertEqual(aggregate_test_history.main(), 0)
        return json.loads(out.read_text())

    def test_orders_runs_oldest_first_with_a_cell_each(self):
        series = series_for(self.aggregate(), "dtp")
        self.assertEqual([run["date"] for run in series["runs"]], ["2026-08-01", "2026-08-02"])
        self.assertEqual([run["id"] for run in series["runs"]], ["1", "2"])
        cells = series["tests"]["a"]
        self.assertEqual([c["pass"] for c in cells], [1, 1])
        self.assertEqual([c["total"] for c in cells], [1, 2])

    def test_columns_stay_aligned_when_a_test_did_not_run(self):
        archives = dict(self.ARCHIVES)
        archives["data/runs/2026-08-03-run3.result.json.gz"] = record(
            "dtp", "b", "2026-08-03T00:00:00+00:00", ["PASS"]
        )
        tests = series_for(self.aggregate(archives), "dtp")["tests"]
        self.assertEqual(len(tests["a"]), 3)
        self.assertEqual(len(tests["b"]), 3)
        self.assertIsNone(tests["a"][2])
        self.assertEqual(tests["b"][:2], [None, None])

    def test_limit_keeps_the_newest_runs(self):
        series = series_for(self.aggregate(limit=1), "dtp")
        self.assertEqual([run["date"] for run in series["runs"]], ["2026-08-02"])

    def test_a_ref_with_no_archives_writes_no_series(self):
        self.assertEqual(self.aggregate({}), {"series": []})

    def test_an_unreadable_archive_is_skipped_rather_than_ending_the_run(self):
        archives = dict(self.ARCHIVES)
        archives["data/runs/2026-08-03-run3.result.json.gz"] = None
        series = series_for(self.aggregate(archives), "dtp")
        self.assertEqual([run["id"] for run in series["runs"]], ["1", "2"])
        self.assertEqual(len(series["tests"]["a"]), 2)

    def test_one_block_under_two_frameworks_reports_as_two_series(self):
        archives = dict(self.ARCHIVES)
        archives["data/runs/2026-08-04-run4.result.json.gz"] = record(
            "dtp", "a", "2026-08-04T00:00:00+00:00", ["PASS"], framework="uvm"
        )
        history = self.aggregate(archives)
        self.assertEqual(
            sorted((s["flow"], s["framework"], s["tool"]) for s in history["series"]),
            [("dtp", "cocotb", "vcs"), ("dtp", "uvm", "vcs")],
        )
        # Series run on their own cadences, so each carries its own run axis.
        self.assertEqual(len(series_for(history, "dtp", "cocotb")["runs"]), 2)
        self.assertEqual(len(series_for(history, "dtp", "uvm")["runs"]), 1)

    def test_reads_the_records_a_summary_shaped_archive_wraps(self):
        wrapped = summary_archive(
            record("dtp", "a", "2026-08-05T00:00:00+00:00", ["PASS"]),
            record("sep", "b", "2026-08-05T00:00:00+00:00", ["FAIL"]),
        )
        history = self.aggregate({"data/runs/2026-08-05-build9.summary.json.gz": wrapped})
        self.assertEqual(
            sorted(s["flow"] for s in history["series"]),
            ["dtp", "sep"],
        )

    def test_the_limit_applies_to_each_publisher(self):
        busy = {
            f"vcs/dtp_cocotb/data/runs/2026-08-0{n}-run{n}.result.json.gz": record(
                "dtp", "a", f"2026-08-0{n}T00:00:00+00:00", ["PASS"]
            )
            for n in (1, 2, 3)
        }
        quiet = {
            "vcs/sep_cocotb/data/runs/2026-08-01-run9.result.json.gz": record(
                "sep", "b", "2026-08-01T00:00:00+00:00", ["PASS"]
            )
        }
        history = self.aggregate(
            publishers={"vcs/dtp_cocotb/data/runs/": busy, "vcs/sep_cocotb/data/runs/": quiet},
            limit=2,
        )
        # The busy publisher is trimmed; the quiet one is not crowded out of it.
        self.assertEqual(len(series_for(history, "dtp")["runs"]), 2)
        self.assertEqual(len(series_for(history, "sep")["runs"]), 1)

    def test_a_record_without_a_flow_names_no_series(self):
        nameless = record("", "a", "2026-08-06T00:00:00+00:00", ["PASS"])
        self.assertEqual(
            self.aggregate({"data/runs/2026-08-06-run6.result.json.gz": nameless}),
            {"series": []},
        )


if __name__ == "__main__":
    unittest.main()
