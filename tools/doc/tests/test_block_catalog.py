# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
ASCIIDOCTOR = shutil.which(os.environ.get("ASCIIDOCTOR", "asciidoctor"))
NODE = shutil.which("node")
SOURCE = """= Catalog fixture
:doctype: book
:block-catalog:
:ocah-trm:
:xrefstyle: short

[[list-of-figures]]
[preface]
== List of Figures

[[list-of-tables]]
[preface]
== List of Tables

== Interface & Control

[[fixed-figure]]
[caption=""]
.Figure 99. Existing caption
image::first.svg[First figure]

image::second.svg[Second figure]

[[trm-table-1]]
A reserved identifier.

[cols="1,1",options="header"]
|===
|Bits |Field
|0 |ENABLE
|===

See <<fixed-figure>>.
"""


class BlockCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def convert(self, backend, source=SOURCE):
        source_path = self.root / "source.adoc"
        source_path.write_text(source)
        output = self.root / "output.html"
        if backend == "ruby":
            if not ASCIIDOCTOR:
                self.skipTest("asciidoctor is required")
            command = [
                ASCIIDOCTOR,
                "-r",
                str(TOOLS / "block_catalog.rb"),
                "-o",
                str(output),
                str(source_path),
            ]
        else:
            if not NODE:
                self.skipTest("node and @asciidoctor/core are required")
            script = self.root / "convert.cjs"
            script.write_text("""
const fs = require('node:fs')
const asciidoctor = require('@asciidoctor/core')()
const registry = asciidoctor.Extensions.create()
const file = {asciidoc: {attributes: {}}}
require(process.argv[2]).register(registry, {file})
const doc = asciidoctor.load(fs.readFileSync(process.argv[3], 'utf8'), {extension_registry: registry})
fs.writeFileSync(process.argv[4], doc.convert())
console.log(JSON.stringify(file.blockCatalog || []))
""")
            command = [
                NODE,
                str(script),
                str(TOOLS / "block-captions.js"),
                str(source_path),
                str(output),
            ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return output.read_text(), result.stdout

    def test_caption_sequence_and_existing_anchor(self):
        for backend in ("ruby", "javascript"):
            with self.subTest(backend=backend):
                html, _ = self.convert(backend)
                self.assertIn("Figure 1. Existing caption", html)
                self.assertIn("Figure 2. Second figure", html)
                self.assertNotIn("Figure 99", html)
                self.assertIn('href="#fixed-figure">Figure 1</a>', html)
                self.assertIn("Table 1. Interface &amp; Control fields", html)
                self.assertNotIn("&amp;amp;", html)
                self.assertEqual(html.count('id="trm-table-1"'), 1)
                self.assertIn('id="trm-table-1-block"', html)

    def test_pdf_lists_link_to_every_block(self):
        html, _ = self.convert("ruby")
        index = html.split('<h2 id="_interface')[0]
        for target, label in (
            ("fixed-figure", "Figure 1"),
            ("trm-figure-2", "Figure 2"),
            ("trm-table-1-block", "Table 1"),
        ):
            self.assertIn(f'href="#{target}">{label}.', index)

    def test_html_reference_fragments_encode_special_characters(self):
        for attributes, fragment in (
            ('[id="control%20port"]', "control%2520port"),
            (
                "[id='figure\"onmouseover=\"alert(1)']",
                "figure%22onmouseover%3D%22alert(1)",
            ),
            ('[id="figure&<>\'/Δ?"]', "figure%26%3C%3E'%2F%CE%94%3F"),
        ):
            with self.subTest(attributes=attributes):
                source = f"= Fixture\n:ocah-trm:\n\n{attributes}\nimage::figure.svg[Figure]\n"
                html, _ = self.convert("javascript", source)
                self.assertIn(
                    '<p class="block-references">Figures and tables: '
                    f'<a href="#{fragment}">Figure 1</a>.</p>',
                    html,
                )

    def test_opt_in_leaves_other_books_unchanged(self):
        source = SOURCE.replace(":block-catalog:\n", "").replace(":ocah-trm:\n", "")
        for backend in ("ruby", "javascript"):
            with self.subTest(backend=backend):
                html, _ = self.convert(backend, source)
                self.assertNotIn("Figures and tables:", html)
                self.assertNotIn("trm-figure-2", html)
                self.assertIn("Figure 99. Existing caption", html)

    def test_html_catalog_includes_generated_register_tables(self):
        source = (
            SOURCE
            + """
++++
<div class="ocah-reg-html">
<h2>Address Map: example</h2>
<table><tr><th>Address</th><th>Name</th></tr><tr><td>0</td><td>CTRL</td></tr></table>
<h3 id="CTRL">CTRL</h3>
<table><tr><th>Bits</th><th>Field</th></tr><tr><td>0</td><td>ENABLE</td></tr></table>
</div>
++++
"""
        )
        html, catalog = self.convert("javascript", source)
        entries = json.loads(catalog)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[-2]["title"], "Address Map: example register list")
        self.assertEqual(entries[-1]["title"], "example.CTRL fields")
        self.assertEqual(entries[-1]["label"], "Table 3")
        self.assertIn("<td>0</td><td>ENABLE</td>", html)
        self.assertEqual(html.count("<caption"), 3)

    def test_repeated_includes_receive_distinct_destinations(self):
        (self.root / "shared.adoc").write_text("image::shared.svg[Shared image]\n")
        source = SOURCE + "\ninclude::shared.adoc[]\n\ninclude::shared.adoc[]\n"
        # Ruby resolves includes from the source path; JS's string API needs basedir.
        html, _ = self.convert("ruby", source)
        self.assertIn('id="trm-figure-3"', html)
        self.assertIn('id="trm-figure-4"', html)
        self.assertIn('href="#trm-figure-4">Figure 4. Shared image</a>', html)


if __name__ == "__main__":
    unittest.main()
