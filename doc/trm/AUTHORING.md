<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# OCAH TRM Authoring Guide

This guide covers conventions for adding or changing a TRM topic so it works
correctly in both the Antora web site and the asciidoctor-pdf book.

This is a separate customer maintenance handover document. Do not stage it
as a TRM web page, add it to public navigation, or include it in the TRM PDF.

---

## 1. Source locations

Canonical authored content lives beside the hardware:

| Content type | Canonical location |
|---|---|
| Subsystem chapters | `hw/sys/<sys>/doc/` |
| IP block chapters | `hw/ip/<family>/<ip>/doc/` |
| Platform/assembly pages | `doc/trm/src/` |
| Discrepancy log, meta tables | `doc/trm/meta/` |

`doc/stage-docs.sh` copies these into the gitignored `doc/trm/modules/` tree.
Do not edit staged copies — they are overwritten on every setup run. Generated
register partials (`hw/<...>/regs/gen/`) are also staged and must not be
hand-edited; they are outputs of the SystemRDL toolchain.

---

## 2. Pages, partials and assembly

| Kind | Location | `= Title`? | Published standalone? |
|---|---|---|---|
| **Page** | `modules/<mod>/pages/` | Required | Yes — becomes a URL |
| **Partial** | `modules/<mod>/partials/` | Forbidden | No |
| **Assembly** | `doc/trm/src/index.adoc` | Yes (doc title) | Both web and PDF root |

**Pages** must have `= Title` as the first non-comment, non-attribute line —
Antora uses it for the HTML `<title>` and `<h1>`. A page without it appears as
"Untitled". **Partials** must not have `= Title`; a partial placed in `pages/`
by mistake creates an "Untitled" standalone URL.

`doc/trm/src/index.adoc` serves both backends: staged to `ROOT/pages/` and
published as the web landing page; also the top-level `asciidoctor-pdf` input
that includes subsystem chapters via `leveloffset`.

`doc/stage-docs.sh` copies files from `hw/sys/<sys>/doc/` to `<sys>/pages/`
via `stage_adoc_tree`, which copies **all** `.adoc` files recursively. Files
intended as partials or DV content must be explicitly excluded or placed in a
directory not covered by `stage_adoc_tree`.

---

## 3. Chapter opening

Every chapter (subsystem or IP block) starts with:

1. **Purpose** — one short paragraph explaining what the block does.
2. **Capabilities** — a brief list of key features or scope.
3. **Block diagram** — at full column width, with a caption and meaningful alt text.
4. **Reading route** — brief prose or a list pointing through the chapter's main
   sections, with backend-guarded cross-page links (see §6).

Omit sections that genuinely do not apply; do not add empty placeholders.

---

## 4. Heading depth and PDF assembly

Write page headings starting at `==`; `=` is the page title and must not
appear in the body. The PDF assembly includes full pages with `leveloffset`
to promote `= Title` to the correct chapter or section depth:

```adoc
// Assembly file location: doc/trm/src/index.adoc
// hw/sys/smu/doc/index.adoc: = Title → == (chapter), == body → ===
include::../../../hw/sys/smu/doc/index.adoc[leveloffset=+1]

// hw/ip/jtag/jtag_ptap/doc/index.adoc: = Title → === (section), == body → ====
include::../../../hw/ip/jtag/jtag_ptap/doc/index.adoc[leveloffset=+2]
```

Use full-page includes with explicit `leveloffset` as the chosen convention.
Body tags select content; they do not adjust heading levels by themselves.
The full-page pattern keeps each title in one maintained source.

Private fragments have no `= Title`. Their owning page supplies the section
heading; any fragment subheadings sit below it. Stage fragments to `partials/`,
never to `pages/`.

---

## 5. Stable anchors and compatibility

Place an explicit anchor before every section a reader might link to:

```adoc
[[smu-axi-crossbar]]
== AXI Crossbar
```

Use kebab-case IDs prefixed with the subsystem or IP name (`smu-`, `dtp-`,
`sep-`, `smc-`). Anchor IDs are public URLs; do not rename them once published.

When a section moves to a new page, the **old page** must keep the old anchor
and add an onward link. The new page carries the authoritative content. In the
PDF assembly, guard the old compatibility anchor with `ifdef::backend-html5[]`
so the assembled book contains only one destination with that ID:

```adoc
// In old page (e.g., architecture.adoc) — HTML only:
ifdef::backend-html5[]
[[smu-axi-crossbar]]
_The SMU AXI Crossbar section has moved._
See xref:smu:index.adoc#smu-axi-crossbar[SMU AXI Crossbar].
endif::backend-html5[]
```

The new page carries `[[smu-axi-crossbar]]` without the guard.

---

## 6. Links and cross-references

Cross-page `xref:` links — including same-module links (`xref:jtag.adoc[]`) —
become external file annotations in the PDF pointing to nonexistent `.pdf` files.
Wrap every cross-page reference in backend conditionals. The same pattern covers
partial includes whose paths differ between backends:

```adoc
// Cross-page link
ifdef::backend-html5[]
See xref:smu:index.adoc#smu-axi-crossbar[SMU AXI Crossbar].
endif::backend-html5[]
ifdef::backend-pdf[]
See <<smu-axi-crossbar,SMU AXI Crossbar>>.
endif::backend-pdf[]

// Partial include (path relative to canonical source file for PDF)
ifdef::backend-pdf[]
include::crossbar-table.adoc[]
endif::backend-pdf[]
ifdef::backend-html5[]
include::partial$crossbar-table.adoc[]
endif::backend-html5[]
```

`<<anchor,text>>` resolves to any named destination in the assembled PDF.
To verify link destinations, check the actual target HTML file for the `id=`
attribute, or run `pdfinfo -dests` to list PDF named destinations. Do not
treat a zero-warning Antora log as link validation — it confirms xref syntax
but does not verify anchor existence on the target page.

External web URLs in body text are fine in both backends. `pdfinfo -url` checks
for unintended per-page file annotations (`.pdf` destinations), not external URLs.

---

## 7. Figures, tables and register documentation

Write a caption and descriptive alt text for every figure. Source images live at
`hw/sys/<sys>/doc/assets/` or `hw/ip/<family>/<ip>/doc/assets/`; the staging
script copies them to `modules/<mod>/assets/images/`. Do not commit staged
images. Use explicit column widths in tables (`[cols="20%,15%,65%"]`) to
prevent mid-word wrapping in the PDF. Page size and margins are set by the
production theme (`doc/theme.yml`); do not prescribe them in page source files.

### 7a. Image viewer

Block diagrams inside `.doc .imageblock` that are not already linked and are not
logos or icons are automatically enhanced with a zoom/pan viewer. JavaScript
wraps the image in a keyboard-operable button; clicking or pressing Enter/Space
opens a modal overlay.

**Eligibility rules** (implemented in `doc/ui-supplemental/js/image-viewer.js`):

- Image must be inside `.doc .imageblock` (AsciiDoc `image::` block macro).
- Image must **not** be wrapped in an `<a>` (i.e., no `link=` attribute on
  the `image::` macro).
- Image must **not** be inside `.navbar`, `.footer` or `.home-panel`.

**Controls** — toolbar buttons and keyboard shortcuts:

| Action | Button | Keyboard |
|---|---|---|
| Zoom in | `+` button | `+` or `=` |
| Zoom out | `−` button | `-` |
| Fit to screen | `⤢` button | `0` |
| Pan left/right/up/down | `◀ ▶ ▲ ▼` buttons | Arrow keys |
| Open original in new tab | `↗` button | — |
| Close | `✕` button | Escape |

**Fit behaviour**: Fit scales the image to fill the available stage regardless
of how small that ratio is (e.g. wide diagrams at narrow mobile viewports).
Zooming beyond fit is always available up to 8×. Fit resets pan to centre.

**Light backing**: The viewer applies a white background to the image element
so that SVG and PNG diagrams with transparent backgrounds remain readable; the
dark panel surround is unchanged.

**Modal isolation**: While the viewer is open, all background content is made
inert so keyboard focus cannot leave the modal. Site shortcuts (`n`/`N`/`j`/`k`
and search) are suppressed until the viewer closes; prior inert states are
restored exactly.

**Accessible names**: The trigger button is labelled "View enlarged: <caption>"
when a figure caption is present, or "View enlarged: <alt text>" for uncaptioned
figures.

Do not add `link=` to block diagrams that should be viewer-eligible. If an image
should open a specific URL instead of the viewer, add `link=<url>` to the image
macro; the viewer will skip it automatically.

The viewer is purely presentational HTML — captions, alt text and the image
itself render normally when JavaScript is unavailable.

### 7b. Wide tables with local horizontal scroll

Tables whose content overflows the article width at some viewport sizes should
use a passthrough HTML scroll wrapper in the HTML backend only, following this
pattern (see PTAP `architecture.adoc` for a worked example):

```adoc
ifdef::backend-html5[]
++++
<div class="ptap-module-hierarchy-scroll" tabindex="0" aria-label="Table description, scrollable">
++++
endif::backend-html5[]

[.ptap-module-hierarchy,width="100%",cols="<30%,<45%,<25%",options="header"]
|===
| ...
|===

ifdef::backend-html5[]
++++
</div>
++++
endif::backend-html5[]
```

The role class (e.g. `.ptap-module-hierarchy`) must have a matching CSS rule in
`extra.css` that sets `overflow-wrap: anywhere` on cells and `table-layout: auto`
on the table. The scroll wrapper class (e.g. `.ptap-module-hierarchy-scroll`)
must have `overflow-x: auto` in `extra.css`. The `tabindex="0"` on the wrapper
makes the scroll area keyboard-operable.

The PDF backend sees none of the passthrough HTML and uses the column widths
from the table attribute block directly.

Generated register documentation comes from SystemRDL (`.rdl`) sources. PDF
includes use `hw/<...>/regs/gen/adoc/`; HTML includes use staged partials from
`hw/<...>/regs/gen/html/`. Do not copy field descriptions into prose and do not
edit generated files — they are overwritten on every regen.

Hardware operating requirements, power-on sequencing and register programming
sequences needed to operate the hardware belong in the TRM. Driver recipes and
OS-level flows belong in the Programmer's Guide.

---

## 8. Verification checklist

**HTML** (`OCAH_DOC_REGEN_REGS=0 OCAH_DOC_RELEASE=1 make -f ocah.mk ocah-doc-trm-setup`, then Antora with `--attribute release --log-failure-level error`):

- [ ] Page `<h1>` matches the `= Title` line.
- [ ] `<title>` element is the meaningful page title, not "Untitled".
- [ ] Nav sidebar shows this page nested at the correct depth.
- [ ] `xref:` links resolve — verify `id=` attribute on actual target HTML page.
- [ ] Figures render; no broken image or SVG fallback text.
- [ ] Page appears exactly once in the site.

**PDF** (`make -f ocah.mk ocah-doc-trm-pdf` or equivalent with `-a release`):

- [ ] Section appears in TOC at the correct level (part → chapter → section).
- [ ] `<<anchor,text>>` references resolve — check `pdfinfo -dests` for the target name.
- [ ] No unintended per-page file annotations: `pdfinfo -url` shows no `*.pdf` destinations.
- [ ] Figure renders; no SVG fallback text.
