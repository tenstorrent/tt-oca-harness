# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the rewrite that keeps host-specific paths and hosts out of published data.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import gzip
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import cli, gen_dashboard  # noqa: E402
from dashboard.collect_results import write_result  # noqa: E402
from dashboard.sanitize import (  # noqa: E402
    EXTERNAL_HOST,
    EXTERNAL_PATH,
    EXTERNAL_URL,
    REPO_ROOT,
    Scrubber,
    checkout_scrubber,
)
from dashboard.schema import make_result, make_summary, read_json, update_history  # noqa: E402

WORKSPACE = "/site/ci/work/tt-oca-harness"
INTERNAL_URL = "http://ci.example.internal:8080/job/dtp/42/"


def quietly(function, *args):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return function(*args)


class TempRoot(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)


class ScrubText(TempRoot):
    def setUp(self):
        super().setUp()
        for directory in ("hw/common/dv", "tools/dv", "local/bin"):
            (self.root / directory).mkdir(parents=True)
        self.scrubber = Scrubber(
            repo_root=self.root,
            roots=(str(self.root),),
            anchors=frozenset({"hw", "tools"}),
        )

    def assertScrubs(self, cases):
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.scrubber.text(text), expected)

    def test_a_path_under_the_checkout_becomes_repository_relative(self):
        self.assertScrubs(
            [
                (f"`{self.root}/hw/common/dv/a.sv` failed", "`hw/common/dv/a.sv` failed"),
                (f"{self.root}/hw/common/dv/a.sv:12: error", "hw/common/dv/a.sv:12: error"),
                (f"cd {self.root}", "cd ."),
                (f"{self.root}//hw/common/dv/a.sv", "hw/common/dv/a.sv"),
                (f"{self.root}/hw/a.sv:{self.root}/hw/b.sv", "hw/a.sv:hw/b.sv"),
            ]
        )

    def test_a_path_from_another_checkout_keeps_its_repository_tail(self):
        self.assertScrubs(
            [
                (
                    f"UVM_ERROR {WORKSPACE}/dtp/uvm/hw/common/dv/a.svh(67) @ 10: CHK FAIL",
                    "UVM_ERROR hw/common/dv/a.svh(67) @ 10: CHK FAIL",
                ),
                (f"+FW={WORKSPACE}/hw/common/dv/fw.hex", "+FW=hw/common/dv/fw.hex"),
                (f"{WORKSPACE}//hw/common/dv/a.sv", "hw/common/dv/a.sv"),
                (f"{WORKSPACE}/hw/common/dv/build/../a.vdb", "hw/common/dv/build/../a.vdb"),
            ]
        )

    def test_a_path_outside_the_repository_becomes_external(self):
        self.assertScrubs(
            [
                (
                    f"`{WORKSPACE}/.venv/bin/python3` exceeded timeout of 7200s",
                    f"`{EXTERNAL_PATH}` exceeded timeout of 7200s",
                ),
                ("/tools/vendor/sim/bin/simv", EXTERNAL_PATH),
                ("/opt/site/local/bin/tool", EXTERNAL_PATH),
                ("-I/site/include", f"-I{EXTERNAL_PATH}"),
                ("-f/site/files.f", f"-f{EXTERNAL_PATH}"),
                ("PYTHONPATH=/site/a:/site/b", f"PYTHONPATH={EXTERNAL_PATH}:{EXTERNAL_PATH}"),
                ("/site/ci//user_dev/vip/a.sv", EXTERNAL_PATH),
                (f"{self.root}/../vip/a.sv", EXTERNAL_PATH),
                (f"{WORKSPACE}/hw/../vip/a.sv", EXTERNAL_PATH),
                ("/x/hw/" + "a" * 300, EXTERNAL_PATH),
            ]
        )

    def test_relative_text_is_left_alone(self):
        for text in (
            "hw/sys/dtp/dv/x.sv",
            "./run.sh",
            "../a/b",
            "3/4 passed",
            "and/or",
            "~/notes",
            "seq@1234",
            "first_flagged=0x5a@1250ns",
            "allow@0x20 + addr-NACK@0x10",
            "UVM_INFO @ 0: reporter",
            "8680 ps vs 8681 ps expected (+/- 2 CDC skew)",
            "COVCMP-34c7a9b34b98e3bb",
            "smoke@fast",
            "label id_width_rd@version_lo",
            "uses: actions/checkout@v4",
            "cocotb@2.0.0.dev0 and pkg@1.x on python@3.x",
            "https://github.com/o/r/tree/feature@next",
            "//top.dut/x",
            "a@b.@c",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.scrubber.text(text), text)

    def test_a_host_outside_github_becomes_external(self):
        self.assertScrubs(
            [
                (f"see {INTERNAL_URL} for the log", f"see {EXTERNAL_URL} for the log"),
                ("file:///site/x", EXTERNAL_URL),
                ("ssh://git@git.example.internal/group/repo", EXTERNAL_URL),
                ("git@git.example.internal:group/repo.git", EXTERNAL_URL),
                ("checkout failed: 27000@licserver01", f"checkout failed: {EXTERNAL_HOST}"),
                ("LM_LICENSE_FILE=27000@10.0.0.5", f"LM_LICENSE_FILE={EXTERNAL_HOST}"),
                (
                    "LM_LICENSE_FILE=27000@lic01:27001@lic02",
                    f"LM_LICENSE_FILE={EXTERNAL_HOST}:{EXTERNAL_HOST}",
                ),
                ("mail jdoe@build.example.com.", f"mail {EXTERNAL_HOST}."),
                ("from jdoe.last@corp.example.com://x", f"from {EXTERNAL_HOST}://x"),
                ("open file:///Users/Alice Smith/x.html now", f"open {EXTERNAL_URL} now"),
                (f"{INTERNAL_URL}=/Users/Alice Smith/x", EXTERNAL_URL),
                ("rsync out/ jdoe@build-04:/site/run/", f"rsync out/ {EXTERNAL_URL}"),
                ("x@internal.example@github.com", EXTERNAL_HOST),
                ("rsync out/ jdoe+ci@build-04:/site/run/", f"rsync out/ {EXTERNAL_URL}"),
                ("mail user+tag@build.example.internal", f"mail {EXTERNAL_HOST}"),
                ("27000@lic_server", EXTERNAL_HOST),
                ("jdoe@build_04.corp.example.com", EXTERNAL_HOST),
                ("ssh user@[fd00::1]", f"ssh {EXTERNAL_HOST}"),
                ("http://[fd00::1]:8080/job/1", EXTERNAL_URL),
                ("https://[2001:db8::1]/x", EXTERNAL_URL),
                (
                    "https://github.com/o/r.git:/site/ci/x",
                    f"https://github.com/o/r.git:{EXTERNAL_PATH}",
                ),
                (
                    f"https://github.com/o/r?next={INTERNAL_URL}",
                    f"https://github.com/o/r?next={EXTERNAL_URL}",
                ),
            ]
        )

    def test_a_github_url_stays_without_its_credentials(self):
        self.assertScrubs(
            [
                (
                    "https://github.com/tenstorrent/tt-oca-harness/issues/1",
                    "https://github.com/tenstorrent/tt-oca-harness/issues/1",
                ),
                ("https://user:secret@github.com/o/r.git", "https://github.com/o/r.git"),
                (
                    "git@github.com:tenstorrent/tt-oca-harness.git",
                    "git@github.com:tenstorrent/tt-oca-harness.git",
                ),
            ]
        )

    def test_the_rewrite_is_idempotent(self):
        for text in (
            f"{WORKSPACE}/dtp/hw/common/dv/a.svh(67) and {WORKSPACE}/.venv/bin/python3",
            f"{INTERNAL_URL} https://user:secret@github.com/o/r 27000@licserver01",
            f"git@git.example.internal:group/repo {self.root}/tools/dv/run_dv.py",
            "lock held by name@/opt/x",
            "x@host.example@y",
            "'/Users/Alice B Smith/x' and /Users/Alice Smith/y to c/d",
            "a@b.@c",
            "a@b.@c:5280@lic.example.com",
            "jdoe@build-04:27000@lic.example.com",
            "5280@lic.example.com:jdoe@build-04:/site/x/",
        ):
            with self.subTest(text=text):
                once = self.scrubber.text(text)
                self.assertEqual(self.scrubber.text(once), once)

    def test_a_path_with_spaces_is_rewritten_whole(self):
        self.assertScrubs(
            [
                ("/Users/Alice Smith/project/result.json", EXTERNAL_PATH),
                ("missing '/Users/Alice B Smith/x.json'", f"missing '{EXTERNAL_PATH}'"),
                ("missing '/Users/Alice  Smith/x.json'", f"missing '{EXTERNAL_PATH}'"),
                ('"/Users/Alice Smith/x" is not readable', f'"{EXTERNAL_PATH}" is not readable'),
                (
                    "`/opt/Program Files/bin/vcs` exceeded timeout",
                    f"`{EXTERNAL_PATH}` exceeded timeout",
                ),
                (
                    "/home/jdoe/My Documents/ws/hw/common/dv/a.sv:12: error",
                    "hw/common/dv/a.sv:12: error",
                ),
            ]
        )

    def test_text_after_a_path_stays_when_it_is_not_part_of_it(self):
        self.assertScrubs(
            [
                ("copied /a/b to c/d", f"copied {EXTERNAL_PATH} to c/d"),
                ("/a/b is not in c/d", f"{EXTERNAL_PATH} is not in c/d"),
                ("cp /site/x hw/common/dv/a.sv", f"cp {EXTERNAL_PATH} hw/common/dv/a.sv"),
                ("`/site/bin/vcs -f hw/a.f` failed", f"`{EXTERNAL_PATH} -f hw/a.f` failed"),
                ("'/a/b' and 'c/d'", f"'{EXTERNAL_PATH}' and 'c/d'"),
            ]
        )

    def test_a_path_that_follows_a_path_is_rewritten_on_its_own(self):
        self.assertScrubs(
            [
                (
                    f"{self.root}/hw/common/dv/simv +load=/scratch/jdoe/a.hex",
                    f"hw/common/dv/simv +load={EXTERNAL_PATH}",
                ),
                (
                    f"vcs {WORKSPACE}/hw/common/dv/a.sv +incdir+/Users/alice/inc",
                    f"vcs hw/common/dv/a.sv +incdir+{EXTERNAL_PATH}",
                ),
                (f"{self.root}/tools/dv FOO=/Users/alice/x", f"tools/dv FOO={EXTERNAL_PATH}"),
                (f"{WORKSPACE}/hw/common/dv/x=/Users/alice/y", f"hw/common/dv/x={EXTERNAL_PATH}"),
                (
                    f"{self.root}/tools/dv/run.py=-f/home/jdoe/a.f",
                    f"tools/dv/run.py=-f{EXTERNAL_PATH}",
                ),
                (
                    f"{WORKSPACE}/hw/common/dv/x.sv=+incdir+/home/jdoe/inc",
                    f"hw/common/dv/x.sv=+incdir+{EXTERNAL_PATH}",
                ),
                ("/site/ws/label=linux/tt-oca-harness/hw/common/dv/a.sv", "hw/common/dv/a.sv"),
                ("/home/jdoe/runs/user=jdoe/sim.log", EXTERNAL_PATH),
                (
                    f"'{self.root}/hw/common/dv/a.sv vs /home/jdoe/b.sv'",
                    f"'hw/common/dv/a.sv vs {EXTERNAL_PATH}'",
                ),
                (f"'{self.root}/tools:/Users/alice/lib'", f"'tools:{EXTERNAL_PATH}'"),
                ('"/site/x.log: No such file"', f'"{EXTERNAL_PATH}: No such file"'),
            ]
        )

    def test_keys_are_rewritten_like_values(self):
        value = {
            f"{WORKSPACE}/.venv/x": 1,
            f"{self.root}/hw/common/dv/a.sv": {"27000@licserver01": 2},
            INTERNAL_URL: [{"/opt/x": 1}],
            "line_percent": 4,
        }
        clean = self.scrubber.value(value)
        self.assertEqual(
            clean,
            {
                EXTERNAL_PATH: 1,
                "hw/common/dv/a.sv": {EXTERNAL_HOST: 2},
                EXTERNAL_URL: [{EXTERNAL_PATH: 1}],
                "line_percent": 4,
            },
        )
        self.assertEqual(self.scrubber.value(clean), clean)

    def test_two_keys_that_rewrite_alike_are_an_error(self):
        for value in (
            {"/site/a": 1, "/site/b": 2},
            {EXTERNAL_PATH: 1, "/site/b": 2},
            {"hw/a.sv": 1, f"{self.root}/hw/a.sv": 2},
        ):
            with self.subTest(keys=list(value)):
                with self.assertRaises(ValueError) as caught:
                    self.scrubber.value(value)
                self.assertNotIn("/site", str(caught.exception))
                self.assertNotIn(str(self.root), str(caught.exception))

    def test_every_string_in_a_json_value_is_rewritten(self):
        value = {
            "reasons": [f"{WORKSPACE}/.venv/bin/python3", 3, None, {"path": "hw/a.sv"}],
            "percent": 94.5,
            "complete": True,
        }
        self.assertEqual(
            self.scrubber.value(value),
            {
                "reasons": [EXTERNAL_PATH, 3, None, {"path": "hw/a.sv"}],
                "percent": 94.5,
                "complete": True,
            },
        )


class CheckoutScrubber(TempRoot):
    def test_a_symlinked_checkout_matches_in_both_forms(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "link"
        link.symlink_to(real)
        scrubber = checkout_scrubber(link)
        self.assertEqual(scrubber.text(f"{link}/hw/a.sv"), "hw/a.sv")
        self.assertEqual(scrubber.text(f"{real}/hw/a.sv"), "hw/a.sv")

    def test_a_directory_outside_git_has_no_anchors(self):
        with mock.patch.dict(os.environ):
            for name in ("GIT_DIR", "GIT_WORK_TREE"):
                os.environ.pop(name, None)
            self.assertEqual(checkout_scrubber(self.root).anchors, frozenset())

    def test_a_checkout_whose_path_has_a_space_becomes_repository_relative(self):
        root = self.root / "Alice Smith" / "tt-oca-harness (2)"
        root.mkdir(parents=True)
        scrubber = checkout_scrubber(root)
        for text, expected in (
            (f"{root}/hw/sys/dtp/a.sv:12: error", "hw/sys/dtp/a.sv:12: error"),
            (f"cd {root}", "cd ."),
            (f"{root}/../vip/a.sv", EXTERNAL_PATH),
        ):
            with self.subTest(text=text):
                self.assertEqual(scrubber.text(text), expected)

    def test_a_checkout_in_a_numbered_workspace_becomes_repository_relative(self):
        root = self.root / "job@2"
        root.mkdir()
        self.assertEqual(
            checkout_scrubber(root).text(f"{root}/hw/sys/dtp/a.sv:12: error"),
            "hw/sys/dtp/a.sv:12: error",
        )

    @unittest.skipUnless((REPO_ROOT / ".git").exists(), "needs a Git checkout")
    def test_the_checkout_anchors_on_its_tracked_top_level(self):
        anchors = checkout_scrubber(REPO_ROOT).anchors
        self.assertTrue({"hw", "tools"} <= anchors)


class CollectWritesSanitizedRecords(TempRoot):
    def test_the_record_and_its_staged_coverage_files_are_sanitized(self):
        report = self.root / "build" / "run" / "cov" / "report"
        report.mkdir(parents=True)
        sample = {"source": f"{WORKSPACE}/.venv/x.sv", "native_locator": f"{self.root}/hw/a.sv:3"}
        (report / "summary.json").write_text(
            json.dumps({"holes_summary": {"samples": [sample]}}), encoding="utf-8"
        )
        (report / "policy-application.json").write_text(
            f"policy {WORKSPACE}/.venv/p.toml", encoding="utf-8"
        )
        (report.parent / "coverage.json").write_text(
            json.dumps({"inputs": [{"path": f"{self.root}/build/run/cov/merged"}]}),
            encoding="utf-8",
        )
        result = make_result(
            repo_root=self.root,
            flow="dtp",
            kind="sim",
            status="FAIL",
            tool="verilator",
            coverage_details={
                "report": "build/run/cov/report",
                "manifest": "build/run/cov/coverage.json",
            },
            failure_buckets=[
                {"signature": f"`{WORKSPACE}/.venv/bin/python3` exceeded timeout", "count": 1}
            ],
            tests_detail=[{"name": "t", "status": "FAIL", "reason": f"missing {self.root}/hw/f"}],
        )
        output = self.root / "bundle" / "dtp.result.json"
        write_result(self.root, result, output)

        record = read_json(output)
        staged = read_json(output.parent / record["coverage"]["summary"])
        manifest = read_json(output.parent / record["coverage"]["manifest"])
        for published in (record, staged, manifest):
            text = json.dumps(published)
            self.assertNotIn(WORKSPACE, text)
            self.assertNotIn(str(self.root), text)
        self.assertEqual(set(record), set(result))
        self.assertEqual(manifest, {"inputs": [{"path": "build/run/cov/merged"}]})
        self.assertEqual(
            (output.parent / record["coverage"]["policy_application"]).read_text(),
            f"policy {EXTERNAL_PATH}",
        )
        self.assertEqual(
            record["failure_buckets"][0]["signature"], f"`{EXTERNAL_PATH}` exceeded timeout"
        )
        self.assertEqual(record["tests_detail"][0]["reason"], "missing hw/f")
        self.assertEqual(
            staged["holes_summary"]["samples"],
            [{"source": EXTERNAL_PATH, "native_locator": "hw/a.sv:3"}],
        )

    def test_a_run_recorded_outside_the_checkout_publishes_no_path(self):
        run = Path(tempfile.mkdtemp()).resolve() / "run"
        self.addCleanup(shutil.rmtree, run.parent, ignore_errors=True)
        (run / "cov").mkdir(parents=True)
        (run / "cov" / "coverage.json").write_text("{}", encoding="utf-8")
        result = make_result(
            repo_root=self.root,
            flow="dtp",
            kind="sim",
            status="FAIL",
            tool="verilator",
            coverage_details={"manifest": str(run / "cov" / "coverage.json")},
            artifacts={"run_dir": str(run), "log": str(run / "sim.log")},
            run_metadata={"run_dir": str(run)},
        )
        output = self.root / "bundle" / "dtp.result.json"
        write_result(self.root, result, output)
        record = read_json(output)
        self.assertEqual(record["artifacts"]["run_dir"], EXTERNAL_PATH)
        self.assertEqual(record["run_metadata"]["run_dir"], EXTERNAL_PATH)
        self.assertEqual(record["artifacts"]["log"], EXTERNAL_PATH)
        self.assertEqual(record["coverage"]["source_manifest"], EXTERNAL_PATH)
        self.assertEqual(record["coverage"]["manifest"], "artifacts/dtp/coverage/coverage.json")


class DashboardSanitizesItsInputs(TempRoot):
    def record(self, reason, start_time):
        return make_result(
            repo_root=self.root,
            flow="dtp",
            kind="sim",
            status="FAIL",
            tool="vcs",
            framework="cocotb",
            start_time=start_time,
            artifacts={"run_dir": "vcs/dtp/runs/cocotb"},
            run_metadata={"git": {"remote": "git@git.example.internal:group/repo.git"}},
            tests_detail=[{"name": "t", "status": "FAIL", "reason": reason}],
        )

    def test_the_summary_and_the_prior_history_are_sanitized(self):
        prior = update_history(
            None, make_summary([self.record("plain failure", "2026-10-03T10:03:00+00:00")])
        )
        prior["points"][0]["per_dut"][0]["holes_summary"] = {
            "samples": [{"source": f"{WORKSPACE}/.venv/x.sv"}]
        }
        prior_id = prior["points"][0]["id"]
        history_in = self.root / "history-in.json"
        history_in.write_text(json.dumps(prior), encoding="utf-8")
        results = self.root / "dtp.result.json"
        results.write_text(
            json.dumps(
                self.record(
                    f"`{WORKSPACE}/.venv/bin/python3` exceeded timeout",
                    "2026-10-04T10:03:00+00:00",
                )
            ),
            encoding="utf-8",
        )
        summary_out = self.root / "summary.json"
        history_out = self.root / "history.json"

        status = quietly(
            gen_dashboard.main,
            [
                "--results",
                str(results),
                "--summary-out",
                str(summary_out),
                "--history-in",
                str(history_in),
                "--history-out",
                str(history_out),
            ],
        )

        self.assertEqual(status, 0)
        for path in (summary_out, history_out):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(WORKSPACE, text)
            self.assertNotIn("example.internal", text)
        history = read_json(history_out)
        self.assertEqual(history["points"][0]["id"], prior_id)
        self.assertEqual(len(history["points"]), 2)


class SanitizeCommand(TempRoot):
    def setUp(self):
        super().setUp()
        self.workspace = self.root / "ws"
        data = {"reason": f"{self.workspace}/hw/a.sv failed"}
        self.plain = self.root / "summary.json"
        self.plain.write_text(json.dumps(data), encoding="utf-8")
        self.archive = self.root / "runs" / "2026-10-06-run1.summary.json.gz"
        self.archive.parent.mkdir()
        self.archive.write_bytes(gzip.compress(json.dumps(data).encode("utf-8")))
        self.files = [str(self.plain), str(self.archive)]

    def run_command(self, *options):
        return quietly(cli.main, ["sanitize", *options, *self.files])

    def test_check_reports_a_file_to_rewrite_and_leaves_it(self):
        before = [self.plain.read_bytes(), self.archive.read_bytes()]
        self.assertEqual(self.run_command("--check"), 1)
        self.assertEqual([self.plain.read_bytes(), self.archive.read_bytes()], before)

    def test_a_rewrite_makes_check_pass(self):
        root = ("--root", str(self.workspace))
        self.assertEqual(self.run_command(*root), 0)
        self.assertEqual(read_json(self.plain), {"reason": "hw/a.sv failed"})
        archived = json.loads(gzip.decompress(self.archive.read_bytes()))
        self.assertEqual(archived, {"reason": "hw/a.sv failed"})
        self.assertEqual(self.run_command("--check", *root), 0)

    def test_a_bad_file_is_named_and_the_others_are_still_rewritten(self):
        truncated = self.root / "runs" / "truncated.summary.json.gz"
        truncated.write_bytes(gzip.compress(b"{}")[:-6])
        self.files[1:1] = [str(self.root / "missing.json"), str(truncated)]
        errors = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(errors):
            status = cli.main(["sanitize", "--root", str(self.workspace), *self.files])
        self.assertEqual(status, 2)
        self.assertIn("missing.json", errors.getvalue())
        self.assertIn("truncated.summary.json.gz", errors.getvalue())
        self.assertEqual(read_json(self.plain), {"reason": "hw/a.sv failed"})
        archived = json.loads(gzip.decompress(self.archive.read_bytes()))
        self.assertEqual(archived, {"reason": "hw/a.sv failed"})

    def test_a_key_is_checked_and_rewritten(self):
        keyed = self.root / "keyed.json"
        keyed.write_text(json.dumps({"/Users/Alice/private": 1}), encoding="utf-8")
        self.files = [str(keyed)]
        self.assertEqual(self.run_command("--check"), 1)
        self.assertEqual(self.run_command(), 0)
        self.assertEqual(read_json(keyed), {EXTERNAL_PATH: 1})
        self.assertEqual(self.run_command("--check"), 0)

    def test_a_file_whose_keys_collide_is_left_as_it_was(self):
        colliding = self.root / "colliding.json"
        colliding.write_text(json.dumps({"/site/a": 1, "/site/b": 2}), encoding="utf-8")
        before = colliding.read_bytes()
        self.files = [str(colliding)]
        errors = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(errors):
            status = cli.main(["sanitize", *self.files])
        self.assertEqual(status, 2)
        self.assertNotIn("/site", errors.getvalue())
        self.assertEqual(colliding.read_bytes(), before)

    def test_a_rewrite_keeps_the_file_mode(self):
        self.plain.chmod(0o640)
        self.assertEqual(self.run_command("--root", str(self.workspace)), 0)
        self.assertEqual(stat.S_IMODE(self.plain.stat().st_mode), 0o640)

    def test_a_failed_write_leaves_each_file_as_it_was(self):
        before = [self.plain.read_bytes(), self.archive.read_bytes()]
        full = OSError(28, "No space left on device")
        with mock.patch("dashboard.sanitize.os.fsync", side_effect=full):
            self.assertEqual(self.run_command("--root", str(self.workspace)), 2)
        self.assertEqual([self.plain.read_bytes(), self.archive.read_bytes()], before)
        self.assertEqual(sorted(path.name for path in self.root.rglob(".*.tmp")), [])

    def test_a_rewrite_through_a_symlink_cleans_its_target(self):
        link = self.root / "link.json"
        link.symlink_to(self.plain)
        self.files = [str(link)]
        self.assertEqual(self.run_command("--root", str(self.workspace)), 0)
        self.assertTrue(link.is_symlink())
        self.assertEqual(read_json(self.plain), {"reason": "hw/a.sv failed"})

    def test_a_file_named_like_an_option_is_rewritten(self):
        names = ["--check", "--ch", "-h", "--root", "--"]
        for name in names:
            shutil.copyfile(self.plain, self.root / name)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)
        self.assertEqual(quietly(cli.main, ["sanitize", "--check", "--", *names]), 1)
        root = ("--root", str(self.workspace))
        self.assertEqual(quietly(cli.main, ["sanitize", *root, "--", *names]), 0)
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(read_json(self.root / name), {"reason": "hw/a.sv failed"})


if __name__ == "__main__":
    unittest.main()
