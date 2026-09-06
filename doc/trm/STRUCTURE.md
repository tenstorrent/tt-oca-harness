<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# OCAH TRM Structure and DTP Content Map

Implementation design for the SMU-parent / DTP-pilot restructuring.
Records the approved structure, source ownership decisions and bounded change
list. Do not add to the Antora nav or the PDF assembly.

---

## 1. Web sidebar and PDF outline

### Web navigation

The production nav file is `doc/trm/modules/ROOT/nav.adoc`. A single nav file
is required; multiple separate nav files render each root `*` entry at the same
depth, breaking the intended hierarchy.

```
* TRM Landing
** Platform Architecture
** System Management Unit
*** Debug & Test Ports
**** Overview
**** Architecture and Access Paths
**** JTAG Operation (topology/integration)
**** JTAG Interface Unit
**** JTAG PTAP
**** JTAG STAP
**** Cross-Trigger Network
**** Cross-Trigger Port
**** Cross-Trigger Matrix
**** Clock Stop / Reset
**** Configuration and Reference
*** Security Processor (SEP)      ← existing, unchanged
*** System Management Controller (SMC) ← existing, unchanged
```

### PDF outline

```
= OCAH Technical Reference Manual
[front matter]

= Part I: OCAH Platform Architecture
  Ch 1: Platform Overview  (doc/trm/src/architecture.adoc [leveloffset=+1])

= Part II: System Management Unit
  Ch 2: SMU                (hw/sys/smu/doc/index.adoc [leveloffset=+1])
  Ch 3: DTP Overview       (hw/sys/dtp/doc/index.adoc [leveloffset=+1])
    3.1 Architecture and Access Paths   (hw/sys/dtp/doc/overview.adoc [leveloffset=+2])
    3.2 JTAG Operation                  (hw/sys/dtp/doc/jtag.adoc [leveloffset=+2])
    3.3 JTAG Interface Unit             (hw/ip/jtag/jtag_intf_unit/doc/index.adoc [leveloffset=+2])
    3.4 JTAG PTAP                       (hw/ip/jtag/jtag_ptap/doc/index.adoc [leveloffset=+2])
    3.5 JTAG STAP                       (hw/ip/jtag/jtag_stap/doc/index.adoc [leveloffset=+2])
    3.6 Cross-Trigger Network           (hw/ip/cross_trigger/cross_trigger_network/doc/index.adoc [leveloffset=+2])
    3.7 Cross-Trigger Port              (hw/ip/cross_trigger/cross_trigger_port/doc/index.adoc [leveloffset=+2])
    3.8 Cross-Trigger Matrix            (hw/ip/cross_trigger/cross_trigger_matrix/doc/index.adoc [leveloffset=+2])
    3.9 Clock Stop / Reset              (hw/sys/dtp/doc/clock_stop.adoc [leveloffset=+2])
    3.10 Configuration and Reference    (port table and register routes)
  Ch 4: SEP                (hw/sys/sep/doc/index.adoc [leveloffset=+1])  ← unchanged
  Ch 5: SMC                (hw/sys/smc/doc/index.adoc [leveloffset=+1])  ← unchanged
```

Both outlines follow the same order: overview → architecture/access → JTAG
operation (integration before IP detail) → cross-trigger → clock-stop → config/reference.

---

## 2. DTP reading order

1. **Overview** — purpose, capabilities, block diagram, reading route.
2. **Architecture and access paths** — the two major blocks (JIU and CTN) and
   how a reader reaches hardware: JTAG2AXI debug bridges via the SMU AXI
   crossbar; cross-trigger configuration via the same paths.
3. **JTAG operation** — DTP-level topology and integration first (`dtp/jtag.adoc`):
   scan chain wiring, clock domains, reset, lifecycle controls. IP detail
   (IU, PTAP, STAP) follows as supporting reference.
4. **Cross-trigger operation** — CTN network behaviour first: routing modes,
   CSR programming, wire-OR vs P2P. CTN owns the CTM and CTP register maps;
   CTP and CTM individual pages provide architecture/interface detail and
   must not re-include the register maps.
5. **Clock-stop / reset behaviour** — `dtp/clock_stop.adoc`.
6. **Configuration and reference** — hardware configuration parameters, port
   table, routes to generated register material.

`defines.adoc` is DV content and is excluded from this order and from staging.

---

## 3. Assembly include ownership (before → after)

This table shows which assembly edges exist at baseline and what changes during
the DTP pilot. SMC and SEP are untouched; their existing heading levels
(`leveloffset=0` in `architecture.adoc`) remain valid until an explicit SMC/SEP task.

| Assembly edge | Baseline owner | After DTP pilot |
|---|---|---|
| root → architecture.adoc | `src/index.adoc` | unchanged |
| architecture.adoc → sep/doc/index.adoc | `architecture.adoc` (leveloffset=0) | unchanged |
| architecture.adoc → smc/doc/index.adoc | `architecture.adoc` (leveloffset=0) | unchanged |
| architecture.adoc → dtp/doc/index.adoc | `architecture.adoc` (leveloffset=0) | **removed** — DTP moves to root assembly |
| root → smu/doc/index.adoc | _(new)_ | `src/index.adoc` (leveloffset=+1) |
| root → dtp/doc/index.adoc | _(new)_ | `src/index.adoc` (leveloffset=+1) |
| dtp/doc/index.adoc → IP chapters | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — IP chapters move to root assembly |
| root → each IP chapter | _(new)_ | `src/index.adoc` (leveloffset=+2) |
| dtp/doc/index.adoc → jtag.adoc, clock_stop.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moved to root assembly (leveloffset=+2) |

**Result:** `src/index.adoc` owns the complete book spine. Each topic is
included once. `architecture.adoc` retains SEP and SMC includes at baseline
`leveloffset=0` — these remain correct in the existing part structure. DTP is
removed from `architecture.adoc` after the pilot succeeds.

Small gap for the pilot: existing SMC and SEP content in `architecture.adoc`
uses `leveloffset=0`, meaning their `= Title` stays at level 0 (document title)
when the PDF assembler encounters them. This is the current production baseline
behaviour. Correcting SMC and SEP heading levels is scoped to the SMC and SEP
tasks, not the DTP pilot.

---

## 4. SMU framework scope

The SMU-framework task moves only:

- A short **composition introduction** adapted from `hw/sys/smu/doc/SMU_SPEC.md`
  §Overview and §Block Overview.
- The discrete **`[[smu-axi-crossbar]]` section** from `doc/trm/src/architecture.adoc`,
  ending before `[[ocah-memory-map]]`.

Platform-wide sections — memory map, power domains, clock domains, reset
hierarchy — **stay in `architecture.adoc`** and are linked from the SMU chapter.
Further SMU narrative belongs to the later SMU completion task.

After the move, `architecture.adoc` retains an HTML-only compatibility block:

```adoc
// architecture.adoc — HTML-only; PDF assembly includes the authoritative
// section from hw/sys/smu/doc/index.adoc, so no duplicate PDF destination.
ifdef::backend-html5[]
[[smu-axi-crossbar]]
_The SMU AXI Crossbar section has moved._
See xref:smu:index.adoc#smu-axi-crossbar[SMU AXI Crossbar].
endif::backend-html5[]
```

---

## 5. DTP source-to-destination map (25 files)

**Prefix legend:**

| Prefix | Expands to |
|---|---|
| `S/dtp` | `hw/sys/dtp/doc/` |
| `IP/jiu` | `hw/ip/jtag/jtag_intf_unit/doc/` |
| `IP/ptap` | `hw/ip/jtag/jtag_ptap/doc/` |
| `IP/stap` | `hw/ip/jtag/jtag_stap/doc/` |
| `IP/ctn` | `hw/ip/cross_trigger/cross_trigger_network/doc/` |
| `IP/ctp` | `hw/ip/cross_trigger/cross_trigger_port/doc/` |
| `IP/ctm` | `hw/ip/cross_trigger/cross_trigger_matrix/doc/` |

IP pages are staged to `ip/pages/<ip>/doc/` by the `stage_adoc_tree` IP loop.
IP private fragments (architecture.adoc, interface.adoc — no `= Title`, body
headings start at `====`) are staged to `ip/partials/<ip>/doc/` and included
by their owning index page. They are not standalone URLs.

### DTP subsystem files (6)

| Source | Staged destination | Notes |
|---|---|---|
| `S/dtp/index.adoc` | `dtp/pages/index.adoc` | Page: DTP chapter root; gains `= DTP` title |
| `S/dtp/overview.adoc` | `dtp/pages/overview.adoc` | Page: architecture + access paths |
| `S/dtp/jtag.adoc` | `dtp/pages/jtag.adoc` | Page: JTAG integration/topology |
| `S/dtp/clock_stop.adoc` | `dtp/pages/clock_stop.adoc` | Page: clock-stop / reset |
| `S/dtp/defines.adoc` | **Excluded** — DV content | Source preserved; migrate to `hw/sys/dtp/dv/docs/` |
| `S/dtp/port_table.adoc` | `ROOT/partials/hw/dtp/doc/port_table.adoc` | Fragment: port table for TRM and Integrator Guide |

### JTAG IP files (9)

| Source | Staged destination | Notes |
|---|---|---|
| `IP/jiu/index.adoc` | `ip/pages/jtag_intf_unit/doc/index.adoc` | Page: JTAG Interface Unit |
| `IP/jiu/architecture.adoc` | `ip/partials/jtag_intf_unit/doc/architecture.adoc` | Private fragment; `====` heading; included by JIU index |
| `IP/jiu/interface.adoc` | `ip/partials/jtag_intf_unit/doc/interface.adoc` | Private fragment; anchor `[[jtag-intf-unit-interface]]` |
| `IP/ptap/index.adoc` | `ip/pages/jtag_ptap/doc/index.adoc` | Page: JTAG PTAP |
| `IP/ptap/architecture.adoc` | `ip/partials/jtag_ptap/doc/architecture.adoc` | Private fragment; anchor `[[ptap-architecture]]` |
| `IP/ptap/interface.adoc` | `ip/partials/jtag_ptap/doc/interface.adoc` | Private fragment; anchor `[[ptap-interface]]` |
| `IP/stap/index.adoc` | `ip/pages/jtag_stap/doc/index.adoc` | Page: JTAG STAP |
| `IP/stap/architecture.adoc` | `ip/partials/jtag_stap/doc/architecture.adoc` | Private fragment |
| `IP/stap/interface.adoc` | `ip/partials/jtag_stap/doc/interface.adoc` | Private fragment |

### Cross-trigger IP files (10)

| Source | Staged destination | Notes |
|---|---|---|
| `IP/ctn/index.adoc` | `ip/pages/cross_trigger_network/doc/index.adoc` | Page: Cross-Trigger Network |
| `IP/ctn/architecture.adoc` | `ip/partials/cross_trigger_network/doc/architecture.adoc` | Private fragment |
| `IP/ctn/interface.adoc` | `ip/partials/cross_trigger_network/doc/interface.adoc` | Private fragment |
| `IP/ctn/memmap.adoc` | `ip/partials/cross_trigger_network/doc/memmap.adoc` | Fragment: **CTN owns CTM and CTP register maps** |
| `IP/ctp/index.adoc` | `ip/pages/cross_trigger_port/doc/index.adoc` | Page: Cross-Trigger Port |
| `IP/ctp/architecture.adoc` | `ip/partials/cross_trigger_port/doc/architecture.adoc` | Private fragment |
| `IP/ctp/interface.adoc` | `ip/partials/cross_trigger_port/doc/interface.adoc` | Private fragment |
| `IP/ctm/index.adoc` | `ip/pages/cross_trigger_matrix/doc/index.adoc` | Page: Cross-Trigger Matrix |
| `IP/ctm/architecture.adoc` | `ip/partials/cross_trigger_matrix/doc/architecture.adoc` | Private fragment |
| `IP/ctm/interface.adoc` | `ip/partials/cross_trigger_matrix/doc/interface.adoc` | Private fragment |

**Register ownership:** `IP/ctn/memmap.adoc` includes:
- HTML: `ip:partial$cross_trigger_matrix/regs/gen/html/cross_trigger_matrix.html`
  and `ip:partial$cross_trigger_port/regs/gen/html/cross_trigger_port.html`
- PDF: `../../cross_trigger_matrix/regs/gen/adoc/cross_trigger_matrix.adoc`
  and `../../cross_trigger_port/regs/gen/adoc/cross_trigger_port.adoc`

CTP and CTM individual pages must not re-include these maps.

---

## 6. Staging contract

### Changes to stage-docs.sh for SMU

```
SUBSYSTEMS="smc sep dtp"        →  SUBSYSTEMS="smc sep dtp smu"
MODULES="ROOT smc sep dtp ip"   →  MODULES="ROOT smc sep dtp smu ip"
```

The `clean()` function hard-codes `for m in smc sep dtp ip` — add `smu` there
too. `PORT_TABLE_SYS` already contains `smu`; no change needed. Image staging
uses `MODULES`; adding `smu` automatically creates `smu/assets/images/`.

The IP fragment routing change (architecture/interface → `ip/partials/` not
`ip/pages/`) requires a change to the IP staging loop: instead of
`stage_adoc_tree "$ipdir/doc" "$MOD/ip/pages/$ip/doc"` for all files, the
index pages go to `pages/` and the private fragments go to `partials/`. The
simplest approach is an explicit copy of the index file to `pages/` followed
by explicit copies of fragment files to `partials/` — or a pattern-based
exclusion from `stage_adoc_tree` combined with explicit partial staging.

After any `stage-docs.sh` change: rebuild the Integrator Guide and verify
it exits 0. Do not reclassify unrelated SMC/SEP pages during the DTP pilot.

### Fragment and DV exclusion

`stage_adoc_tree` copies **all** `.adoc` files. Files requiring explicit routing:

| File | Action |
|---|---|
| `hw/sys/smu/doc/crossbar-table.adoc` | Copy to `smu/partials/`; exclude from `stage_adoc_tree` |
| `hw/sys/dtp/doc/defines.adoc` | Exclude from staging entirely; source preserved |
| `IP/*/architecture.adoc`, `IP/*/interface.adoc` | Copy to `ip/partials/<ip>/doc/`; exclude from `ip/pages/` |
| `IP/ctn/memmap.adoc` | Copy to `ip/partials/cross_trigger_network/doc/`; exclude from `ip/pages/` |

---

## 7. URL and anchor compatibility

The old URL `architecture.html#smu-axi-crossbar` must continue to work after
the crossbar section moves to the SMU chapter. The old page keeps the anchor
and an onward link (HTML-only); the new page carries the authoritative content.
The PDF assembly includes only the new page, so there is one PDF destination.

| Old URL | Old anchor | New page | New anchor | Action |
|---|---|---|---|---|
| `architecture.html#smu-axi-crossbar` | `[[smu-axi-crossbar]]` | `smu/index.html` | `[[smu-axi-crossbar]]` | Compat block in architecture.adoc (HTML-only); new page carries authoritative anchor |
| `dtp/index.html#debug-test-ports` | `[[debug-test-ports]]` | `dtp/index.html` | `[[debug-test-ports]]` | No URL change; keep anchor |
| `dtp/jtag.html#dtp-jtag-integration` | `[[dtp-jtag-integration]]` | `dtp/jtag.html` | `[[dtp-jtag-integration]]` | No URL change; keep anchor |
| `dtp/clock_stop.html#dtp-clock-stop` | `[[dtp-clock-stop]]` | `dtp/clock_stop.html` | `[[dtp-clock-stop]]` | No URL change; keep anchor |
| `ip/jtag_intf_unit/doc/index.html#jtag-interface-unit` | `[[jtag-interface-unit]]` | same | same | No URL change |
| `ip/jtag_ptap/doc/index.html#jtag-ptap` | `[[jtag-ptap]]` | same | same | No URL change |
| `ip/jtag_ptap/doc/architecture.html` | `[[ptap-architecture]]` | Private fragment — no standalone URL | — | Old URL disappears; anchor survives on the PTAP index page via fragment include |
| `ip/jtag_stap/doc/index.html#jtag-stap` | `[[jtag-stap]]` | same | same | No URL change |
| `ip/cross_trigger_network/doc/index.html#cross-trigger-network` | `[[cross-trigger-network]]` | same | same | No URL change |
| `ip/cross_trigger_port/doc/index.html#cross-trigger-port` | `[[cross-trigger-port]]` | same | same | Anchor already exists in source |
| `ip/cross_trigger_matrix/doc/index.html#cross-trigger-matrix` | `[[cross-trigger-matrix]]` | same | same | Anchor already exists in source |

**Fixture proof** (Item 2): The 002c fixture demonstrates the `smu-axi-crossbar`
migration. Verified in `_build/html/`:
- `architecture.html` exists with `id="smu-axi-crossbar"` (old anchor present).
- `architecture.html` contains `href="smu/index.html#smu-axi-crossbar"` (onward link).
- `smu/index.html` contains `id="smu-axi-crossbar"` (new authoritative destination).
- PDF: one `smu-axi-crossbar` named destination (from SMU chapter only). No duplicate.

---

## 8. Fixture and build evidence

### Fixture location

`/tmp/claude-1000/task-002c/fixture/`, HEAD `1e68ad3`.

**Canonical sources** (single maintained copy):

```
hw/sys/smu/doc/index.adoc          ← authored SMU page
hw/sys/smu/doc/crossbar-table.adoc ← private fragment (→ smu/partials/)
hw/sys/smu/dv/defines.adoc         ← DV content (excluded from staging)
hw/sys/smu/assets/smu_block.svg    ← source image
hw/ip/jtag/jtag_ptap/doc/index.adoc    ← representative IP page
hw/ip/jtag/jtag_ptap/doc/architecture.adoc ← private fragment (→ ip/partials/)
doc/trm/src/architecture.adoc      ← compatibility page with HTML-only compat block
book.adoc                          ← PDF assembly (reads hw/ sources directly)
antora-playbook.yml                ← Antora reads staged/ git repo
stage.sh                           ← clean → stage → commit staged/
```

No prose is duplicated. `staged/` is generated by `stage.sh` and committed for
Antora HEAD reads. The PDF assembly (`book.adoc`) reads canonical `hw/` sources
directly with correct relative fragment paths.

### Commands

```bash
cd /tmp/claude-1000/task-002c/fixture

# 1. Clean and stage (populates and commits staged/)
bash stage.sh

# 2. HTML build (Antora reads staged/ git repo)
node /tmp/claude-1000/npm-cache/_npx/def697450dda4c3a/node_modules/@antora/cli/bin/antora \
  --log-failure-level error antora-playbook.yml

# 3. PDF build (reads canonical hw/ sources directly)
GEM_HOME=$TMPDIR/gems $TMPDIR/gems/bin/asciidoctor-pdf -D _build/pdf book.adoc

# 4. Checks
pdfinfo -url _build/pdf/book.pdf    # must list no *.pdf annotations
pdfinfo -dests _build/pdf/book.pdf  # must include smu-axi-crossbar
```

### Measured results

**HTML** — 4 pages (all titled):

| URL | `<title>` |
|---|---|
| `index.html` | `OCAH Prototype TRM :: OCAH Prototype TRM` |
| `architecture.html` | `OCAH Platform Architecture :: OCAH Prototype TRM` |
| `smu/index.html` | `System Management Unit :: OCAH Prototype TRM` |
| `ip/jtag_ptap/doc/index.html` | `JTAG Primary TAP (PTAP) :: OCAH Prototype TRM` |

**Nav depth** (measured `data-depth` from rendered HTML):

```
[2] Platform Architecture
[2] System Management Unit
  [3] JTAG Primary TAP
```

**Content verification:**
- `smu/index.html`: crossbar table present; `src="_images/smu_block.svg"` present.
- `ip/jtag_ptap/doc/index.html`: `id="ptap-architecture"` present; fragment body text present.
- `architecture.html`: `id="smu-axi-crossbar"` present; `href="smu/index.html#smu-axi-crossbar"` present.
- `smu/index.html`: `id="smu-axi-crossbar"` present (new authoritative destination).

**PDF:** Part "OCAH Platform Architecture" → Ch.1 Platform → Ch.2 SMU (§2.1 Composition, §2.2 AXI Crossbar, §2.3 PTAP). Zero external file annotations. Named destination `smu-axi-crossbar` on page 6 (one occurrence).

**Staging checks:** All three `PASS:` lines confirmed (DV excluded, crossbar-table in partials/, IP architecture.adoc in partials/).

### Production build reference

For the full TRM (do not run for this task):

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
