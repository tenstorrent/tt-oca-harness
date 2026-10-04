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


def published(*tags, without=()):
    return [
        {"tag": t, "assets": [] if t in without else [release_docs.asset_name(t)]} for t in tags
    ]


class StampTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def book(self, name, text):
        (self.tmp / name).mkdir()
        (self.tmp / name / "antora.yml").write_text(text)

    def test_versions_every_book_by_series_and_shows_the_release(self):
        self.book("trm", "name: ocah-docs\nversion: latest\nstart_page: index.adoc\n")
        self.book("home", "name: ocah-home\nversion: latest\n")
        release_docs.stamp("v0.5.2", self.tmp)
        for name in ("trm", "home"):
            text = (self.tmp / name / "antora.yml").read_text()
            self.assertIn("version: '0.5'\ndisplay_version: '0.5.2'\n", text)
            self.assertNotIn("latest", text)

    def test_rejects_a_book_without_the_latest_version(self):
        self.book("trm", "name: ocah-docs\nversion: '0.4'\n")
        with self.assertRaises(SystemExit):
            release_docs.stamp("v0.5.0", self.tmp)

    def test_rejects_tags_that_are_not_releases(self):
        self.book("trm", "version: latest\n")
        for tag in ("../x", "latest", "", "v0.5", "v0.5.0-rc1", "v01.2.3"):
            with self.subTest(tag=tag), self.assertRaises(SystemExit):
                release_docs.stamp(tag, self.tmp)

    def test_every_repository_book_can_be_stamped(self):
        books = sorted(REPO_DOC.glob("*/antora.yml"))
        self.assertTrue(books)
        for book in books:
            with self.subTest(book=book.parent.name):
                self.assertRegex(book.read_text(), release_docs.VERSION_LINE)


class NamingTests(unittest.TestCase):
    def test_a_release_is_served_from_its_minor_series(self):
        self.assertEqual(release_docs.site_dir("v0.5.2"), "v0.5")
        self.assertEqual(release_docs.site_dir("1.10.0"), "v1.10")
        self.assertEqual(release_docs.display("v0.5.2"), "0.5.2")


class SelectTests(unittest.TestCase):
    def test_keeps_the_newest_patch_of_the_newest_series(self):
        available = published("v0.4.0", "v0.5.1", "v0.4.3", "v0.5.0", "v0.3.9", "v0.5.2")
        self.assertEqual(release_docs.select(available, keep=2), ["v0.5.2", "v0.4.3"])

    def test_orders_by_version_not_by_publication(self):
        # A hotfix to an older series published after a newer release.
        available = published("v0.4.4", "v0.6.0", "v0.5.0")
        self.assertEqual(release_docs.select(available, keep=2), ["v0.6.0", "v0.5.0"])

    def test_falls_back_to_the_previous_patch_without_a_snapshot(self):
        available = published("v0.5.2", "v0.5.1", without=("v0.5.2",))
        self.assertEqual(release_docs.select(available, keep=2), ["v0.5.1"])


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.site = self.tmp / "site"
        self.site.mkdir()
        (self.site / "index.html").write_text("latest")
        self.assets = self.tmp / "assets"
        self.assets.mkdir()
        for tag in ("v0.6.0", "v0.5.1", "v0.5.0", "v0.4.0"):
            snapshot = self.tmp / tag
            (snapshot / "ocah-home").mkdir(parents=True)
            (snapshot / "index.html").write_text(tag)
            (snapshot / "ocah-home" / "page.html").write_text("page")
            release_docs.pack(snapshot, self.assets / release_docs.asset_name(tag))

    def fake_gh(self, *args):
        self.assertEqual(args[:2], ("release", "download"))
        tag, asset, dest = args[2], args[4], Path(args[6])
        self.assertEqual(asset, release_docs.asset_name(tag))
        shutil.copy(self.assets / asset, dest / asset)
        return ""

    def restore(self, available, keep=2):
        with mock.patch.object(release_docs, "gh", side_effect=self.fake_gh):
            return release_docs.restore(self.site, available, keep)

    def test_serves_each_kept_series_and_lists_it(self):
        versions = self.restore(published("v0.6.0", "v0.5.1", "v0.5.0", "v0.4.0"))
        self.assertEqual(
            versions,
            [
                {"version": "latest", "path": ""},
                {"version": "0.6.0", "path": "v0.6/"},
                {"version": "0.5.1", "path": "v0.5/"},
            ],
        )
        self.assertEqual(json.loads((self.site / "versions.json").read_text()), versions)
        self.assertEqual((self.site / "index.html").read_text(), "latest")
        self.assertEqual((self.site / "v0.5" / "index.html").read_text(), "v0.5.1")
        self.assertEqual((self.site / "v0.5" / "ocah-home" / "page.html").read_text(), "page")
        self.assertFalse((self.site / "v0.4").exists())

    def test_without_releases_lists_only_latest(self):
        self.assertEqual(self.restore([]), [{"version": "latest", "path": ""}])

    def test_replaces_a_previously_restored_snapshot(self):
        (self.site / "v0.5").mkdir()
        (self.site / "v0.5" / "stale.html").write_text("stale")
        self.restore(published("v0.5.1"))
        self.assertFalse((self.site / "v0.5" / "stale.html").exists())
        self.assertEqual((self.site / "v0.5" / "index.html").read_text(), "v0.5.1")


class PackTests(unittest.TestCase):
    def test_refuses_a_directory_without_a_built_site(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            release_docs.pack(Path(tmp), Path(tmp) / "out.tar.gz")


if __name__ == "__main__":
    unittest.main()
