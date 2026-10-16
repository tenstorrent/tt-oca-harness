# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the pinned UVM library: the fetch and its cache, the archive and tree digest
checks, the site file's mirror, archive and home, the OCAH_UVM_HOME override, the record, and
the archive members the unpack refuses.

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
from runlib.uvm_library import (  # noqa: E402
    fetch_uvm_library,
    resolve_uvm_library,
    uvm_tree_sha256,
)

RELEASE = {
    "1800.2-2020.3.2/LICENSE.txt": "Apache License\n",
    "1800.2-2020.3.2/src/uvm_pkg.sv": "package uvm_pkg;\nendpackage\n",
    "1800.2-2020.3.2/src/dpi/uvm_dpi.cc": "// dpi\n",
}
UNREACHABLE = "https://unreachable.invalid/uvm.gz"


def write_archive(path: Path, members: dict[str, str]) -> str:
    """A gzip tar of ``members`` at ``path``; its SHA-256 comes back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_home(home: Path, members: dict[str, str]) -> Path:
    """The release members unpacked as a UVM home at ``home``; ``home`` comes back."""
    for name, text in members.items():
        path = home / name.split("/", 1)[1]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return home


@mock.patch.dict(os.environ, {"OCAH_UVM_HOME": ""})
class UvmLibraryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "checkout"
        self.root.mkdir()
        self.messages: list[str] = []
        self.warnings: list[str] = []
        self.release_tree = uvm_tree_sha256(write_home(self.tmp / "reference", RELEASE) / "src")

    def archive(self, members: dict[str, str] = RELEASE, name: str = "release.gz") -> Path:
        path = self.tmp / name
        write_archive(path, members)
        return path

    def mirror(self, name: str) -> Path:
        """A copy of the pinned archive at ``name``: what a mirror or a local copy holds."""
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.tmp / "release.gz", path)
        return path

    def pin(self, url: str | None = None, **digests: str) -> dict:
        """A build table pinning RELEASE; ``url`` replaces the archive's own location."""
        archive = self.archive()
        table = {
            "url": url or archive.as_uri(),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "tree_sha256": self.release_tree,
        }
        table.update(digests)
        return {"uvm_library": table}

    def fetch(self, build: dict, site: dict | None = None) -> uvm_library.UvmLibrary:
        return fetch_uvm_library(
            self.root,
            build,
            "fixture",
            site=site,
            say=self.messages.append,
            warn=self.warnings.append,
        )

    def cache(self, build: dict) -> Path:
        return self.root / "local" / "uvm" / str(build["uvm_library"]["sha256"])[:16]


class FetchUvmLibrary(UvmLibraryCase):
    def test_fetch_unpacks_the_release_as_a_uvm_home(self):
        build = self.pin()
        library = self.fetch(build)
        self.assertEqual(library.src, self.cache(build) / "src")
        self.assertEqual((library.source, library.tree_sha256), ("archive", self.release_tree))
        self.assertFalse(library.unpinned)
        self.assertTrue((library.src.parent / "LICENSE.txt").is_file())
        entries = [path.name for path in self.cache(build).parent.iterdir()]
        self.assertEqual(entries, [self.cache(build).name])
        self.assertEqual(resolve_uvm_library(self.root, build, "fixture"), library)

    def test_a_fetched_library_is_reused_without_the_archive(self):
        build = self.pin()
        first = self.fetch(build)
        (self.tmp / "release.gz").unlink()
        self.assertEqual(self.fetch(build), first)
        self.assertEqual(len(self.messages), 1)

    def test_a_repack_of_the_pinned_tree_is_used_with_a_warning(self):
        build = self.pin(sha256="0" * 64)
        library = self.fetch(build)
        self.assertEqual((library.source, library.tree_sha256), ("archive", self.release_tree))
        self.assertEqual(library.src, self.cache(build) / "src")
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("not the pinned " + "0" * 64, self.warnings[0])
        self.assertIn("unpacks to the pinned src tree", self.warnings[0])

    def test_an_archive_that_matches_neither_digest_leaves_no_cache_entry(self):
        build = self.pin(sha256="0" * 64, tree_sha256="1" * 64)
        with self.assertRaisesRegex(
            ConfigError, "unpacks to a src tree .* the archive has SHA-256 .* where sha256 pins"
        ):
            self.fetch(build)
        self.assertEqual(list((self.root / "local" / "uvm").iterdir()), [])
        self.assertEqual(self.warnings, [])

    def test_a_tree_digest_mismatch_leaves_no_cache_entry(self):
        build = self.pin(tree_sha256="0" * 64)
        with self.assertRaises(ConfigError) as ctx:
            self.fetch(build)
        self.assertRegex(str(ctx.exception), f"unpacks to a src tree .* {self.release_tree}")
        self.assertNotIn("the archive has SHA-256", str(ctx.exception))
        self.assertEqual(list((self.root / "local" / "uvm").iterdir()), [])

    def test_an_edited_cache_entry_is_refused(self):
        build = self.pin()
        library = self.fetch(build)
        (library.src / "uvm_pkg.sv").write_text("// edited\n")
        with self.assertRaisesRegex(ConfigError, "holds a src tree .* move it aside"):
            resolve_uvm_library(self.root, build, "fixture")
        unread = resolve_uvm_library(self.root, build, "fixture", verify=False)
        self.assertEqual(unread.tree_sha256, "")

    def test_an_unreachable_archive_names_every_route(self):
        build = self.pin(url=(self.tmp / "absent.gz").as_uri())
        with self.assertRaisesRegex(
            ConfigError, r"site file's \[uvm_library\] names .* OCAH_UVM_HOME names a UVM home"
        ):
            self.fetch(build)

    def test_an_archive_member_outside_the_target_is_refused(self):
        archive = self.archive({**RELEASE, "../outside.txt": "escaped\n"}, "escape.gz")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        build = self.pin(url=archive.as_uri(), sha256=digest)
        with self.assertRaisesRegex(ConfigError, "cannot unpack"):
            self.fetch(build)
        self.assertEqual(list((self.root / "local" / "uvm").iterdir()), [])

    def test_an_archive_without_uvm_pkg_is_refused(self):
        archive = self.archive({"1800.2-2020.3.2/README.md": "readme\n"}, "bare.gz")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        build = self.pin(url=archive.as_uri(), sha256=digest)
        with self.assertRaisesRegex(ConfigError, "no src/uvm_pkg.sv at its top"):
            self.fetch(build)

    def test_a_concurrent_fetch_keeps_the_copy_already_in_place(self):
        build = self.pin()
        home = self.cache(build)
        real_home_in = uvm_library._home_in

        def other_fetch_lands_first(*args):
            candidate = real_home_in(*args)
            shutil.copytree(candidate, home)
            (home / "landed-first").write_text("\n")
            return candidate

        with mock.patch.object(uvm_library, "_home_in", side_effect=other_fetch_lands_first):
            library = self.fetch(build)
        self.assertTrue((library.src.parent / "landed-first").is_file())


class SiteUvmLibrary(UvmLibraryCase):
    def test_a_site_archive_fills_the_cache_without_the_pinned_url(self):
        build = self.pin(url=UNREACHABLE)
        local = self.mirror("mirror/release.gz")
        library = self.fetch(build, {"archive": str(local)})
        self.assertEqual((library.source, library.src), ("archive", self.cache(build) / "src"))
        self.assertEqual(self.messages, [f"fetching the UVM library from {local.as_uri()}"])

    def test_a_site_mirror_replaces_the_pinned_url(self):
        build = self.pin(url=UNREACHABLE)
        mirror = self.mirror("mirror.gz").as_uri()
        self.assertEqual(self.fetch(build, {"url": mirror}).tree_sha256, self.release_tree)
        self.assertEqual(self.messages, [f"fetching the UVM library from {mirror}"])

    def test_a_site_archive_of_another_release_is_refused(self):
        build = self.pin(url=UNREACHABLE)
        other = self.archive({**RELEASE, "1800.2-2020.3.2/src/extra.sv": "// x\n"}, "other.gz")
        with self.assertRaisesRegex(ConfigError, f"{other.as_uri()} unpacks to a src tree"):
            self.fetch(build, {"archive": str(other)})

    def test_a_site_home_is_checked_against_the_tree_pin(self):
        build = self.pin(url=UNREACHABLE)
        home = write_home(self.tmp / "installed", RELEASE)
        library = self.fetch(build, {"home": str(home)})
        self.assertEqual((library.source, library.src), ("site", home / "src"))
        self.assertEqual(self.messages, [])
        (home / "src" / "uvm_pkg.sv").write_text("// another release\n")
        with self.assertRaisesRegex(ConfigError, r"\[uvm_library\]\.home .* holds a src tree"):
            self.fetch(build, {"home": str(home)})
        (home / "src" / "uvm_pkg.sv").unlink()
        with self.assertRaisesRegex(ConfigError, r"\.home .* has no src/uvm_pkg.sv"):
            self.fetch(build, {"home": str(home)})


class UvmHomeOverride(UvmLibraryCase):
    def test_the_override_wins_and_skips_the_fetch(self):
        build = self.pin(url=UNREACHABLE)
        home = write_home(self.tmp / "shell-uvm", RELEASE)
        site_home = write_home(self.tmp / "site-uvm", RELEASE)
        with mock.patch.dict(os.environ, {"OCAH_UVM_HOME": str(home)}):
            library = self.fetch(build, {"home": str(site_home)})
        self.assertEqual((library.source, library.src), ("OCAH_UVM_HOME", home / "src"))
        self.assertFalse(library.unpinned)
        self.assertEqual(self.messages, [])

    def test_an_override_of_another_release_is_reported_not_refused(self):
        build = self.pin(url=UNREACHABLE)
        home = write_home(self.tmp / "shell-uvm", {**RELEASE, "x/src/uvm_pkg.sv": "// 1.2\n"})
        with mock.patch.dict(os.environ, {"OCAH_UVM_HOME": str(home)}):
            library = self.fetch(build)
            self.assertTrue(library.unpinned)
            self.assertEqual(library.pin, self.release_tree)
            (home / "src" / "uvm_pkg.sv").unlink()
            with self.assertRaisesRegex(ConfigError, "OCAH_UVM_HOME=.* has no src/uvm_pkg.sv"):
                self.fetch(build)


class ResolveUvmLibrary(UvmLibraryCase):
    def test_resolving_an_unfetched_library_says_how_to_get_it(self):
        build = self.pin()
        with self.assertRaisesRegex(ConfigError, "not fetched into local/uvm/"):
            resolve_uvm_library(self.root, build, "fixture")
        library = resolve_uvm_library(self.root, build, "fixture", present=False)
        self.assertFalse(library.src.exists())
        self.assertEqual(library.tree_sha256, "")

    def test_the_record_names_the_source_the_home_and_the_digest(self):
        build = self.pin()
        library = self.fetch(build)
        expected = {
            "source": "archive",
            "home": f"local/uvm/{self.cache(build).name}",
            "tree_sha256": self.release_tree,
        }
        self.assertEqual(library.record(self.root), expected)
        outside = write_home(self.tmp / "installed", RELEASE)
        site = resolve_uvm_library(self.root, build, "fixture", site={"home": str(outside)})
        self.assertEqual(site.record(self.root)["home"], str(outside))

    def test_the_tree_digest_follows_content_not_location(self):
        trees = [write_home(self.tmp / name, RELEASE) / "src" for name in ("a", "b")]
        self.assertEqual(uvm_tree_sha256(trees[0]), uvm_tree_sha256(trees[1]))
        (trees[1] / "dpi" / "uvm_dpi.cc").write_text("// edited\n")
        self.assertNotEqual(uvm_tree_sha256(trees[0]), uvm_tree_sha256(trees[1]))

    def test_the_pin_is_validated(self):
        digest = "0" * 64
        full = {"url": "u", "sha256": digest, "tree_sha256": digest}
        cases = [
            ({}, r"needs \[build.uvm_library\]"),
            ({"uvm_library": {**full, "rev": "x"}}, "unknown keys: rev"),
            ({"uvm_library": {"sha256": digest, "tree_sha256": digest}}, r"\.url is required"),
            ({"uvm_library": {**full, "sha256": "ABC"}}, r"\.sha256 must be 64 lowercase"),
            ({"uvm_library": {"url": "u", "sha256": digest}}, r"\.tree_sha256 must be 64"),
        ]
        for build, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ConfigError, message):
                resolve_uvm_library(self.root, build, "fixture", present=False)


if __name__ == "__main__":
    unittest.main()
