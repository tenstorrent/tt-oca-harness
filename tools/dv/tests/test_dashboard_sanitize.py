# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the rewrite that keeps host-specific paths and hosts out of published data.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import gzip
import io
import json
import os
import shutil
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
                ("rsync out/ jdoe@build-04:/site/run/", f"rsync out/ {EXTERNAL_URL}"),
                ("x@internal.example@github.com", EXTERNAL_HOST),
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
        ):
            with self.subTest(text=text):
                once = self.scrubber.text(text)
                self.assertEqual(self.scrubber.text(once), once)

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


if __name__ == "__main__":
    unittest.main()
