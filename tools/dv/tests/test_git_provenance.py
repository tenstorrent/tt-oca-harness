# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the git state a run records: `git_info`, the diff archive
`git_provenance` writes, the worker's `repo_identity`, and the checkout check.

Every git call is answered by a stand-in, so the tests read no real checkout.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import results, worker  # noqa: E402
from runlib.executors.manifest import repo_identity  # noqa: E402

COMMIT = "1" * 40
STATUS = " M src/top.sv\n"
DIFF = "diff --git a/src/top.sv b/src/top.sv\n"


class FakeGit:
    """Answers `subprocess.run` for the git subcommands the runner asks."""

    def __init__(
        self,
        *,
        status: str = STATUS,
        failing: tuple[str, ...] = (),
        timing_out: tuple[str, ...] = (),
        missing: bool = False,
    ) -> None:
        self.status = status
        self.failing = failing
        self.timing_out = timing_out
        self.missing = missing
        self.timeouts: dict[str, Any] = {}

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if self.missing:
            raise FileNotFoundError(argv[0])
        words = list(argv[1:])
        if words[:1] == ["-C"]:
            words = words[2:]
        command = words[0]
        self.timeouts[command] = kwargs.get("timeout")
        if command in self.timing_out:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout") or 0)
        if command in self.failing:
            return subprocess.CompletedProcess(argv, 128, stdout="")
        outputs = {"rev-parse": "main\n" if "--abbrev-ref" in words else COMMIT + "\n"}
        outputs.update({"status": self.status, "diff": DIFF})
        return subprocess.CompletedProcess(argv, 0, stdout=outputs[command])

    def patch(self) -> Any:
        return mock.patch.object(subprocess, "run", side_effect=self)


class GitInfoTest(unittest.TestCase):
    def info(self, git: FakeGit) -> dict[str, str]:
        with git.patch():
            info: dict[str, str] = results.git_info(Path("/checkout"))
        return info

    def test_a_dirty_and_a_clean_tree(self) -> None:
        self.assertEqual(
            self.info(FakeGit()), {"commit": COMMIT, "branch": "main", "dirty": "true"}
        )
        self.assertEqual(self.info(FakeGit(status=""))["dirty"], "false")

    def test_a_status_git_does_not_answer_is_unknown(self) -> None:
        for git in (FakeGit(timing_out=("status",)), FakeGit(failing=("status",))):
            with self.subTest(timing_out=git.timing_out, failing=git.failing):
                info = self.info(git)
                self.assertEqual(info["dirty"], "unknown")
                self.assertEqual(info["commit"], COMMIT)

    def test_missing_git_is_unknown(self) -> None:
        self.assertEqual(
            self.info(FakeGit(missing=True)), {"commit": "", "branch": "", "dirty": "unknown"}
        )

    def test_status_waits_a_minute(self) -> None:
        git = FakeGit()
        self.info(git)
        self.assertEqual(git.timeouts["status"], 60)


class GitProvenanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = self.root / "runs" / "r1"
        self.archive = self.run_dir / "provenance"

    def provenance(self, git: FakeGit) -> dict[str, str]:
        with git.patch():
            info: dict[str, str] = results.git_provenance(self.root, self.run_dir)
        return info

    def test_a_dirty_tree_archives_what_git_reported(self) -> None:
        info = self.provenance(FakeGit())
        self.assertEqual((self.archive / "worktree.status").read_text(), STATUS)
        self.assertEqual((self.archive / "worktree.diff").read_text(), DIFF)
        self.assertEqual(info["diff_archive"], "runs/r1/provenance/worktree.diff")
        self.assertEqual(info["dirty_files"], "1")

    def test_a_clean_or_unknown_tree_archives_nothing(self) -> None:
        for git in (FakeGit(status=""), FakeGit(timing_out=("status",))):
            with self.subTest(status=git.status, timing_out=git.timing_out):
                info = self.provenance(git)
                self.assertNotIn("diff_archive", info)
                self.assertFalse(self.archive.exists())

    def test_a_failing_diff_archives_nothing(self) -> None:
        info = self.provenance(FakeGit(failing=("diff",)))
        self.assertEqual(info["dirty"], "true")
        self.assertEqual(info["diff_archive"], "")
        self.assertFalse((self.archive / "worktree.diff").exists())


class RepoIdentityTest(unittest.TestCase):
    def identity(self, git: FakeGit) -> tuple[str | None, bool | None]:
        with git.patch():
            identity: tuple[str | None, bool | None] = repo_identity(Path("/checkout"))
        return identity

    def test_the_commit_survives_a_status_git_does_not_answer(self) -> None:
        self.assertEqual(self.identity(FakeGit(timing_out=("status",))), (COMMIT, None))
        self.assertEqual(self.identity(FakeGit(failing=("status",))), (COMMIT, None))

    def test_a_clean_dirty_and_unreadable_checkout(self) -> None:
        self.assertEqual(self.identity(FakeGit(status="")), (COMMIT, False))
        self.assertEqual(self.identity(FakeGit()), (COMMIT, True))
        self.assertEqual(self.identity(FakeGit(failing=("rev-parse",))), (None, True))
        self.assertEqual(self.identity(FakeGit(missing=True)), (None, None))


class VerifyCheckoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for marker in ("Bender.yml", "pyproject.toml"):
            (self.root / marker).write_text("", encoding="utf-8")
        self.data = {"repo_root": str(self.root), "repo_commit": COMMIT}

    def test_a_commit_git_cannot_read_is_reported(self) -> None:
        out = io.StringIO()
        with mock.patch.object(worker, "repo_identity", return_value=(None, None)):
            with redirect_stdout(out):
                self.assertEqual(worker.verify_checkout(self.data), self.root)
        self.assertIn("not checked", out.getvalue())
        self.assertIn(COMMIT[:12], out.getvalue())

    def test_another_commit_is_refused(self) -> None:
        with mock.patch.object(worker, "repo_identity", return_value=("2" * 40, False)):
            with self.assertRaisesRegex(worker.WorkerError, "manifest was planned at"):
                worker.verify_checkout(self.data)


if __name__ == "__main__":
    unittest.main()
