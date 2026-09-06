<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# OCAH TRM Structure and DTP Content Map

Implementation design for the SMU-parent / DTP-pilot restructuring.
This document records the approved structure, source ownership decisions and the bounded change list for subsequent tasks.

Do not add this file to the Antora nav or the PDF assembly.

---

## 1. Web sidebar hierarchy and PDF outline

### Web navigation (Antora sidebar)

The restructured nav exposes SMU directly as a top-level chapter with expandable DTP children. The current architecture-as-hub pattern (where subsystems are only hash-anchors under `architecture.html`) is replaced.

```
TRM Home / Landing
About OCAH
OCAH Architecture & Platform (architecture.adoc — platform-wide content only)
System Management Unit
  ├─ Overview (smu/index.adoc — composition, crossbar, power, clock, reset)
  ├─ Debug & Test Ports
  │    ├─ DTP Overview
  │    ├─ JTAG Interface Unit
  │    ├─ JTAG PTAP
  │    ├─ JTAG STAP
  │    ├─ JTAG Integration
  │    ├─ Cross Trigger Network
  │    ├─ Cross Trigger Port
  │    ├─ Cross Trigger Matrix
  │    └─ Clock Stop
  ├─ Security Processor (SEP)
  └─ System Management Controller (SMC)
Verification Dashboard
```

SEP and SMC are already staged via `SUBSYSTEMS="smc sep dtp"` in `doc/stage-docs.sh`. They remain in their current positions; this restructuring does not remove them. SMN and AoU remain as placeholder pages at their current level.

### PDF part/chapter outline

The PDF assembly uses `:doctype: book` with a part/chapter structure. Each subsystem page is included with `leveloffset` so the page's `= Title` shifts to the chapter heading; no body-tag extraction is needed or used (see AUTHORING.md §3 for why).

```
= OCAH Technical Reference Manual

[front matter / about OCAH]

= Part I: OCAH Platform Architecture
  Chapter 1: Platform Overview and Interconnect (from architecture.adoc)

= Part II: System Management Unit
  Chapter 2: System Management Unit (smu/index.adoc [leveloffset=+1])
  Chapter 3: Debug and Test Ports (dtp/index.adoc [leveloffset=+1])
    3.1  JTAG Interface Unit         (jtag_intf_unit/index.adoc [leveloffset=+2])
    3.2  JTAG PTAP                   (jtag_ptap/index.adoc [leveloffset=+2])
    3.3  JTAG STAP                   (jtag_stap/index.adoc [leveloffset=+2])
    3.4  JTAG Integration            (dtp/jtag.adoc [leveloffset=+2])
    3.5  Cross Trigger Network       (cross_trigger_network/index.adoc [leveloffset=+2])
    3.6  Cross Trigger Port          (cross_trigger_port/index.adoc [leveloffset=+2])
    3.7  Cross Trigger Matrix        (cross_trigger_matrix/index.adoc [leveloffset=+2])
    3.8  Clock Stop                  (dtp/clock_stop.adoc [leveloffset=+2])
  Chapter 4: Security Processor (sep/index.adoc [leveloffset=+1])
  Chapter 5: System Management Controller (smc/index.adoc [leveloffset=+1])

[appendices: SMN placeholder, AoU placeholder]
```

The PDF assembly (`doc/trm/src/index.adoc`) is the single owner of the PDF part/chapter hierarchy. Source pages do not contain assembly-level headings; `leveloffset` handles all heading promotion. This means each source page serves as a self-contained standalone URL in HTML and is promoted to the right chapter/section level in the PDF without duplication.

**Prototype result:** A 5-page HTML / 12-section PDF prototype at `/tmp/claude-1000/task-002a/proto/` proved this hierarchy. All HTML pages have correct `<title>` elements (not "Untitled"). PDF TOC: Part "System Management Unit" → Chapter 1 "System Management Unit" → Chapter 2 "Debug and Test Ports (DTP)" → §2.3 "JTAG Operation" / §2.4 "Cross-Trigger Network". No external file-link annotations (`pdfinfo -url` lists none). Cross-topic references resolve in both formats.

---

## 2. SMU source ownership

### Current state

SMU content is split across three locations:

| Location | Content | Status |
|---|---|---|
| `doc/trm/src/architecture.adoc` §§`[[smu-axi-crossbar]]`–`[[ocah-reset]]` | SMU AXI crossbar, memory map overview, power domains, clock domains, reset hierarchy | Platform-wide; anchors currently in `architecture.adoc` |
| `hw/sys/smu/doc/SMU_SPEC.md` | Overview, specifications, configuration parameters, architecture, interfaces, operating modes, clock/reset, error handling, security, DV info | Mixed: hardware description + DV/verification detail |
| `doc/integrator/src/index.adoc` §`smu-top-level-integration` | Integration wiring, module variants, port connections, firmware programming order | Integration guidance; stays in Integrator Guide |

### Proposed ownership after SMU-framework task

| Content | Destination | Notes |
|---|---|---|
| SMU composition (what SMC/SEP/DTP are) | `hw/sys/smu/doc/index.adoc` (new) → TRM SMU chapter | Adapt from `SMU_SPEC.md` §Overview and §Architecture §Block Overview |
| AXI crossbar port table and programming | `hw/sys/smu/doc/crossbar.adoc` (new) or fragment | Move from `architecture.adoc` `[[smu-axi-crossbar]]`; anchor preserved |
| Power domains, clock domains, reset hierarchy | `hw/sys/smu/doc/index.adoc` or `hw/sys/smu/doc/clk_rst.adoc` | Move from `architecture.adoc`; same anchor IDs (`[[ocah-power-domains]]`, `[[ocah-clock-domains]]`, `[[ocah-reset]]`) |
| OCAH top block diagram + high-level features | Stay in `architecture.adoc` | Platform-wide introductory content |
| OCAH memory map overview | Stay in `architecture.adoc` | Platform-wide; SMU-specific apertures move to SMU chapter |
| Config parameters from `SMU_SPEC.md` §Configuration | `hw/sys/smu/doc/index.adoc` or separate reference page | Select `smu_cfg_t` defaults and AXI parameter summary; omit RTL implementation detail |
| Features §1–7 from `SMU_SPEC.md` | Adapt selectively into SMU chapter narrative | §DV environment, BFM refs stay out of TRM |
| DV environment, BFM packages, cocotb flows | Not in TRM — stays in `hw/sys/smu/dv/` README or DV guide | `SMU_SPEC.md` §Verification Alignment, table row "Open-source DV location" |
| RTL implementation detail | Not in TRM — integrator note only | Already in `doc/integrator/src/index.adoc` §smu-module-variants |
| Integration wiring, port table | Stay in Integrator Guide; port_table.adoc staged as ROOT partial | SMU port table already staged as ROOT partial; TRM SMU chapter links to Integrator Guide |

`doc/trm/src/architecture.adoc` retains platform-wide introductory content. The SMU-specific subsections (`[[smu-axi-crossbar]]` through `[[ocah-reset]]`) move to the SMU chapter. Anchors must be preserved at their existing IDs to avoid breaking inbound links.

---

## 3. DTP source-to-destination map

### Source files (25 total)

DTP contributes 25 source files: 6 DTP subsystem files, 9 JTAG IP files (3 per IP × 3 IPs), and 10 cross-trigger IP files (CTN ×4 including memmap, CTP ×3, CTM ×3).

| Source | Current role | Destination |
|---|---|---|
| `hw/sys/dtp/doc/index.adoc` | DTP chapter assembly | Remains; gains `= Debug and Test Ports (DTP)` as standalone page title |
| `hw/sys/dtp/doc/overview.adoc` | DTP overview | TRM page: `= DTP Overview`; anchor `[[dtp-overview]]` preserved |
| `hw/sys/dtp/doc/jtag.adoc` | JTAG integration narrative | TRM page: `= JTAG Integration`; anchor `[[dtp-jtag-integration]]` preserved |
| `hw/sys/dtp/doc/clock_stop.adoc` | Clock-stop controls | TRM page: `= Clock Stop`; anchor `[[dtp-clock-stop]]` preserved |
| `hw/sys/dtp/doc/defines.adoc` | DV simulation defines | **Not TRM content** (TRM-B008); excluded from chapter assembly; migrate to `hw/sys/dtp/dv/docs/` |
| `hw/sys/dtp/doc/port_table.adoc` | Port declaration table | Remains as ROOT partial for both TRM and Integrator Guide |
| `hw/ip/jtag/jtag_intf_unit/doc/index.adoc` | JTAG IU overview | TRM page: `= JTAG Interface Unit`; anchor `[[jtag-interface-unit]]` preserved |
| `hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc` | JTAG IU architecture | Fragment included by `jtag_intf_unit/doc/index.adoc` |
| `hw/ip/jtag/jtag_intf_unit/doc/interface.adoc` | JTAG IU interface | Fragment; anchor `[[jtag-intf-unit-interface]]` |
| `hw/ip/jtag/jtag_ptap/doc/index.adoc` | PTAP overview | TRM page: `= JTAG PTAP`; anchor `[[jtag-ptap]]` preserved |
| `hw/ip/jtag/jtag_ptap/doc/architecture.adoc` | PTAP architecture + config params | Fragment; anchor `[[ptap-architecture]]` |
| `hw/ip/jtag/jtag_ptap/doc/interface.adoc` | PTAP interface | Fragment; anchor `[[ptap-interface]]` |
| `hw/ip/jtag/jtag_stap/doc/index.adoc` | STAP overview | TRM page: `= JTAG STAP`; anchor `[[jtag-stap]]` preserved |
| `hw/ip/jtag/jtag_stap/doc/architecture.adoc` | STAP architecture | Fragment |
| `hw/ip/jtag/jtag_stap/doc/interface.adoc` | STAP interface | Fragment |
| `hw/ip/cross_trigger/cross_trigger_network/doc/index.adoc` | CTN overview | TRM page: `= Cross Trigger Network`; anchor `[[cross-trigger-network]]` preserved |
| `hw/ip/cross_trigger/cross_trigger_network/doc/architecture.adoc` | CTN architecture | Fragment |
| `hw/ip/cross_trigger/cross_trigger_network/doc/interface.adoc` | CTN interface | Fragment |
| `hw/ip/cross_trigger/cross_trigger_network/doc/memmap.adoc` | CTN register map | Fragment; includes CTM and CTP register maps — see §Register ownership below |
| `hw/ip/cross_trigger/cross_trigger_port/doc/index.adoc` | CTP overview | TRM page: `= Cross Trigger Port` |
| `hw/ip/cross_trigger/cross_trigger_port/doc/architecture.adoc` | CTP architecture | Fragment |
| `hw/ip/cross_trigger/cross_trigger_port/doc/interface.adoc` | CTP interface | Fragment |
| `hw/ip/cross_trigger/cross_trigger_matrix/doc/index.adoc` | CTM overview | TRM page: `= Cross Trigger Matrix` |
| `hw/ip/cross_trigger/cross_trigger_matrix/doc/architecture.adoc` | CTM architecture | Fragment |
| `hw/ip/cross_trigger/cross_trigger_matrix/doc/interface.adoc` | CTM interface | Fragment |

**Nothing is silently dropped.** `defines.adoc` is excluded from the TRM chapter assembly but is preserved in its source file and noted as needing migration to DV guide documentation.

### Register ownership

`cross_trigger_network/doc/memmap.adoc` includes both the CTM register map (`partial$cross_trigger_matrix/regs/gen/html/cross_trigger_matrix.html`) and the CTP register map (`../../cross_trigger_port/regs/gen/adoc/cross_trigger_port.adoc`). The CTN page owns these register maps. The individual CTM and CTP standalone pages must not re-include their own register maps — doing so would duplicate them in the PDF assembly at each sub-section level.

### Staging changes required

`doc/stage-docs.sh` currently lists `SUBSYSTEMS="smc sep dtp"` and `MODULES="ROOT smc sep dtp ip"`. Adding SMU requires:

1. Add `smu` to `SUBSYSTEMS` (controls per-subsystem staging cleanup target)
2. Add `smu` to `MODULES` (controls which module trees are staged)
3. Confirm DV content exclusion: `stage_adoc_tree` copies ALL `.adoc` files from the source tree to `modules/<mod>/pages/`. Files that are partials or DV content (e.g., `defines.adoc`, `crossbar-table.adoc`) must either be placed in `partials/` in the source tree or excluded explicitly — they cannot be placed in `pages/` by this function without becoming standalone URLs.

`PORT_TABLE_SYS` already contains `smu`; no change needed for port table staging.

### Existing anchors and URL compatibility

The following anchors are currently reachable in the built site and must be preserved or explicitly redirected:

| Anchor | Location | Status |
|---|---|---|
| `[[debug-test-ports]]` | `dtp/index.adoc` | Preserve |
| `[[dtp-overview]]` | `dtp/overview.adoc` | Preserve |
| `[[dtp-jtag-integration]]` | `dtp/jtag.adoc` | Preserve |
| `[[dtp-clock-stop]]` | `dtp/clock_stop.adoc` | Preserve |
| `[[jtag-interface-unit]]` | `jtag_intf_unit/doc/index.adoc` | Preserve |
| `[[jtag-intf-unit-architecture]]` | `jtag_intf_unit/doc/architecture.adoc` | Preserve |
| `[[jtag-intf-unit-interface]]` | `jtag_intf_unit/doc/interface.adoc` | Preserve |
| `[[jtag-ptap]]` | `jtag_ptap/doc/index.adoc` | Preserve |
| `[[ptap-architecture]]` | `jtag_ptap/doc/architecture.adoc` | Preserve |
| `[[ptap-interface]]` | `jtag_ptap/doc/interface.adoc` | Preserve |

Anchors in the SMU material currently in `architecture.adoc` (`[[smu-axi-crossbar]]`, `[[ocah-power-domains]]`, `[[ocah-clock-domains]]`, `[[ocah-reset]]`) must be preserved at the same IDs when content moves to the SMU chapter. If a section moves to a different URL (different page file), the old page must retain a compatibility entry point with the old anchor ID pointing forward to the new location.

---

## 4. DTP reading order

Readers who are new to DTP should proceed in this order:

1. **DTP Overview** (`overview.adoc`) — architecture diagram, purpose, the two major blocks (JIU and CTN). Entry point.
2. **JTAG Interface Unit** (`jtag_intf_unit/doc/index.adoc`) — JTAG topology: PTAP, STAP chain, iJTAG network, JTAG2AXI bridges.
3. **JTAG PTAP** (`jtag_ptap/doc/index.adoc`) — primary TAP IEEE 1149.1 compliance, configuration, security lockout, boundary scan.
4. **JTAG STAP** (`jtag_stap/doc/index.adoc`) — secondary TAPs: per-component scan chains, TDI/TDO routing.
5. **JTAG Integration** (`jtag.adoc`) — DTP-level JTAG integration: clock domains, reset, lifecycle feature control.
6. **Cross Trigger Network** (`cross_trigger_network/doc/index.adoc`) — CTN controller, CSR apertures, wire-OR and P2P routing modes, register map (includes CTM and CTP registers).
7. **Cross Trigger Port** (`cross_trigger_port/doc/index.adoc`) — per-port connection and interface.
8. **Cross Trigger Matrix** (`cross_trigger_matrix/doc/index.adoc`) — CTM routing table, address map.
9. **Clock Stop** (`clock_stop.adoc`) — CLA clock-stop aggregation, cross-trigger clock stop coordination.
10. **Port Reference** (`port_table.adoc`) — SMU-level DTP port declaration.

`defines.adoc` is not in the reading order; it is DV content (see §3).

The PDF assembly presents IP detail (JTAG topology, PTAP/STAP) before integration narrative (JTAG Integration, clock-stop) because IP reference is needed to understand the integration. The web site provides the same sequence via the sidebar nav order. Both outlines match; a reader navigating from a printed TOC and a reader following web links reach the same sequence.

---

## 5. Bounded change list for subsequent tasks

### SMU-framework task (Step 3)

**Files to author or modify:**

| File | Change |
|---|---|
| `hw/sys/smu/doc/index.adoc` | New — SMU chapter page (`= System Management Unit`) |
| `hw/sys/smu/doc/crossbar.adoc` | New — SMU AXI crossbar detail (moved from `architecture.adoc`) |
| `doc/trm/src/architecture.adoc` | Remove `[[smu-axi-crossbar]]` through `[[ocah-reset]]` sections; add aliases for moved anchors |
| `doc/trm/src/index.adoc` | Add SMU includes (HTML xref + PDF filesystem include with `leveloffset=+1`) |
| `doc/trm/modules/ROOT/nav.adoc` | Add SMU entry and child chapter entries |
| `doc/stage-docs.sh` | Add `smu` to `SUBSYSTEMS` and `MODULES` |

**Checks after SMU-framework task:**
- All moved anchors resolve in both HTML and PDF.
- `architecture.adoc` hash-anchor subitems in the current nav are updated.
- Integrator Guide builds without errors after `stage-docs.sh` change.
- SMU standalone pages have correct `<title>` elements.

### DTP pilot task (Step 4)

**Files to modify:**

| File | Change |
|---|---|
| `hw/sys/dtp/doc/index.adoc` | Add `= Debug and Test Ports (DTP)` as standalone page title |
| `hw/sys/dtp/doc/overview.adoc` | Add `= DTP Overview`; address SVG diagram fallback text |
| `hw/sys/dtp/doc/jtag.adoc` | Add `= JTAG Integration`; fix intra-page fragment links — replace `#jtag-interface-unit` etc. with `xref:` cross-page links (see §6) |
| `hw/sys/dtp/doc/clock_stop.adoc` | Add `= Clock Stop` |
| `hw/sys/dtp/doc/defines.adoc` | Remove from chapter assembly include; leave file for DV guide migration |
| `hw/ip/jtag/*/doc/index.adoc` (3 files) | Add `= [IP name]` as page title |
| `hw/ip/cross_trigger/*/doc/index.adoc` (3 files) | Add `= [IP name]` as page title |
| `doc/trm/src/architecture.adoc` | Update DTP includes if source paths change |
| `doc/trm/modules/ROOT/nav.adoc` | Add DTP child page entries under SMU |

**Checks after DTP pilot task:**
- All DTP pages have correct `<title>` (not "Untitled").
- `dtp/jtag.html` cross-page links (`xref:jtag_intf_unit:index.adoc[…]` etc.) resolve.
- DTP block diagram renders without SVG fallback text.
- `defines.adoc` is absent from the built DTP chapter.
- CTM and CTP register maps appear exactly once in the PDF (owned by CTN memmap, not re-included by CTM/CTP standalone pages).
- PDF TOC shows DTP at chapter depth under the SMU part.

---

## 6. Baseline issues the pilot will address

From `doc/trm/meta/beta-issues.adoc` and `reviews/001b/REVIEW.md`:

| Issue | Source | DTP pilot action |
|---|---|---|
| Missing standalone page titles — 121 of 128 pages | TRM-B011 | Add `= Title` to all DTP source page files |
| DTP `jtag.html` links `#jtag-interface-unit`, `#jtag-ptap`, `#jtag-stap` show `[#id]` placeholder text | Codex review | Replace with `xref:` cross-page links to the standalone IP pages |
| DTP block diagram SVG fallback text visible in PDF | Codex review | Regenerate SVG from source tool; or provide PNG alternative |
| DTP diagram labels small at mobile viewport (390 px) | Codex review | Address in DTP pilot; note as known limitation if out of scope |
| Register-field table column wrapping in PDF | Codex review | Note as a generator template follow-up; do not edit generated output directly |
| `defines.adoc` included in TRM chapter assembly | TRM-B008 | Remove from assembly |

---

## 7. Prototype

A disposable prototype proving the SMU parent / DTP chapter hierarchy is at `/tmp/claude-1000/task-002a/proto/`.

### Source layout

```
proto/
  antora-playbook.yml
  book.adoc                         — PDF assembly (leveloffset, no tag::body)
  doc/
    antora.yml
    modules/
      ROOT/
        nav.adoc
        pages/index.adoc
      smu/
        nav.adoc
        pages/index.adoc            — = System Management Unit
        partials/crossbar-table.adoc — fragment, no = Title
      dtp/
        nav.adoc
        pages/
          index.adoc                — = Debug and Test Ports (DTP)
          jtag.adoc                 — = JTAG Operation
          cross-trigger.adoc        — = Cross-Trigger Network
        assets/images/
          dtp_arch_diagram.drawio.svg — real DTP SVG from hw/sys/dtp/doc/assets/
```

### Build commands

```bash
cd /tmp/claude-1000/task-002a/proto

# HTML
node /tmp/claude-1000/npm-cache/_npx/def697450dda4c3a/node_modules/@antora/cli/bin/antora \
  antora-playbook.yml

# PDF
GEM_HOME=$TMPDIR/gems $TMPDIR/gems/bin/asciidoctor-pdf \
  -D _build/pdf book.adoc
```

Both exit 0, zero errors.

### Results

**HTML** — 5 pages, all with correct `<title>` (zero "Untitled"):

| URL | `<title>` |
|---|---|
| `index.html` | `OCAH Prototype :: OCAH Prototype` |
| `smu/index.html` | `System Management Unit :: OCAH Prototype` |
| `dtp/index.html` | `Debug and Test Ports (DTP) :: OCAH Prototype` |
| `dtp/jtag.html` | `JTAG Operation :: OCAH Prototype` |
| `dtp/cross-trigger.html` | `Cross-Trigger Network :: OCAH Prototype` |

Sidebar hierarchy: OCAH Prototype → System Management Unit → Debug & Test Ports → JTAG Operation / Cross-Trigger Network.

**PDF** — Asciidoctor PDF 2.3.27. TOC:
- Part "System Management Unit" (unnumbered)
- Chapter 1 "System Management Unit" (§1.1 Subsystem Composition, §1.2 AXI Crossbar)
- Chapter 2 "Debug and Test Ports (DTP)" (§2.1 Architecture Overview, §2.2 Chapter Contents, §2.3 JTAG Operation, §2.4 Cross-Trigger Network)

`pdfinfo -url book.pdf` lists no external file-link annotations. Real DTP architecture SVG renders as a figure in the PDF. Internal `<<smu-axi-crossbar,…>>` references appear as linked text.
