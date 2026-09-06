<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# OCAH TRM Authoring Guide

This guide explains how to add or change a TRM topic so it works consistently in both the Antora web site and the asciidoctor-pdf book. Read it before editing any chapter source.

Do not add this file to the Antora nav or the PDF assembly.

---

## 1. Chapter opening

Every chapter (subsystem or IP block) starts with:

1. **Purpose** — one short paragraph explaining what the block does and why a reader is here.
2. **Scope / capabilities** — a brief list of key capabilities. Do not enumerate every section heading; give enough for a reader to decide whether to keep reading.
3. **A readable block diagram** — the architecture figure goes here, at full column width, with a descriptive caption and meaningful alt text. See §5.
4. **A reading route** — brief prose or a list pointing through the chapter's main sections. In HTML output, this may link to sibling pages. See §4 for how to guard those links.

You may omit sections that genuinely do not apply; do not add empty placeholder sections.

---

## 2. Pages, partials and assembly

The TRM uses three kinds of source file. Keep them distinct.

| Kind | Location | Has `= Title`? | Published standalone? |
|---|---|---|---|
| **Page** | `modules/<mod>/pages/` | Yes — mandatory | Yes, by Antora |
| **Partial (fragment)** | `modules/<mod>/partials/` | No — forbidden | No |
| **Assembly** | `doc/trm/src/index.adoc` / `book.adoc` | Yes (document title) | No (PDF only) |

**Pages** are the unit of web navigation. Every file in `pages/` becomes a URL. The `= Title` line (first non-comment, non-attribute line) is required; Antora uses it for the HTML `<title>` element. A page without it shows as "Untitled" in browser tabs and search results.

**Partials** hold shared prose, tables, or register includes that are reused across pages or pulled into the PDF assembly. They live in `partials/` and must not have a `= Title` line. A partial placed in `pages/` by mistake becomes an "Untitled" standalone URL.

**Assemblies** are not web pages. The PDF assembly (`doc/trm/src/index.adoc`) includes subsystem chapters via `leveloffset` includes — see §3. The staging script (`doc/stage-docs.sh`) copies source pages and partials into the gitignored `modules/` tree; treat that tree as build output, not source.

Source files live beside the hardware: `hw/sys/<sys>/doc/` for subsystems, `hw/ip/<ip>/doc/` for IP blocks. Do not edit staged copies in `modules/`; they are overwritten on every setup run.

---

## 3. Heading depth and PDF assembly

Inside a **page**, write headings starting at `==`:

- `==` — main section
- `===` — subsection
- `====` — sub-subsection (use sparingly; prefer fewer levels)

The PDF assembly includes pages using `leveloffset`:

```adoc
// = Title becomes == (chapter); == body becomes ===
include::doc/modules/smu/pages/index.adoc[leveloffset=+1]

// = Title becomes === (section); == body becomes ====
include::doc/modules/dtp/pages/jtag.adoc[leveloffset=+2]
```

With `leveloffset`, the `= Title` of each included page is shifted automatically; you do not need to remove or tag-extract it. Do not use `[tag=body]` includes to strip the title: that pattern leaves `==` body headings at absolute document level and creates accidental top-level chapters in the PDF.

Write each page so that `==` is your outermost heading. The assembly controls absolute depth.

### Stable anchors

Place an explicit anchor before every section a reader might link to:

```adoc
[[dtp-jtag-ptap]]
== Primary TAP (PTAP)
```

Use kebab-case IDs prefixed with the subsystem or IP name (`dtp-`, `smu-`, `sep-`, `smc-`). Anchor IDs are public URLs; do not rename them once published. If you must rename, keep the old ID as an alias or provide a redirect.

### Partial includes from pages

Use backend-conditional paths when a partial is included from a page source:

```adoc
ifdef::backend-pdf[]
include::../partials/crossbar-table.adoc[]
endif::backend-pdf[]
ifdef::backend-html5[]
include::partial$crossbar-table.adoc[]
endif::backend-html5[]
```

The `../partials/` path is relative to the source file's location in the hardware tree. The `partial$` path is the Antora module reference. Both must be kept in sync if a partial is moved.

---

## 4. Links and cross-references

### Within the same module

```adoc
xref:jtag.adoc#dtp-jtag-ptap[Primary TAP]
```

### Across modules (HTML only)

Cross-module `xref:` calls produce file-link annotations in the PDF — they point to nonexistent per-topic PDF files. Wrap them in backend conditionals:

```adoc
ifdef::backend-html5[]
See xref:smu:index.adoc#smu-axi-crossbar[SMU AXI Crossbar] for crossbar port assignments.
endif::backend-html5[]
ifdef::backend-pdf[]
See <<smu-axi-crossbar,SMU AXI Crossbar>> for crossbar port assignments.
endif::backend-pdf[]
```

Format: `xref:<module>:<page>.adoc#<anchor>[Link text]`. Always provide explicit link text.

### PDF internal references

`<<anchor-id,Link text>>` — resolves to any anchor defined in the assembled document.

### Same-page anchors

An anchor defined on the standalone page resolves in HTML. Do not link from a page to an anchor that exists only in the assembled PDF (e.g., headings from a different page that is not cross-loaded): those produce `[#id]` placeholder text. Move shared content to its own page or qualify the reference.

---

## 5. Figures and tables

### Figures

```adoc
.DTP Block Diagram
image::dtp_arch_diagram.drawio.svg[DTP architecture showing JTAG Interface Unit and Cross Trigger Network,scaledwidth=100%]
```

Rules:
- Write a caption (`.Caption text` before the `image::` macro).
- Write useful alt text: describe what the diagram shows, not just its file name.
- Labels must be readable at A4 page width (~140 mm content area) and at desktop viewport (~1200 px). Test at both sizes.
- If an SVG renders as a fallback string ("Text is not SVG"), regenerate from the source tool or export as PNG.
- Source SVG/PNG files live at `hw/sys/<sys>/doc/assets/` or `hw/ip/<ip>/doc/assets/`. The staging script copies them to `modules/<mod>/assets/images/`. Do not commit staged images; edit the source assets.

### Tables

Use a `.Caption` and `options="header"` for every table with more than one column:

```adoc
.SMU AXI Crossbar Ports
[cols="1,1,3",options="header"]
|===
|Port |Direction |Description
|`sep_out` |Master→External |SEP-initiated transactions leaving the SMU
|===
```

Give tables explicit column widths to prevent narrow columns or line-wrapping in the PDF.

### Register documentation

Generated register documentation lives in `hw/<sys>/regs/gen/adoc/` (PDF) and `hw/<sys>/regs/gen/html/` (HTML partials). Do not copy field descriptions into prose; include or link to the generated output. The generated source is the single source of truth.

If generated register tables have presentation issues in PDF (column widths, line wrapping), the fix belongs in the generator template or a documented follow-up item — not in the generated output files, which are disposable and overwritten on every regeneration run.

---

## 6. Ownership boundaries

| Material | Home | Notes |
|---|---|---|
| Subsystem architecture, operation, configuration | TRM chapter (`hw/sys/<sys>/doc/`) | Hardware description for integrators and firmware authors |
| IP reference documentation | TRM IP section (`hw/ip/<ip>/doc/`) | Architecture, interface, register reference |
| Platform integration, pin/port assignments, integrator mandatory regions | Integrator Guide (`doc/integrator/`) | Do not duplicate in TRM; link from TRM where relevant |
| Register programming sequences, driver recipes, boot order | Programmer's Guide (`doc/programmer/`) | Link from TRM firmware notes |
| Simulation preprocessor defines, BFM parameters, cocotb infrastructure | DV guide or `dv/docs/` README | Do **not** stage into TRM pages; DV material is wrong context for integrators |
| Verification plan stubs (`dv_vplan.adoc`) | Not in TRM | Must not appear in the chapter assembly; remove from staging or migrate to a DV product |

The TRM covers *what the hardware does* and *how to use it*. It does not cover *how to simulate it* or *how to prove it*.

---

## 7. Verification checklist

Before submitting a change to a TRM page, confirm the following.

**HTML (run `make -f ocah.mk ocah-doc-trm-setup` then the Antora command):**

- [ ] Page `<title>` is the meaningful page title, not "Untitled". Confirm: `grep '<title>' <page>.html`.
- [ ] Top heading (`<h2>`) matches the `= Title` line.
- [ ] Nav sidebar shows this page at the correct depth under its parent.
- [ ] All `xref:` links resolve (Antora exits 0; no unresolved-xref warnings in the log).
- [ ] Figures render (no broken image icon).
- [ ] The page appears exactly once in the site.
- [ ] `revision.html` is absent from the release build output.

**PDF (run `make -f ocah.mk ocah-doc-trm-pdf`):**

- [ ] Section appears in the TOC at the correct level (part → chapter → section).
- [ ] No duplicated section headings.
- [ ] `<<anchor,text>>` references resolve (no `[#id]` placeholder text in the output).
- [ ] Figure renders; no SVG fallback text.
- [ ] No external file-link annotations (check: `pdfinfo -url <file>.pdf` should list none).

**Documented host build commands:**

```bash
# Setup
cd <clone-root>
OCAH_DOC_REGEN_REGS=0 OCAH_DOC_RELEASE=1 make -f ocah.mk ocah-doc-trm-setup

# HTML
node /path/to/antora-cli/bin/antora \
  --attribute release \
  --attribute "basedir=<clone-root>/doc/trm" \
  --log-failure-level error \
  antora-trm-playbook.yml

# PDF
GEM_HOME=<gems-dir> <gems-dir>/bin/asciidoctor-pdf \
  -a pdf-theme=doc/theme.yml -a pdf-themesdir=doc \
  -a toc -a toclevels=3 -a release \
  -o doc/trm/_build/latex/ocah-trm.pdf \
  doc/trm/src/index.adoc
```

Verified tool versions: Antora 3.1.15, Asciidoctor PDF 2.3.27, Ruby 3.2.3.
