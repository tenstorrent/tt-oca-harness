# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the pinned UVM library fetch: cache reuse, digest checks, the
OCAH_UVM_HOME override, and the archive members the unpack refuses.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import hashlib
import io
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import uvm_library  # noqa: E402
from runlib.models import ConfigError  # noqa: E402
from runlib.uvm_library import fetch_uvm_library, uvm_library_src  # noqa: E402

RELEASE = {
    "1800.2-2020.3.2/LICENSE.txt": "Apache License\n",
    "1800.2-2020.3.2/src/uvm_pkg.sv": "package uvm_pkg;\nendpackage\n",
    "1800.2-2020.3.2/src/dpi/uvm_dpi.cc": "// dpi\n",
}


def write_archive(path: Path, members: dict[str, str]) -> str:
    """A gzip tar of ``members`` at ``path``; its SHA-256 comes back."""
    with tarfile.open(path, "w:gz") as tar:
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@mock.patch.dict(os.environ, {"OCAH_UVM_HOME": ""})
class FetchUvmLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "checkout"
        self.root.mkdir()
        self.messages: list[str] = []

    def pin(self, members: dict[str, str] = RELEASE, sha256: str | None = None) -> dict:
        archive = self.tmp / "release.gz"
        digest = write_archive(archive, members)
        return {"uvm_library": {"url": archive.as_uri(), "sha256": sha256 or digest}}

    def fetch(self, build: dict) -> Path:
        return fetch_uvm_library(self.root, build, "fixture", say=self.messages.append)

    def test_fetch_unpacks_the_release_as_a_uvm_home(self):
        build = self.pin()
        src = self.fetch(build)
        digest = build["uvm_library"]["sha256"]
        self.assertEqual(src, self.root / "local" / "uvm" / digest[:16] / "src")
        self.assertTrue((src / "uvm_pkg.sv").is_file())
        self.assertTrue((src.parent / "LICENSE.txt").is_file())
        self.assertEqual(sorted(path.name for path in src.parent.parent.iterdir()), [digest[:16]])
        self.assertEqual(uvm_library_src(self.root, build, "fixture"), src)

    def test_a_fetched_library_is_reused_without_the_archive(self):
        build = self.pin()
        first = self.fetch(build)
        (self.tmp / "release.gz").unlink()
        self.assertEqual(self.fetch(build), first)
        self.assertEqual(len(self.messages), 1)

    def test_a_digest_mismatch_leaves_no_cache_entry(self):
        build = self.pin(sha256="0" * 64)
        with self.assertRaisesRegex(ConfigError, "has SHA-256"):
            self.fetch(build)
        self.assertEqual(list((self.root / "local" / "uvm").iterdir()), [])

    def test_an_unreachable_archive_names_the_override(self):
        build = {"uvm_library": {"url": (self.tmp / "absent.gz").as_uri(), "sha256": "0" * 64}}
        with self.assertRaisesRegex(ConfigError, "OCAH_UVM_HOME names a UVM home"):
            self.fetch(build)

    def test_an_archive_member_outside_the_target_is_refused(self):
        build = self.pin({**RELEASE, "../outside.txt": "escaped\n"})
        with self.assertRaisesRegex(ConfigError, "cannot unpack"):
            self.fetch(build)
        self.assertEqual(list((self.root / "local" / "uvm").iterdir()), [])

    def test_an_archive_without_uvm_pkg_is_refused(self):
        build = self.pin({"1800.2-2020.3.2/README.md": "readme\n"})
        with self.assertRaisesRegex(ConfigError, "no src/uvm_pkg.sv at its top"):
            self.fetch(build)

    def test_a_concurrent_fetch_keeps_the_copy_already_in_place(self):
        build = self.pin()
        home = self.root / "local" / "uvm" / build["uvm_library"]["sha256"][:16]
        real_home_in = uvm_library._home_in

        def other_fetch_lands_first(*args):
            (home / "src").mkdir(parents=True)
            (home / "src" / "uvm_pkg.sv").write_text("// first\n")
            return real_home_in(*args)

        with mock.patch.object(uvm_library, "_home_in", side_effect=other_fetch_lands_first):
            src = self.fetch(build)
        self.assertEqual((src / "uvm_pkg.sv").read_text(), "// first\n")

    def test_the_override_names_the_home_and_skips_the_fetch(self):
        home = self.tmp / "site-uvm"
        (home / "src").mkdir(parents=True)
        (home / "src" / "uvm_pkg.sv").write_text("// site\n")
        build = {"uvm_library": {"url": "https://unreachable.invalid/uvm.gz", "sha256": "0" * 64}}
        with mock.patch.dict(os.environ, {"OCAH_UVM_HOME": str(home)}):
            self.assertEqual(self.fetch(build), home / "src")
            (home / "src" / "uvm_pkg.sv").unlink()
            with self.assertRaisesRegex(ConfigError, "OCAH_UVM_HOME=.* has no src/uvm_pkg.sv"):
                self.fetch(build)
        self.assertEqual(self.messages, [])

    def test_resolving_an_unfetched_library_says_how_to_get_it(self):
        build = self.pin()
        with self.assertRaisesRegex(ConfigError, "not fetched into local/uvm/"):
            uvm_library_src(self.root, build, "fixture")
        src = uvm_library_src(self.root, build, "fixture", present=False)
        self.assertFalse(src.exists())

    def test_the_pin_is_validated(self):
        cases = [
            ({}, r"needs \[build.uvm_library\]"),
            ({"uvm_library": {"url": "u", "sha256": "0" * 64, "rev": "x"}}, "unknown keys: rev"),
            ({"uvm_library": {"sha256": "0" * 64}}, r"\.url is required"),
            ({"uvm_library": {"url": "u", "sha256": "ABC"}}, "64 lowercase hexadecimal"),
        ]
        for build, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ConfigError, message):
                uvm_library_src(self.root, build, "fixture", present=False)


if __name__ == "__main__":
    unittest.main()
