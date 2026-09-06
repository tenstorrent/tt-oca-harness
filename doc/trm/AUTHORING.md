<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# OCAH TRM Authoring Guide

This guide covers the conventions for adding or changing a TRM topic so it
works correctly in both the Antora web site and the asciidoctor-pdf book.
Read it before editing any chapter source.

Do not add this file to the Antora nav or the PDF assembly.

---

## 1. Source locations

Canonical authored content lives beside the hardware, not in the staged build tree:

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
by mistake becomes an "Untitled" standalone URL.

`doc/trm/src/index.adoc` is the document root for both backends: staged to
`ROOT/pages/` and published as the web landing page; also the top-level
`asciidoctor-pdf` input that includes subsystem chapters via `leveloffset`.

`doc/stage-docs.sh` copies files from `hw/sys/<sys>/doc/` to `<sys>/pages/`
via `stage_adoc_tree`, which copies **all** `.adoc` files recursively. Files
intended as partials or DV content must be explicitly excluded or placed in a
directory not covered by `stage_adoc_tree` — they cannot rely on being skipped
automatically.

---

## 3. Heading depth and PDF assembly

Write page headings starting at `==`; `=` is the page title and must not
appear in the body. The PDF assembly includes full pages with `leveloffset`
to promote `= Title` to the correct chapter or section depth:

```adoc
include::hw/sys/smu/doc/index.adoc[leveloffset=+1]     // = Title → ==
include::hw/ip/jtag/jtag_ptap/doc/index.adoc[leveloffset=+2]  // = Title → ===
```

Do not use `[tag=body]` to extract body content: it leaves `==` at absolute
document level and creates unintended top-level chapters in the PDF.

---

## 4. Stable anchors

Place an explicit anchor before every section a reader might link to:

```adoc
[[smu-axi-crossbar]]
== AXI Crossbar
```

Use kebab-case IDs prefixed with the subsystem or IP name (`smu-`, `dtp-`,
`sep-`, `smc-`). Anchor IDs are public URLs; do not rename them once published.
If a section moves to a different page, keep `[[old-id]]` at the top of the
new page as a compatibility entry so existing bookmark links still land.

---

## 5. Links, cross-references and includes

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

// Partial include
ifdef::backend-pdf[]
include::../partials/crossbar-table.adoc[]
endif::backend-pdf[]
ifdef::backend-html5[]
include::partial$crossbar-table.adoc[]
endif::backend-html5[]
```

`<<anchor,text>>` resolves to any named destination in the assembled PDF.
External web URLs in body text are fine in both backends. `pdfinfo -url` checks
for unintended per-page file annotations (`page.pdf`), not external URLs.

---

## 6. Figures and tables

```adoc
.DTP Architecture
image::dtp_arch.svg[DTP architecture: JIU with PTAP/STAPs and CTN with CTM/CTPs,scaledwidth=90%]
```

Write a caption and descriptive alt text. Source images live at
`hw/sys/<sys>/doc/assets/` or `hw/ip/<family>/<ip>/doc/assets/`; the staging
script copies them to `modules/<mod>/assets/images/`. Do not commit staged
images. Use explicit column widths in tables (`[cols="20%,15%,65%"]`) to
prevent mid-word wrapping in the PDF. Page size and margins are set by the
production theme (`doc/theme.yml`); do not prescribe them in page source files.

---

## 7. Register documentation and content boundaries

Generated register documentation comes from SystemRDL (`.rdl`) sources via the
register generator. PDF includes use `hw/<...>/regs/gen/adoc/`; HTML includes
use staged partials from `hw/<...>/regs/gen/html/`. Do not copy field
descriptions into prose; include or link to the generated output. Do not edit
generated files — they are overwritten on every regen. Presentation issues
(column widths, wrapping) belong to the generator template.

Hardware operating requirements, power-on sequencing, and register programming
sequences needed to operate the hardware belong in the TRM. Driver recipes and
OS-level flows belong in the Programmer's Guide.

---

## 8. Verification checklist

**HTML** (run `OCAH_DOC_RELEASE=1 make -f ocah.mk ocah-doc-trm-setup`, then Antora):

- [ ] Page `<h1>` matches the `= Title` line. Confirm via page source.
- [ ] `<title>` element is the meaningful page title, not "Untitled".
- [ ] Nav sidebar shows this page nested at the correct depth.
- [ ] `xref:` links resolve — Antora exits 0, no unresolved-xref warnings.
- [ ] Figures render; no broken image icon or SVG fallback text.
- [ ] Page appears exactly once (no accidental duplication via assembly include).

**PDF** (run `make -f ocah.mk ocah-doc-trm-pdf`, or equivalent with `-a release`):

- [ ] Section appears in TOC at the correct level (part → chapter → section).
- [ ] No duplicated headings from `= Title` appearing twice.
- [ ] `<<anchor,text>>` references resolve; no `[#id]` placeholder text.
- [ ] No unintended per-page file annotations: `pdfinfo -url <file>.pdf` must
  show no `*.pdf` destinations (external web URLs are acceptable).
- [ ] Figure renders correctly; no SVG fallback text visible.

Exact build commands and prototype evidence are in `doc/trm/STRUCTURE.md §7`.
