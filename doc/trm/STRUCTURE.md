<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# OCAH TRM Structure and DTP Content Map

Implementation design for the SMU-parent / DTP-pilot restructuring.
Records the approved structure, source ownership decisions and bounded change
list. Do not add to the Antora nav or the PDF assembly.

---

## 1. Web sidebar and PDF outline

### Web navigation

The production nav file is `doc/trm/modules/ROOT/nav.adoc`. Use one nested
list there for this design. Registering independent lists with root `*` entries
does not nest those entries beneath one another.

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
  Ch 4: SEP                (hw/sys/sep/doc/index.adoc [leveloffset=0])  ← existing == heading; offset 0 until SEP task
  Ch 5: SMC                (hw/sys/smc/doc/index.adoc [leveloffset=0])  ← existing == heading; offset 0 until SMC task
```

Both outlines follow the same order: overview → architecture/access → JTAG
operation (integration before IP detail) → cross-trigger → clock-stop → config/reference.

The after-DTP-pilot PDF assembly root (`src/index.adoc`) includes chapters in this
order:

```adoc
= OCAH Platform Architecture
include::architecture.adoc[leveloffset=+1]

= System Management Unit
include::../../../hw/sys/smu/doc/index.adoc[leveloffset=+1]
include::../../../hw/sys/dtp/doc/index.adoc[leveloffset=+1]
// DTP topics follow here, each included once at leveloffset=+2:
// overview/access paths, JTAG integration, IU/PTAP/STAP,
// CTN/CTP/CTM, clock-stop, configuration/reference.

// Unchanged baseline child indexes already start with == chapter headings.
include::../../../hw/sys/sep/doc/index.adoc[leveloffset=0]
include::../../../hw/sys/smc/doc/index.adoc[leveloffset=0]
```

Note: DTP's own `index.adoc` gains `= Title` as part of the pilot. Pre-pilot, the
file starts with `==`; include it temporarily at `leveloffset=0` until the pilot
adds the title, at which point change to `leveloffset=+1`.

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
the DTP pilot. SEP and SMC existing indexes start with `==` (not `= Title`);
use `leveloffset=0` to keep those headings at chapter level. Correcting SEP/SMC
to use `= Title` is scoped to their own later restructuring tasks.

| Assembly edge | Baseline owner | After DTP pilot |
|---|---|---|
| root → architecture.adoc | `src/index.adoc` (offset 0) | same owner; offset +1 beneath the platform part |
| architecture.adoc → sep/doc/index.adoc | `architecture.adoc` (leveloffset=0) | **removed** — SEP moves to root assembly under SMU part |
| architecture.adoc → smc/doc/index.adoc | `architecture.adoc` (leveloffset=0) | **removed** — SMC moves to root assembly under SMU part |
| architecture.adoc → dtp/doc/index.adoc | `architecture.adoc` (leveloffset=0) | **removed** — DTP moves to root assembly under SMU part |
| root → smu/doc/index.adoc | _(new with SMU framework task)_ | `src/index.adoc` (leveloffset=+1) |
| root → dtp/doc/index.adoc (pre-pilot) | _(new)_ | `src/index.adoc` (leveloffset=0) — DTP starts with ==; temporary until pilot adds = Title |
| root → dtp/doc/index.adoc (after pilot) | _(pilot changes this edge)_ | `src/index.adoc` (leveloffset=+1) — pilot adds = Title |
| dtp/doc/index.adoc → overview.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moves to root assembly at leveloffset=+2 |
| dtp/doc/index.adoc → jtag_intf_unit/doc/index.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moves to root assembly at leveloffset=+2 |
| dtp/doc/index.adoc → jtag_ptap/doc/index.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moves to root assembly at leveloffset=+2 |
| dtp/doc/index.adoc → jtag_stap/doc/index.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moves to root assembly at leveloffset=+2 |
| dtp/doc/index.adoc → cross_trigger_network/doc/index.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moves to root assembly at leveloffset=+2 |
| dtp/doc/index.adoc → cross_trigger_port/doc/index.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moves to root assembly at leveloffset=+2 |
| dtp/doc/index.adoc → cross_trigger_matrix/doc/index.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moves to root assembly at leveloffset=+2 |
| dtp/doc/index.adoc → jtag.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moves to root assembly at leveloffset=+2 |
| dtp/doc/index.adoc → clock_stop.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed** — moves to root assembly at leveloffset=+2 |
| dtp/doc/index.adoc → defines.adoc | `dtp/doc/index.adoc` (leveloffset=0) | **removed entirely** — defines.adoc is DV content; excluded from TRM |
| root → each DTP topic | _(new)_ | `src/index.adoc` (leveloffset=+2) |
| root → sep/doc/index.adoc | _(new under SMU part)_ | `src/index.adoc` (leveloffset=0) — existing == heading; unchanged until SEP task |
| root → smc/doc/index.adoc | _(new under SMU part)_ | `src/index.adoc` (leveloffset=0) — existing == heading; unchanged until SMC task |

**Result:** `src/index.adoc` owns the complete book spine. Each topic is
included exactly once. `architecture.adoc` has no subsystem includes; it
contains only platform-wide content (memory map, clock/reset domains) plus the
HTML-only `[[smu-axi-crossbar]]` compatibility block. SEP and SMC appear under
the SMU part at `leveloffset=0`; their `==` headings become chapter headings
within the part, which matches their current production treatment.

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

Retain the existing about/revision front matter and SMN/AoU placeholder content.
When architecture becomes platform-only, move its SMN/AoU assembly includes
to a following platform-components part at the root, preserving their `==`
chapter headings at offset 0 and their existing standalone web paths. This
keeps those components outside SMU containment without adding technical prose.

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
IP private fragments (architecture.adoc, interface.adoc — no `= Title`) are
staged to `ip/partials/<ip>/doc/` and included by their owning index page.
They are not standalone URLs. The owning index page supplies the `== Architecture`
or `== Interface` section heading; the fragment supplies anchored body content,
with any subheadings at a level below that section heading. Do not add a blanket
`====` heading inside fragments — use the appropriate level relative to the owning
section.

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
| `IP/jiu/architecture.adoc` | `ip/partials/jtag_intf_unit/doc/architecture.adoc` | Private fragment; anchored body; included by JIU index |
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

Apply this routing exception only to the six DTP IPs listed in section 5.
All other IPs retain their existing staging behaviour. Stage the 13 authored
TRM compatibility pages from section 7 into their old page paths separately;
never substitute the technical fragment itself for a compatibility page.

After any `stage-docs.sh` change: rebuild the Integrator Guide and verify
it exits 0. Check affected IP includes there as well as the TRM; preserve
sibling-product resource paths or update consumers under the relevant brief.
Do not reclassify unrelated SMC/SEP pages during the DTP pilot.

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

### Crossbar section migration

The old URL `architecture.html#smu-axi-crossbar` must continue to work after
the crossbar section moves to the SMU chapter. The old page keeps the anchor
and an onward link (HTML-only); the new page carries the authoritative content.
The PDF assembly includes only the new page, so there is one PDF destination.

| Old URL | Old anchor | New page | New anchor | Action |
|---|---|---|---|---|
| `architecture.html#smu-axi-crossbar` | `[[smu-axi-crossbar]]` | `smu/index.html` | `[[smu-axi-crossbar]]` | Compat block in architecture.adoc (HTML-only); new page carries authoritative anchor |

### IP fragment URL compatibility (13 pages)

Converting architecture/interface/memmap sub-files to private partials removes
their old standalone URLs. For each old URL, author a short **HTML-only
compatibility page** at that exact path. Each compat page contains:
- `= Title (moved)` — a meaningful HTML title
- The old explicit anchor (e.g., `[[ptap-architecture]]`)
- An onward `xref:` link to the owning IP index page and the anchor there
- No copied technical prose

Compat pages are authored at `doc/trm/compat/ip/<ip>/doc/<filename>.adoc` and
staged to `ip/pages/<ip>/doc/<filename>.adoc` (HTML-only, not in PDF assembly).
The private fragment itself is staged to `ip/partials/<ip>/doc/<filename>.adoc`.

Anchors verified against current production source files:

**JTAG IP (6 compat pages):**

| Old URL (fragment → private) | Old anchor in fragment | New owning page | Anchor on owning page | Compat page source |
|---|---|---|---|---|
| `ip/jtag_intf_unit/doc/architecture.html` | `[[jtag-intf-unit-architecture]]` | `ip/jtag_intf_unit/doc/index.html` | `[[jtag-intf-unit-architecture]]` | `doc/trm/compat/ip/jtag_intf_unit/doc/architecture.adoc` |
| `ip/jtag_intf_unit/doc/interface.html` | `[[jtag-intf-unit-interface]]` | `ip/jtag_intf_unit/doc/index.html` | `[[jtag-intf-unit-interface]]` | `doc/trm/compat/ip/jtag_intf_unit/doc/interface.adoc` |
| `ip/jtag_ptap/doc/architecture.html` | `[[ptap-architecture]]` | `ip/jtag_ptap/doc/index.html` | `[[ptap-architecture]]` (via fragment include) | `doc/trm/compat/ip/jtag_ptap/doc/architecture.adoc` |
| `ip/jtag_ptap/doc/interface.html` | `[[ptap-interface]]` | `ip/jtag_ptap/doc/index.html` | `[[ptap-interface]]` (via fragment include) | `doc/trm/compat/ip/jtag_ptap/doc/interface.adoc` |
| `ip/jtag_stap/doc/architecture.html` | `[[stap-architecture]]` | `ip/jtag_stap/doc/index.html` | `[[stap-architecture]]` | `doc/trm/compat/ip/jtag_stap/doc/architecture.adoc` |
| `ip/jtag_stap/doc/interface.html` | `[[stap-interface]]` | `ip/jtag_stap/doc/index.html` | `[[stap-interface]]` | `doc/trm/compat/ip/jtag_stap/doc/interface.adoc` |

**Cross-trigger IP (7 compat pages):**

| Old URL (fragment → private) | Old anchor in fragment | New owning page | Anchor on owning page | Compat page source |
|---|---|---|---|---|
| `ip/cross_trigger_network/doc/architecture.html` | `[[cross-trigger-network-architecture]]` | `ip/cross_trigger_network/doc/index.html` | `[[cross-trigger-network-architecture]]` (via fragment) | `doc/trm/compat/ip/cross_trigger_network/doc/architecture.adoc` |
| `ip/cross_trigger_network/doc/interface.html` | `[[cross-trigger-network-interface]]` | `ip/cross_trigger_network/doc/index.html` | `[[cross-trigger-network-interface]]` (via fragment) | `doc/trm/compat/ip/cross_trigger_network/doc/interface.adoc` |
| `ip/cross_trigger_network/doc/memmap.html` | `[[ctn-memory-map]]` | `ip/cross_trigger_network/doc/index.html` | `[[ctn-memory-map]]` (via fragment) | `doc/trm/compat/ip/cross_trigger_network/doc/memmap.adoc` |
| `ip/cross_trigger_port/doc/architecture.html` | `[[ctp-architecture]]` | `ip/cross_trigger_port/doc/index.html` | `[[ctp-architecture]]` (via fragment) | `doc/trm/compat/ip/cross_trigger_port/doc/architecture.adoc` |
| `ip/cross_trigger_port/doc/interface.html` | `[[ctp-interface]]` | `ip/cross_trigger_port/doc/index.html` | `[[ctp-interface]]` | `doc/trm/compat/ip/cross_trigger_port/doc/interface.adoc` |
| `ip/cross_trigger_matrix/doc/architecture.html` | `[[ctm-architecture]]` | `ip/cross_trigger_matrix/doc/index.html` | `[[ctm-architecture]]` (via fragment) | `doc/trm/compat/ip/cross_trigger_matrix/doc/architecture.adoc` |
| `ip/cross_trigger_matrix/doc/interface.html` | `[[ctm-interface]]` | `ip/cross_trigger_matrix/doc/index.html` | `[[ctm-interface]]` | `doc/trm/compat/ip/cross_trigger_matrix/doc/interface.adoc` |

Notes:
- Preserve the anchored fragment body on each owning index page; compatibility
  links target that same specific section, not just the block overview.
- The CTP and CTM index overview anchors (`cross-trigger-port` and
  `cross-trigger-matrix`) also remain unchanged.
- CTN `memmap.html#ctn-memory-map` exists in the verified baseline HTML;
  its compatibility page is required along with the other 12 pages.

**Fixture proof** (Items 1 and 2): The 002d fixture demonstrates both compat routes. Verified in `_build/html/`:
- `architecture.html` exists with `id="smu-axi-crossbar"` (old anchor present).
- `architecture.html` contains `href="smu/index.html#smu-axi-crossbar"` (onward link).
- `smu/index.html` contains `id="smu-axi-crossbar"` (new authoritative destination).
- `ip/jtag_ptap/doc/architecture.html` exists with `id="ptap-architecture"` and `href="index.html#ptap-architecture"`.
- `ip/jtag_ptap/doc/index.html` contains `id="ptap-architecture"` (via private fragment include).
- PDF: one `smu-axi-crossbar` named destination (from SMU chapter only). No duplicate.
- PDF: `ptap-architecture` named destination present. Compat page absent from PDF (HTML-only).

---

## 8. Fixture and build evidence

### Fixture location

`/tmp/claude-1000/task-002d/fixture/`, HEAD `b625376`.

**Canonical sources** (single maintained copy):

```
hw/sys/smu/doc/index.adoc               ← authored SMU page
hw/sys/smu/doc/crossbar-table.adoc      ← private fragment (→ smu/partials/)
hw/sys/smu/dv/defines.adoc              ← DV content (excluded from staging)
hw/sys/smu/assets/smu_block.svg         ← source image
hw/sys/dtp/doc/index.adoc               ← DTP chapter (= Title; pilot-shaped)
hw/sys/dtp/doc/jtag.adoc                ← DTP JTAG topic (= Title)
hw/sys/sep/doc/index.adoc               ← SEP stand-in (== heading; no = Title)
hw/sys/smc/doc/index.adoc               ← SMC stand-in (== heading; no = Title)
hw/ip/jtag/jtag_ptap/doc/index.adoc     ← representative IP page
hw/ip/jtag/jtag_ptap/doc/architecture.adoc ← private fragment (→ ip/partials/)
doc/trm/src/architecture.adoc           ← platform page with HTML-only compat block
doc/trm/compat/ip/jtag_ptap/doc/architecture.adoc ← IP compat page (→ ip/pages/)
book.adoc                               ← PDF assembly (reads hw/ sources directly)
antora-playbook.yml                     ← Antora reads staged/ git repo
stage.sh                                ← clean → stage → commit staged/
```

No prose is duplicated. `staged/` is generated by `stage.sh` and committed for
Antora HEAD reads. The PDF assembly (`book.adoc`) reads canonical `hw/` sources
directly with correct relative fragment paths.

### Commands

```bash
cd /tmp/claude-1000/task-002d/fixture

# 1. Clean and stage (populates and commits staged/)
bash stage.sh

# 2. HTML build (Antora reads staged/ git repo)
node /home/colin-mckellar/.npm/_npx/def697450dda4c3a/node_modules/@antora/cli/bin/antora \
  antora-playbook.yml

# 3. PDF build (reads canonical hw/ sources directly)
GEM_HOME=/tmp/claude-1000/gems /tmp/claude-1000/gems/bin/asciidoctor-pdf \
  -o _build/pdf/book.pdf book.adoc

# 4. Checks
pdfinfo -url _build/pdf/book.pdf    # must list no *.pdf annotations
pdfinfo -dests _build/pdf/book.pdf  # must include smu-axi-crossbar, ptap-architecture
```

### Measured results

**HTML** — 7 pages (all titled):

| URL | `<title>` |
|---|---|
| `index.html` | `OCAH Prototype TRM :: OCAH Prototype TRM` |
| `architecture.html` | `OCAH Platform Architecture :: OCAH Prototype TRM` |
| `smu/index.html` | `System Management Unit :: OCAH Prototype TRM` |
| `dtp/index.html` | `Debug and Test Ports (DTP) :: OCAH Prototype TRM` |
| `dtp/jtag.html` | `JTAG Operation :: OCAH Prototype TRM` |
| `ip/jtag_ptap/doc/index.html` | `JTAG Primary TAP (PTAP) :: OCAH Prototype TRM` |
| `ip/jtag_ptap/doc/architecture.html` | `PTAP Architecture (moved) :: OCAH Prototype TRM` |

**Nav depth** (measured `data-depth` from rendered HTML):

```
[1] OCAH Prototype TRM
[2] Platform Architecture
[2] System Management Unit
  [3] Debug and Test Ports (DTP)
    [4] JTAG Operation
    [4] JTAG Primary TAP (PTAP)
```

**Content verification:**
- `smu/index.html`: crossbar table present; `src="_images/smu_block.svg"` present.
- `ip/jtag_ptap/doc/index.html`: `id="ptap-architecture"` present (via fragment include).
- `ip/jtag_ptap/doc/architecture.html`: `id="ptap-architecture"` present (compat anchor); `href="index.html#ptap-architecture"` present (onward link).
- `architecture.html`: `id="smu-axi-crossbar"` present; `href="smu/index.html#smu-axi-crossbar"` present.
- `smu/index.html`: `id="smu-axi-crossbar"` present (new authoritative destination).

**PDF:** 9 pages. Part "OCAH Platform Architecture" → Ch.1 Platform → Part "System Management Unit" → Ch.2 SMU → Ch.3 DTP (§3.1 Architecture Overview, §3.2 Reading Route) → §3.x JTAG Operation → §3.x JTAG Primary TAP → Ch.4 SEP → Ch.5 SMC. Zero external file annotations (`pdfinfo -url` empty). Named destinations include: `smu-axi-crossbar`, `debug-test-ports`, `dtp-jtag-integration`, `jtag-ptap`, `ptap-architecture`, `security-processor-sep`, `system-management-controller-smc`.

**Staging checks:** All five `PASS:` lines confirmed (DV excluded, crossbar-table in partials/, IP architecture fragment in partials/, compat page in ip/pages/, DTP pages present).

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
