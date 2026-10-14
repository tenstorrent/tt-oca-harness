# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the `clean` stage: the paths it removes and the paths it refuses.

Every case runs against a scratch checkout, and `/` only in a dry run, so a refusal that
stops working removes scratch files and nothing else.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.config import validate_stage_table  # noqa: E402
from runlib.models import ConfigError  # noqa: E402
from runlib.stages import clean_stage  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def checked_in_clean_stages() -> list[tuple[Path, dict]]:
    stages = []
    for path in sorted((REPO_ROOT / "hw").rglob("*_cfg.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        table = data.get("native", {}).get("stages", {}).get("clean")
        if isinstance(table, dict):
            stages.append((path, table))
    return stages


class CleanStageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.root = self.sandbox / "checkout"
        self.home = self.sandbox / "home"
        self.run_dir = self.root / "build" / "runs" / "r1"
        self.kept = [
            self.root / ".git" / "HEAD",
            self.root / "src" / "top.sv",
            self.run_dir / "result.json",
            self.home / ".profile",
            self.sandbox / "elsewhere" / "data",
        ]
        for path in self.kept:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        home = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        home.start()
        self.addCleanup(home.stop)

    def clean(self, *paths: str, run_dir: Path | None = None, dry_run: bool = False) -> None:
        ctx = {
            "item": "",
            "run_dir": str(run_dir or self.run_dir),
            "repo_root": str(self.root),
        }
        clean_stage({"kind": "clean", "paths": list(paths)}, self.root, ctx, dry_run)

    def assert_refused(self, *paths: str, dry_run: bool = False) -> str:
        with self.assertRaises(ConfigError) as caught:
            self.clean(*paths, dry_run=dry_run)
        for path in self.kept:
            self.assertTrue(path.is_file(), f"{path} was removed")
        return str(caught.exception)

    def test_an_entry_that_renders_empty_is_refused(self) -> None:
        for value in ("", "  ", "{item}"):
            with self.subTest(value=value):
                self.assertIn("empty", self.assert_refused(value))

    def test_the_checkout_and_the_directories_above_it_are_refused(self) -> None:
        for value in (".", "..", "src/..", "{repo_root}", str(self.sandbox)):
            with self.subTest(value=value):
                self.assertIn(str(self.root), self.assert_refused(value))

    def test_the_git_directory_and_the_home_directory_are_refused(self) -> None:
        for value in (".git", "~", str(self.home)):
            with self.subTest(value=value):
                self.assert_refused(value)

    def test_the_filesystem_root_is_refused(self) -> None:
        self.assert_refused("/", dry_run=True)

    def test_a_path_outside_the_checkout_and_the_run_directory_is_refused(self) -> None:
        message = self.assert_refused(str(self.sandbox / "elsewhere"))
        self.assertIn("outside the checkout and the run directory", message)

    def test_one_refused_entry_stops_the_whole_list(self) -> None:
        self.assert_refused("build", "")

    def test_a_dry_run_refuses_what_a_run_refuses(self) -> None:
        for value in ("", ".", "~", str(self.sandbox / "elsewhere")):
            with self.subTest(value=value):
                self.assert_refused(value, dry_run=True)

    def test_the_run_directory_and_checkout_paths_are_removed(self) -> None:
        run_dir = self.sandbox / "runs" / "r2"
        (run_dir / "logs").mkdir(parents=True)
        (self.root / "build" / "out.log").write_text("x\n", encoding="utf-8")
        self.clean("{run_dir}", "build/out.log", "build/missing", run_dir=run_dir)
        self.assertFalse(run_dir.exists())
        self.assertFalse((self.root / "build" / "out.log").exists())
        self.assertTrue((self.root / "src" / "top.sv").is_file())

    def test_a_symbolic_link_is_removed_as_the_link(self) -> None:
        link = self.run_dir.parent / "latest"
        link.symlink_to(self.run_dir.name)
        self.clean("build/runs/latest")
        self.assertFalse(link.is_symlink())
        self.assertTrue((self.run_dir / "result.json").is_file())

    def test_a_link_to_the_checkout_is_refused(self) -> None:
        link = self.root / "build" / "up"
        link.symlink_to(self.root)
        self.assert_refused("build/up")
        self.assertTrue(link.is_symlink())

    def test_a_dry_run_lists_the_plan_and_removes_nothing(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            self.clean("{run_dir}", "build/missing", dry_run=True)
        self.assertEqual(
            out.getvalue().splitlines(),
            [f"REMOVE: {self.run_dir}", f"REMOVE: {self.root / 'build' / 'missing'}"],
        )
        self.assertTrue((self.run_dir / "result.json").is_file())

    def test_every_checked_in_clean_stage_passes(self) -> None:
        stages = checked_in_clean_stages()
        self.assertTrue(stages)
        for path, table in stages:
            with self.subTest(config=str(path.relative_to(REPO_ROOT))):
                validate_stage_table("clean", table, str(path))
                with redirect_stdout(io.StringIO()):
                    self.clean(*table["paths"], dry_run=True)


class CleanStageValidationTest(unittest.TestCase):
    def test_paths_must_be_non_empty(self) -> None:
        for value in ("", "  "):
            with self.subTest(value=value):
                with self.assertRaises(ConfigError) as caught:
                    validate_stage_table("clean", {"kind": "clean", "paths": [value]}, "cfg")
                self.assertIn("paths[0]", str(caught.exception))

    def test_paths_cannot_use_item(self) -> None:
        with self.assertRaises(ConfigError) as caught:
            validate_stage_table(
                "clean", {"kind": "clean", "paths": ["{run_dir}", "build/{item}"]}, "cfg"
            )
        self.assertIn("paths[1]", str(caught.exception))
        self.assertIn("{item}", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
