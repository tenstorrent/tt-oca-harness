# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_docs  # noqa: E402

REPO_DOC = Path(__file__).resolve().parents[3] / "doc"


class StampTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def book(self, name, text):
        (self.tmp / name).mkdir()
        (self.tmp / name / "antora.yml").write_text(text)

    def test_sets_the_tag_version_on_every_book(self):
        self.book("trm", "name: ocah-docs\nversion: latest\nstart_page: index.adoc\n")
        self.book("home", "name: ocah-home\nversion: latest\n")
        release_docs.stamp("v0.5.0", self.tmp)
        for name in ("trm", "home"):
            text = (self.tmp / name / "antora.yml").read_text()
            self.assertIn("version: '0.5.0'\n", text)
            self.assertNotIn("latest", text)

    def test_rejects_a_book_without_the_latest_version(self):
        self.book("trm", "name: ocah-docs\nversion: '0.4.0'\n")
        with self.assertRaises(SystemExit):
            release_docs.stamp("v0.5.0", self.tmp)

    def test_rejects_tags_that_cannot_name_a_directory(self):
        self.book("trm", "version: latest\n")
        for tag in ("../x", "a/b", "latest", ""):
            with self.subTest(tag=tag), self.assertRaises(SystemExit):
                release_docs.stamp(tag, self.tmp)

    def test_every_repository_book_can_be_stamped(self):
        books = sorted(REPO_DOC.glob("*/antora.yml"))
        self.assertTrue(books)
        for book in books:
            with self.subTest(book=book.parent.name):
                self.assertRegex(book.read_text(), release_docs.VERSION_LINE)


class VersionTests(unittest.TestCase):
    def test_drops_only_a_leading_v_before_a_digit(self):
        self.assertEqual(release_docs.version_of("v0.5.0"), "0.5.0")
        self.assertEqual(release_docs.version_of("0.5.0"), "0.5.0")
        self.assertEqual(release_docs.version_of("vendor-1"), "vendor-1")


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.site = self.tmp / "site"
        self.site.mkdir()
        (self.site / "index.html").write_text("latest")
        snapshot = self.tmp / "snapshot"
        snapshot.mkdir()
        (snapshot / "index.html").write_text("frozen")
        (snapshot / "ocah-home").mkdir()
        (snapshot / "ocah-home" / "page.html").write_text("page")
        self.assets = self.tmp / "assets"
        self.assets.mkdir()
        for tag in ("v0.6.0", "v0.5.0"):
            release_docs.pack(snapshot, self.assets / release_docs.asset_name(tag))

    def fake_gh(self, *args):
        self.assertEqual(args[:2], ("release", "download"))
        tag, asset, dest = args[2], args[4], Path(args[6])
        self.assertEqual(asset, release_docs.asset_name(tag))
        shutil.copy(self.assets / asset, dest / asset)
        return ""

    def test_unpacks_each_snapshot_and_lists_versions_newest_first(self):
        available = [
            {"tag": "v0.6.0", "assets": ["docs-v0.6.0.tar.gz"]},
            {"tag": "v0.5.1", "assets": ["firmware.bin"]},
            {"tag": "v0.5.0", "assets": ["docs-v0.5.0.tar.gz", "firmware.bin"]},
        ]
        with mock.patch.object(release_docs, "gh", side_effect=self.fake_gh):
            versions = release_docs.restore(self.site, available)

        self.assertEqual(
            versions,
            [
                {"version": "latest", "path": ""},
                {"version": "0.6.0", "path": "v0.6.0/"},
                {"version": "0.5.0", "path": "v0.5.0/"},
            ],
        )
        self.assertEqual(json.loads((self.site / "versions.json").read_text()), versions)
        self.assertEqual((self.site / "index.html").read_text(), "latest")
        self.assertEqual((self.site / "v0.5.0" / "index.html").read_text(), "frozen")
        self.assertEqual((self.site / "v0.5.0" / "ocah-home" / "page.html").read_text(), "page")
        self.assertFalse((self.site / "v0.5.1").exists())

    def test_without_releases_lists_only_latest(self):
        versions = release_docs.restore(self.site, [])
        self.assertEqual(versions, [{"version": "latest", "path": ""}])

    def test_replaces_a_previously_restored_snapshot(self):
        (self.site / "v0.5.0").mkdir()
        (self.site / "v0.5.0" / "stale.html").write_text("stale")
        available = [{"tag": "v0.5.0", "assets": ["docs-v0.5.0.tar.gz"]}]
        with mock.patch.object(release_docs, "gh", side_effect=self.fake_gh):
            release_docs.restore(self.site, available)
        self.assertFalse((self.site / "v0.5.0" / "stale.html").exists())
        self.assertEqual((self.site / "v0.5.0" / "index.html").read_text(), "frozen")


class PackTests(unittest.TestCase):
    def test_refuses_a_directory_without_a_built_site(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            release_docs.pack(Path(tmp), Path(tmp) / "out.tar.gz")


if __name__ == "__main__":
    unittest.main()
