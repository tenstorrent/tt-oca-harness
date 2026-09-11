<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Validation contract for the incoming team

Read the repository README, CONTRIBUTING.md and tools/docker/README.md for the
recipient's tool setup. Original machine caches and absolute paths are not
prerequisites. Configure a valid, sufficiently large scratch directory according
to repository/environment instructions. Use an isolated execution checkout, with
independent reviewer builds in another checkout at the submitted commit.

## Proven release build modes

The following reproduces the established modes with `antora` and
`asciidoctor-pdf` installed on PATH and their dependencies available. Substitute
the locally configured executable locations if needed. These are translations
of commands already exercised on the source revision, not a claim that the new
machine has its toolchain installed. Record actual tool versions.

From the repository root, execute each command separately and retain its stdout,
stderr and immediate exit code. Do not hide failure behind a pipe.

```bash
export OCAH_DOC_REGEN_REGS=0
export OCAH_DOC_RELEASE=1

make -f ocah.mk ocah-doc-trm-setup ocah-doc-integrator-setup \
  ocah-doc-programmer-setup ocah-doc-appnotes-setup \
  ocah-doc-contributing-setup ocah-doc-home-setup

antora generate --clean --attribute release \
  --attribute "basedir=$PWD/doc/trm" --log-failure-level error antora-trm-playbook.yml

antora generate --clean --attribute release \
  --log-failure-level error antora-playbook.yml

make -f ocah.mk ocah-doc-trm-pdf OCAH_ASCIIDOCTOR_PDF=asciidoctor-pdf
```

Keep `OCAH_DOC_REGEN_REGS=0` and `OCAH_DOC_RELEASE=1` on setup/build steps.
The renderer itself needs `--attribute release`: staging alone is insufficient.
Missing six-product staging previously produced cross-component errors; the
fully staged combined site has a zero-error baseline. Do not weaken the Antora
error gate or relabel new failures as inherited.

Outputs:

- TRM HTML: `doc/trm/_build/html_antora/ocah-docs/latest/`
- Combined HTML: `doc/_build/html_antora/`
- TRM PDF: `doc/trm/dist/ocah-trm.pdf`

Copy the fresh PDF into the task's artifact directory and preserve its source SHA
and checksum. The tracked PDF is not an authorized implementation change. Check
all generated working-tree changes separately; do not commit staging/register output.
Do not reset or clean another person's checkout to obtain clean status.

## Rendered checks

Check `dtp/overview.html` and `ip/jtag_ptap/doc/index.html` in both the standalone
TRM and combined `ocah-integrator-guide/latest/` consumer. A source-usage search
must identify other affected consumers. All six combined products currently
receive copies of these assets; check those copies remain correct.

Inspect actual published pages, not just bare SVGs, at 1440/1280/1024/768/390 CSS px.
At 1280 and 100%, measure actual image placement width and effective font sizes.
Desktop main labels need 14 px, essential labels 12 px. Check full glyph extents,
text containment, endpoint/label association, line styles and directions. Ensure
the image viewer opens/closes and preserves expected keyboard/focus behavior;
wide content must not collide with Contents or cause page-wide overflow.

Native 200% browser zoom is an explicit final appearance check. A device-scale
factor, enlarged screenshot or resized viewport alone does not demonstrate it.
On small screens require a useful overview and accessible enlargement, without
pretending every technical label is readable at the desktop floor at 390 px.

The current DTP and PTAP figures are on physical PDF pages 21 and 31 respectively,
in a 635-page document. Rediscover page locations after changes; do not blindly
measure the old page numbers. Rasterize those pages and inspect at normal page size.
For native-size extraction use explicit scaling, for example:

```bash
pdftohtml -f 21 -l 21 -zoom 1 -xml -hidden doc/trm/dist/ocah-trm.pdf dtp-page.xml
pdftohtml -f 31 -l 31 -zoom 1 -xml -hidden doc/trm/dist/ocah-trm.pdf ptap-page.xml
```

Zoom-1 font sizes are integer-rounded. An independent zoom-3 extraction divided
by three provides a useful cross-check. Include every essential font family,
including Courier port labels. Missing extraction must fail or be unknown, never
pass at Infinity. Inspect rendered glyphs: prior Unicode arrows became logical
negation signs despite passing font-size checks.

## Source, behavior and ownership preservation

- Verify the complete cumulative and incremental diff against recorded SHAs.
  Only the current task's permitted source paths may change. The separately
  introduced transfer records are coordinator-owned and are not a relaxation
  of implementation scope.
- Preserve all 14 DTP compatibility routes/anchors and the full 77-row port
  reference. Preserve accepted navigation, image viewer and table containment.
- Verify AUTHORING, STRUCTURE, DV defines and internal release-history content
  are absent from published output, including direct URLs, not just navigation.
- Follow one canonical authored source for HTML and PDF. Staged Antora files
  are disposable, never the place to implement fixes.
- An independent reviewer inspects the actual rendered artifacts and source
  meaning. A successful build or a geometry pass count is not appearance acceptance.
- For broader UI changes or source consumers, rerun relevant sibling products.
  Earlier standalone IG HTML had four inherited cross-component errors; the
  combined fully staged site passes. Earlier IG PDF had 67 pages and an inherited
  memory-map annotation. Those are branch-specific baselines, not certification
  of the separate IG PRs or any future integration onto main.

After an implementation handoff, report branch/base/full HEAD, complete changed
paths, initial/final status, current content mapping, exact commands and immediate
exits, raw logs, tool versions, matched HTML/PDF, screenshot/page locations,
checksums and honest gaps. The coordinator records acceptance or a bounded
correction before assigning the next task's exact base.
