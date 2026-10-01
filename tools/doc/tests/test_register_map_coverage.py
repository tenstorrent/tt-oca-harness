# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ASCIIDOCTOR = shutil.which(os.environ.get("ASCIIDOCTOR", "asciidoctor"))
EXTENSION = Path(__file__).resolve().parents[1] / "register_map_coverage.rb"


@unittest.skipUnless(ASCIIDOCTOR, "asciidoctor is required")
class RegisterMapCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.maps = [self.root / name for name in ("first.adoc", "second.adoc")]
        for path in self.maps:
            path.write_text(
                "== Address Map: example\n\n=== CTRL\n\nControl fields.\n\n"
                "=== STATUS\n\nStatus fields.\n"
            )
        self.manifest = self.root / "maps.txt"
        self.manifest.write_text("\n".join(map(str, self.maps)) + "\n")

    def convert(self, body, toc_depth=5, outline_depth=5):
        source = self.root / "book.adoc"
        source.write_text("= Register Reference\n:doctype: book\n\n" + body)
        return subprocess.run(
            [
                ASCIIDOCTOR,
                "-r",
                str(EXTENSION),
                "-a",
                f"register-map-manifest={self.manifest}",
                "-a",
                "toc",
                "-a",
                f"toclevels={toc_depth}",
                "-a",
                f"outlinelevels={outline_depth}",
                "-o",
                str(self.root / "book.html"),
                str(source),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_accepts_all_maps_with_the_same_title(self):
        result = self.convert("include::first.adoc[]\n\ninclude::second.adoc[]\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_missing_map_despite_identical_title(self):
        result = self.convert("include::first.adoc[]\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing or incomplete register map:", result.stderr)
        self.assertIn(str(self.maps[1]), result.stderr)

    def test_rejects_map_excluded_by_backend(self):
        result = self.convert(
            "include::first.adoc[]\n\n"
            "ifdef::backend-pdf[]\ninclude::second.adoc[]\nendif::backend-pdf[]\n"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(self.maps[1]), result.stderr)

    def test_rejects_map_with_omitted_register(self):
        result = self.convert("include::first.adoc[]\n\ninclude::second.adoc[lines=1..5]\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing or incomplete register map:", result.stderr)

    def test_rejects_contents_and_bookmark_depth_limits(self):
        for toc_depth, outline_depth in ((1, 5), (5, 1)):
            with self.subTest(toc_depth=toc_depth, outline_depth=outline_depth):
                result = self.convert(
                    "include::first.adoc[]\n\ninclude::second.adoc[]\n",
                    toc_depth,
                    outline_depth,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exceeds contents/bookmark depth", result.stderr)

    def test_rejects_empty_inventory(self):
        self.manifest.write_text("")
        result = self.convert("include::first.adoc[]\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Register map manifest is empty", result.stderr)


if __name__ == "__main__":
    unittest.main()
