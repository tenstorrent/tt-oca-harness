# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the UVM library: the checked-in release tree, the configured home and the
OCAH_UVM_HOME override, the tree digest, and the record.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import os
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.models import ConfigError  # noqa: E402
from runlib.uvm_library import resolve_uvm_library, uvm_tree_sha256  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILE = REPO_ROOT / "hw" / "common" / "dv" / "configs" / "profiles" / "native.toml"
RELEASE = {
    "src/uvm_pkg.sv": "package uvm_pkg;\nendpackage\n",
    "src/dpi/uvm_dpi.cc": "// dpi\n",
}


def write_home(home: Path, members: dict[str, str] = RELEASE) -> Path:
    """A UVM home holding ``members`` at ``home``; ``home`` comes back."""
    for name, text in members.items():
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return home


@mock.patch.dict(os.environ, {"OCAH_UVM_HOME": ""})
class ResolveUvmLibrary(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "checkout"
        self.home = write_home(self.root / "uvm")
        self.build = {"uvm_library": "uvm"}

    def test_the_profile_names_a_release_tree_with_its_licence(self):
        build = tomllib.loads(PROFILE.read_text())["frameworks"]["uvm"]["build"]
        library = resolve_uvm_library(REPO_ROOT, build, "native", digest=False)
        self.assertEqual(library.source, "config")
        for name in ("LICENSE.txt", "NOTICE.txt"):
            self.assertTrue((library.src.parent / name).is_file(), name)

    def test_the_configured_home_resolves_against_the_checkout(self):
        library = resolve_uvm_library(self.root, self.build, "fixture")
        self.assertEqual((library.src, library.source), (self.home / "src", "config"))
        self.assertEqual(library.tree_sha256, uvm_tree_sha256(self.home / "src"))
        absolute = resolve_uvm_library(self.tmp, {"uvm_library": str(self.home)}, "fixture")
        self.assertEqual(absolute.src, self.home / "src")

    def test_digest_false_skips_the_read(self):
        library = resolve_uvm_library(self.root, self.build, "fixture", digest=False)
        self.assertEqual(library.tree_sha256, "")

    def test_a_home_without_uvm_pkg_is_refused(self):
        (self.home / "src" / "uvm_pkg.sv").unlink()
        with self.assertRaisesRegex(ConfigError, r"\[build\]\.uvm_library uvm has no src/uvm_pkg"):
            resolve_uvm_library(self.root, self.build, "fixture")
        with self.assertRaisesRegex(ConfigError, r"needs \[build\]\.uvm_library"):
            resolve_uvm_library(self.root, {}, "fixture")

    def test_the_override_wins_over_the_configured_home(self):
        shell = write_home(self.tmp / "shell-uvm", {"src/uvm_pkg.sv": "// 1.2\n"})
        with mock.patch.dict(os.environ, {"OCAH_UVM_HOME": str(shell)}):
            library = resolve_uvm_library(self.root, {}, "fixture")
            self.assertEqual((library.src, library.source), (shell / "src", "OCAH_UVM_HOME"))
            (shell / "src" / "uvm_pkg.sv").unlink()
            with self.assertRaisesRegex(ConfigError, "OCAH_UVM_HOME=.* has no src/uvm_pkg.sv"):
                resolve_uvm_library(self.root, self.build, "fixture")

    def test_the_record_names_the_source_the_home_and_the_digest(self):
        library = resolve_uvm_library(self.root, self.build, "fixture")
        expected = {"source": "config", "home": "uvm", "tree_sha256": library.tree_sha256}
        self.assertEqual(library.record(self.root), expected)
        shell = write_home(self.tmp / "shell-uvm")
        with mock.patch.dict(os.environ, {"OCAH_UVM_HOME": str(shell)}):
            override = resolve_uvm_library(self.root, self.build, "fixture")
        self.assertEqual(override.record(self.root)["home"], str(shell))

    def test_the_tree_digest_follows_content_not_location(self):
        trees = [write_home(self.tmp / name) / "src" for name in ("a", "b")]
        self.assertEqual(uvm_tree_sha256(trees[0]), uvm_tree_sha256(trees[1]))
        (trees[1] / "dpi" / "uvm_dpi.cc").write_text("// edited\n")
        self.assertNotEqual(uvm_tree_sha256(trees[0]), uvm_tree_sha256(trees[1]))


if __name__ == "__main__":
    unittest.main()
