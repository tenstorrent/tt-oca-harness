# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for update_vendor_uvm: the release listing, the archive gate, the update, the
check, and the checked-in package.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import hashlib
import io
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import update_vendor_uvm as vendor  # noqa: E402
from update_vendor_uvm import UpdateError  # noqa: E402

PAGE = """
<table>
  <tr><td><a href="/images/downloads/standards/uvm/1800.2-2020.3.2%20Release.gz">
    UVM v2020.3.2 Library Code for IEEE 1800.2</a></td></tr>
  <tr><td><a href="/images/downloads/standards/uvm/UVM-18002-2020-11tar.gz">UVM v2020.1.1
    Library Code for IEEE 1800.2</a></td></tr>
  <tr><td><a href="/images/downloads/standards/uvm/UVM-18002-2017-11tar.gz">
    UVM 2017 v1.1 Library Code for IEEE 1800.2</a></td></tr>
  <tr><td><a href="/images/downloads/standards/uvm/uvm-1.2.tar.gz">Class Library Code</a></td></tr>
  <tr><td><a href="/images/downloads/standards/uvm/VIP_1.0.pdf">VIP_1.0</a></td></tr>
</table>
"""
BASE = "https://www.accellera.org/images/downloads/standards/uvm/"
LICENSE = "                Apache License\n          Version 2.0, January 2004\n\n   TERMS\n"
RELEASE = {
    "src/uvm_pkg.sv": "package uvm_pkg;\nendpackage\n",
    "src/dpi/uvm_dpi.cc": "// dpi\n",
    "LICENSE.txt": LICENSE,
    "NOTICE.txt": "Portions developed by Accellera.\n",
    "README.md": "# UVM\n",
    "docs/index.html": "<html></html>\n",
    "CONTRIBUTING.md": "# Contributing\n",
}
KEPT_PATHS = ("src/uvm_pkg.sv", "src/dpi/uvm_dpi.cc", "LICENSE.txt", "NOTICE.txt", "README.md")
KEPT = {path: RELEASE[path].encode() for path in KEPT_PATHS}


def archive(members: dict[str, str] = RELEASE, top: str = "1800.2-2020.3.2", **links: str) -> bytes:
    """A gzipped tar of ``members`` below ``top``; ``links`` adds symbolic links by path."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.addfile(_directory(top))
        for path, text in members.items():
            info = tarfile.TarInfo(f"{top}/{path}")
            info.size = len(text.encode())
            tar.addfile(info, io.BytesIO(text.encode()))
        for path, target in links.items():
            info = tarfile.TarInfo(f"{top}/{path}")
            info.type, info.linkname = tarfile.SYMTYPE, target
            tar.addfile(info)
    return buffer.getvalue()


def _directory(name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    return info


def two_tops() -> bytes:
    """A gzipped tar whose members sit below two top directories."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in ("a/src/uvm_pkg.sv", "b/LICENSE.txt"):
            tar.addfile(tarfile.TarInfo(name), io.BytesIO(b""))
    return buffer.getvalue()


class ListReleases(unittest.TestCase):
    def test_the_page_lists_only_ieee_1800_2_releases_newest_first(self):
        releases = vendor.list_releases(PAGE)
        self.assertEqual([r.name for r in releases], ["2020-3.2", "2020-1.1", "2017-1.1"])
        self.assertEqual(releases[0].url, BASE + "1800.2-2020.3.2%20Release.gz")

    def test_no_name_selects_the_newest_and_a_name_selects_that_release(self):
        releases = vendor.list_releases(PAGE)
        self.assertEqual(vendor.select_release(releases, None).name, "2020-3.2")
        self.assertEqual(
            vendor.select_release(releases, "2017-1.1").url, BASE + "UVM-18002-2017-11tar.gz"
        )

    def test_an_unlisted_release_is_refused_with_the_listed_ones(self):
        releases = vendor.list_releases(PAGE)
        with self.assertRaisesRegex(
            UpdateError, "no release 2020-9.9; it links 2020-3.2, 2020-1.1"
        ):
            vendor.select_release(releases, "2020-9.9")
        with self.assertRaisesRegex(UpdateError, "links no UVM release"):
            vendor.select_release(vendor.list_releases("<p>moved</p>"), None)

    def test_only_https_is_fetched(self):
        with self.assertRaisesRegex(UpdateError, "only an https URL"):
            vendor.fetch("http://www.accellera.org/downloads/standards/uvm")


class ReleaseMembers(unittest.TestCase):
    def test_upstream_keeps_src_and_the_licence_files(self):
        self.assertEqual(vendor.release_members(archive()), KEPT)
        self.assertEqual(vendor.release_members(archive(top="./1800.2-2020.3.2")), KEPT)

    def test_an_archive_that_is_not_apache_2_is_refused(self):
        with self.assertRaisesRegex(UpdateError, "LICENSE.txt is not the Apache License"):
            vendor.release_members(
                archive({**RELEASE, "LICENSE.txt": "GNU GENERAL PUBLIC LICENSE\n"})
            )
        without = {path: text for path, text in RELEASE.items() if path != "LICENSE.txt"}
        with self.assertRaisesRegex(UpdateError, "LICENSE.txt is not the Apache License"):
            vendor.release_members(archive(without))

    def test_an_archive_without_uvm_pkg_is_refused(self):
        without = {path: text for path, text in RELEASE.items() if path != "src/uvm_pkg.sv"}
        with self.assertRaisesRegex(UpdateError, "no src/uvm_pkg.sv"):
            vendor.release_members(archive(without))

    def test_a_member_outside_the_archive_or_a_link_is_refused(self):
        with self.assertRaisesRegex(UpdateError, "leaves the archive"):
            vendor.release_members(archive({**RELEASE, "../escape.sv": "x"}))
        with self.assertRaisesRegex(UpdateError, "is not a regular file"):
            vendor.release_members(archive(**{"src/link.svh": "/etc/passwd"}))
        with self.assertRaisesRegex(UpdateError, "2 top-level entries"):
            vendor.release_members(two_tops())
        with self.assertRaisesRegex(UpdateError, "not a tar archive"):
            vendor.release_members(b"<html>sign in</html>")


class UpdateAndCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.package = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.package, ignore_errors=True)
        self.archive = archive()
        self.served = {
            vendor.DOWNLOAD_PAGE: PAGE.encode(),
            BASE + "1800.2-2020.3.2%20Release.gz": self.archive,
        }
        patcher = mock.patch.object(vendor, "fetch", side_effect=lambda url: self.served[url])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_update_replaces_upstream_and_records_the_release(self):
        stale = self.package / "upstream" / "src" / "stale.svh"
        stale.parent.mkdir(parents=True)
        stale.write_text("// gone\n")
        release, count = vendor.update(self.package, None)
        self.assertEqual((release.name, count), ("2020-3.2", len(KEPT)))
        self.assertEqual(vendor.tree_files(self.package / "upstream"), KEPT)
        record = vendor.read_record(self.package)
        self.assertEqual(
            (record["release"], record["url"], record["sha256"]),
            ("2020-3.2", release.url, hashlib.sha256(self.archive).hexdigest()),
        )
        self.assertFalse((self.package / "upstream.new").exists())

    def test_a_refused_archive_leaves_upstream_alone(self):
        vendor.update(self.package, None)
        self.served[BASE + "1800.2-2020.3.2%20Release.gz"] = b"<html>sign in</html>"
        with self.assertRaises(UpdateError):
            vendor.update(self.package, None)
        self.assertEqual(vendor.tree_files(self.package / "upstream"), KEPT)

    def test_the_check_passes_on_the_written_tree_and_names_each_departure(self):
        vendor.update(self.package, None)
        self.assertEqual(vendor.check(self.package), [])
        upstream = self.package / "upstream"
        (upstream / "src" / "uvm_pkg.sv").write_text("// edited\n")
        (upstream / "src" / "dpi" / "uvm_dpi.cc").unlink()
        (upstream / "src" / "extra.svh").write_text("// extra\n")
        self.assertEqual(
            vendor.check(self.package),
            ["missing src/dpi/uvm_dpi.cc", "extra src/extra.svh", "differs src/uvm_pkg.sv"],
        )

    def test_the_check_fails_when_the_recorded_archive_changes(self):
        vendor.update(self.package, None)
        self.served[BASE + "1800.2-2020.3.2%20Release.gz"] = archive(RELEASE, top="other")
        [line] = vendor.check(self.package)
        self.assertIn("not the recorded", line)

    def test_a_missing_record_is_an_error(self):
        with self.assertRaisesRegex(UpdateError, "release.toml"):
            vendor.check(self.package)


class CheckedInPackage(unittest.TestCase):
    def test_the_record_names_a_release_and_its_archive(self):
        record = vendor.read_record(vendor.PACKAGE)
        self.assertRegex(record["release"], r"^\d{4}-\d+\.\d+$")
        self.assertTrue(record["url"].startswith("https://www.accellera.org/"))
        self.assertRegex(record["sha256"], r"^[0-9a-f]{64}$")

    def test_upstream_holds_only_what_the_update_keeps_under_apache_2(self):
        files = vendor.tree_files(vendor.PACKAGE / "upstream")
        self.assertEqual([path for path in files if not vendor.is_kept(path)], [])
        self.assertNotIn(None, files.values())
        self.assertIn("src/uvm_pkg.sv", files)
        self.assertIn("NOTICE.txt", files)
        self.assertTrue(vendor.is_apache_2(files["LICENSE.txt"].decode()))


if __name__ == "__main__":
    unittest.main()
