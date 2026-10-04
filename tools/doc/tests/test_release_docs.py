# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_docs  # noqa: E402


def published(*tags, without=()):
    return [
        {"tag": t, "assets": [] if t in without else [release_docs.asset_name(t)]} for t in tags
    ]


class ReleaseDocsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_stamps_every_repository_book_by_series(self):
        doc = self.tmp / "doc"
        for book in (release_docs.ROOT / "doc").glob("*/antora.yml"):
            (doc / book.parent.name).mkdir(parents=True)
            shutil.copy(book, doc / book.parent.name)
        release_docs.stamp("v0.5.2", doc)
        for book in doc.glob("*/antora.yml"):
            self.assertIn("version: '0.5'\ndisplay_version: '0.5.2'\n", book.read_text())
        with self.assertRaises(SystemExit):
            release_docs.stamp("v0.5.3", doc)

    def test_rejects_tags_that_are_not_releases(self):
        for tag in ("../x", "latest", "v0.5", "v0.5.0-rc1", "v01.2.3"):
            with self.subTest(tag=tag), self.assertRaises(SystemExit):
                release_docs.site_dir(tag)

    def test_selects_the_newest_patch_of_the_newest_series_by_version(self):
        available = published("v0.4.4", "v0.6.0", "v0.5.1", "v0.5.2", "foo", without=("v0.5.2",))
        self.assertEqual(release_docs.select(available), ["v0.6.0", "v0.5.1"])

    def test_restores_each_snapshot_and_lists_it(self):
        site, assets = self.tmp / "site", self.tmp / "assets"
        (site / "v0.5").mkdir(parents=True)
        (site / "v0.5" / "stale.html").write_text("stale")
        (assets / "built").mkdir(parents=True)
        (assets / "built" / "index.html").write_text("frozen")
        release_docs.pack(assets / "built", assets / "docs-v0.5.1.tar.gz")

        versions = release_docs.restore(
            site, ["v0.5.1"], lambda tag, dest: shutil.copy(assets / f"docs-{tag}.tar.gz", dest)
        )

        self.assertEqual(
            versions, [{"version": "latest", "path": ""}, {"version": "0.5.1", "path": "v0.5/"}]
        )
        self.assertEqual(json.loads((site / "versions.json").read_text()), versions)
        self.assertEqual((site / "v0.5" / "index.html").read_text(), "frozen")
        self.assertFalse((site / "v0.5" / "stale.html").exists())


if __name__ == "__main__":
    unittest.main()
