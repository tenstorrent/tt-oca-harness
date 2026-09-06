<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# OCAH TRM Structure and DTP Content Map

Implementation design for the SMU-parent / DTP-pilot restructuring.
Records the approved structure, source ownership decisions and bounded change
list. Do not add to the Antora nav or the PDF assembly.

---

## 1. Web sidebar hierarchy and PDF outline

### Web navigation

One nav file (`doc/trm/modules/ROOT/nav/nav.adoc`) nests DTP beneath SMU:

```
* TRM Landing
** System Management Unit
*** Debug & Test Ports
**** DTP Overview
**** JTAG Interface Unit
**** JTAG PTAP
**** JTAG STAP
**** JTAG Integration
**** Cross Trigger Network
**** Cross Trigger Port
**** Cross Trigger Matrix
**** Clock Stop
*** Security Processor (SEP)      ← existing, unchanged
*** System Management Controller (SMC) ← existing, unchanged
```

A single nav file is required; multiple separate nav files render each
root-level `*` entry at the same sidebar depth, breaking the hierarchy.
DTP must be a `***` entry under SMU, not a sibling `**`.

SMC and SEP remain at `***` under SMU once the SMU framework is in place.
They are not removed during the DTP pilot and must stay reachable throughout.

### PDF outline

```
= OCAH Technical Reference Manual

[front matter]

= Part I: OCAH Platform Architecture
  Chapter 1: Platform Overview (architecture.adoc [leveloffset=+1])

= Part II: System Management Unit
  Chapter 2: SMU (smu/index.adoc [leveloffset=+1])
  Chapter 3: DTP Overview (dtp/index.adoc [leveloffset=+1])
    3.1 JTAG Operation (dtp/jtag.adoc [leveloffset=+2])
    3.2 JTAG Interface Unit (jtag_intf_unit/index.adoc [leveloffset=+2])
    3.3 JTAG PTAP (jtag_ptap/index.adoc [leveloffset=+2])
    3.4 JTAG STAP (jtag_stap/index.adoc [leveloffset=+2])
    3.5 Cross Trigger Network (cross_trigger_network/index.adoc [leveloffset=+2])
    3.6 Cross Trigger Port (cross_trigger_port/index.adoc [leveloffset=+2])
    3.7 Cross Trigger Matrix (cross_trigger_matrix/index.adoc [leveloffset=+2])
    3.8 Clock Stop (dtp/clock_stop.adoc [leveloffset=+2])
  Chapter 4: SEP (sep/index.adoc [leveloffset=+1])  ← existing, unchanged
  Chapter 5: SMC (smc/index.adoc [leveloffset=+1])  ← existing, unchanged
```

The PDF assembly (`doc/trm/src/index.adoc`) is the single owner of this
hierarchy. Each topic is included exactly once; existing SMC and SEP includes
are preserved without change during the DTP pilot.

**Prototype:** `/tmp/claude-1000/task-002b/proto/` proves this hierarchy.
Nav depth confirmed: `[2] SMU → [3] DTP → [4] JTAG Operation / Cross-Trigger Network`.
PDF TOC: Part → Ch.1 SMU → Ch.2 DTP → §2.3 JTAG Operation → §2.4 Cross-Trigger.
Zero external file annotations. Build commands in §7.

---

## 2. DTP reading order

Both the web sidebar and PDF outline follow this conceptual sequence:

1. **Overview** — purpose, capabilities, block diagram, reading route.
2. **Architecture and access paths** — the two major blocks (JIU and CTN)
   and how a reader reaches hardware: JTAG2AXI debug bridges to SMC/SEP via
   the SMU AXI crossbar; cross-trigger configuration via the same paths.
3. **JTAG operation** — DTP-level JTAG topology and integration first
   (`dtp/jtag.adoc`): scan chain wiring, clock domains, reset, lifecycle
   controls. IP detail (IU/PTAP/STAP) follows as supporting reference;
   readers who only need topology can stop at step 3.
4. **Cross-trigger operation** — CTN network behaviour (`cross_trigger_network`)
   first: routing modes, CSR programming, wire-OR vs P2P. CTN owns the
   CTM and CTP register maps and includes them in `memmap.adoc`. CTP and
   CTM individual pages provide architecture and interface detail; they do
   not re-include the register maps (which would duplicate them in the PDF).
5. **Clock-stop/reset behaviour** — `dtp/clock_stop.adoc`.
6. **Configuration and reference** — hardware configuration parameters,
   port table, routes to generated register material.

The IP inventory (IU, PTAP, STAP, CTN, CTP, CTM) appears after the
integration narrative in both outlines, not before it.

`defines.adoc` is DV content and does not appear in this reading order.

---

## 3. SMU framework scope

The SMU-framework task moves only:

- A short **composition introduction** adapted from `hw/sys/smu/doc/SMU_SPEC.md`
  §Overview and §Block Overview: what SMC, SEP and DTP are, the AXI crossbar role.
- The discrete **`[[smu-axi-crossbar]]` section** from `doc/trm/src/architecture.adoc`,
  ending before `[[ocah-memory-map]]`.

Platform-wide sections — memory map, power domains (`[[ocah-power-domains]]`),
clock domains (`[[ocah-clock-domains]]`), reset hierarchy (`[[ocah-reset]]`) —
**stay in `architecture.adoc`** and are linked from the SMU chapter.
Further SMU-specific narrative (operating modes, error handling) belongs to the
later SMU completion task.

`architecture.adoc` retains its platform-wide role. After the framework move:
- `[[smu-axi-crossbar]]` lives in `hw/sys/smu/doc/crossbar.adoc` with
  the same anchor ID.
- `architecture.adoc` keeps a compatibility anchor `[[smu-axi-crossbar]]`
  for backward compatibility until all inbound links are updated.
- SMC and SEP assembly includes in `src/index.adoc` are unchanged.

---

## 4. DTP source-to-destination map (25 files)

**Prefix legend:**

| Prefix | Expands to |
|---|---|
| `S/dtp` | `hw/sys/dtp/doc/` |
| `S/smu` | `hw/sys/smu/doc/` |
| `IP/jiu` | `hw/ip/jtag/jtag_intf_unit/doc/` |
| `IP/ptap` | `hw/ip/jtag/jtag_ptap/doc/` |
| `IP/stap` | `hw/ip/jtag/jtag_stap/doc/` |
| `IP/ctn` | `hw/ip/cross_trigger/cross_trigger_network/doc/` |
| `IP/ctp` | `hw/ip/cross_trigger/cross_trigger_port/doc/` |
| `IP/ctm` | `hw/ip/cross_trigger/cross_trigger_matrix/doc/` |

Staged destinations use `<mod>/pages/` for standalone pages and
`<mod>/partials/` for fragments. The `ip` Antora module uses the path
`ip:partial$<ip>/regs/gen/html/<name>.html` for HTML register includes;
PDF uses the filesystem path relative to the canonical source file.

### DTP subsystem files (6)

| Canonical source | Staged destination | Role |
|---|---|---|
| `S/dtp/index.adoc` | `dtp/pages/index.adoc` | Page: DTP Overview — gains `= Debug and Test Ports (DTP)` |
| `S/dtp/overview.adoc` | `dtp/pages/overview.adoc` | Page: DTP architecture narrative; repair SVG fallback text |
| `S/dtp/jtag.adoc` | `dtp/pages/jtag.adoc` | Page: JTAG integration (topology, clocks, reset) |
| `S/dtp/clock_stop.adoc` | `dtp/pages/clock_stop.adoc` | Page: clock-stop behaviour |
| `S/dtp/defines.adoc` | **Excluded** — DV content | Source preserved; not staged; migrate to `hw/sys/dtp/dv/docs/` |
| `S/dtp/port_table.adoc` | `ROOT/partials/hw/dtp/doc/port_table.adoc` | Fragment: port table for TRM and Integrator Guide |

### JTAG IP files (9: 3 per IP × 3 IPs)

| Canonical source | Staged destination | Role |
|---|---|---|
| `IP/jiu/index.adoc` | `ip/pages/jtag_intf_unit/doc/index.adoc` | Page: JTAG Interface Unit |
| `IP/jiu/architecture.adoc` | `ip/pages/jtag_intf_unit/doc/architecture.adoc` | Fragment included by JIU index |
| `IP/jiu/interface.adoc` | `ip/pages/jtag_intf_unit/doc/interface.adoc` | Fragment; anchor `[[jtag-intf-unit-interface]]` |
| `IP/ptap/index.adoc` | `ip/pages/jtag_ptap/doc/index.adoc` | Page: JTAG PTAP |
| `IP/ptap/architecture.adoc` | `ip/pages/jtag_ptap/doc/architecture.adoc` | Fragment; anchor `[[ptap-architecture]]` |
| `IP/ptap/interface.adoc` | `ip/pages/jtag_ptap/doc/interface.adoc` | Fragment; anchor `[[ptap-interface]]` |
| `IP/stap/index.adoc` | `ip/pages/jtag_stap/doc/index.adoc` | Page: JTAG STAP |
| `IP/stap/architecture.adoc` | `ip/pages/jtag_stap/doc/architecture.adoc` | Fragment |
| `IP/stap/interface.adoc` | `ip/pages/jtag_stap/doc/interface.adoc` | Fragment |

### Cross-trigger IP files (10: CTN ×4, CTP ×3, CTM ×3)

| Canonical source | Staged destination | Role |
|---|---|---|
| `IP/ctn/index.adoc` | `ip/pages/cross_trigger_network/doc/index.adoc` | Page: Cross Trigger Network |
| `IP/ctn/architecture.adoc` | `ip/pages/cross_trigger_network/doc/architecture.adoc` | Fragment |
| `IP/ctn/interface.adoc` | `ip/pages/cross_trigger_network/doc/interface.adoc` | Fragment |
| `IP/ctn/memmap.adoc` | `ip/pages/cross_trigger_network/doc/memmap.adoc` | Fragment: **CTN owns CTM and CTP register maps** |
| `IP/ctp/index.adoc` | `ip/pages/cross_trigger_port/doc/index.adoc` | Page: Cross Trigger Port |
| `IP/ctp/architecture.adoc` | `ip/pages/cross_trigger_port/doc/architecture.adoc` | Fragment |
| `IP/ctp/interface.adoc` | `ip/pages/cross_trigger_port/doc/interface.adoc` | Fragment |
| `IP/ctm/index.adoc` | `ip/pages/cross_trigger_matrix/doc/index.adoc` | Page: Cross Trigger Matrix |
| `IP/ctm/architecture.adoc` | `ip/pages/cross_trigger_matrix/doc/architecture.adoc` | Fragment |
| `IP/ctm/interface.adoc` | `ip/pages/cross_trigger_matrix/doc/interface.adoc` | Fragment |

**Register ownership:** `IP/ctn/memmap.adoc` includes both the CTM register
map (`ip:partial$cross_trigger_matrix/regs/gen/html/cross_trigger_matrix.html`
for HTML; `../../cross_trigger_matrix/regs/gen/adoc/cross_trigger_matrix.adoc`
for PDF) and the CTP register map. CTM and CTP individual pages must not
re-include their own register maps.

---

## 5. Staging contract

### What stage-docs.sh must change for SMU

```
SUBSYSTEMS="smc sep dtp"   →   SUBSYSTEMS="smc sep dtp smu"
MODULES="ROOT smc sep dtp ip"  →  MODULES="ROOT smc sep dtp smu ip"
```

The `clean()` function hard-codes `for m in smc sep dtp ip`. Adding `smu` to
`MODULES` does not automatically add it to `clean()` — that loop must also be
updated. `PORT_TABLE_SYS` already contains `smu`; no change needed.

Image staging uses the `MODULES` list via `stage_module_assets`. Adding `smu`
to `MODULES` will create `smu/assets/images/` and populate it from the
aggregated `doc/assets/` tree — no separate image-staging change required.

Changes to `stage-docs.sh` are shared across all documentation products.
After any change: rebuild the Integrator Guide and verify it still exits 0.

### Fragment and DV exclusion

`stage_adoc_tree` copies **all** `.adoc` files from a source directory tree
into `<mod>/pages/`. Files that must not become standalone pages (fragments,
DV content) require explicit handling:

| File | Action |
|---|---|
| `hw/sys/smu/doc/crossbar-table.adoc` | Copy explicitly to `smu/partials/`; exclude from `stage_adoc_tree` path, or stage only the non-fragment files |
| `hw/sys/dtp/doc/defines.adoc` | Exclude from staging; source preserved at `hw/sys/dtp/doc/defines.adoc`; migrate content to DV guide |
| Architecture/interface fragments under `hw/ip/*/doc/` | Currently staged into `ip/pages/` by the IP loop — acceptable if they have `= Title`; fragments-without-title need `= Title` added |

The fixture at `/tmp/claude-1000/task-002b/fixture/` demonstrates the three
routing outcomes (page, partial, excluded DV) with explicit staging logic and
clean/verify checks. Run `bash stage.sh` to reproduce.

---

## 6. URL and anchor compatibility

Old URLs include fragment IDs. Both the old anchor and any new destination
anchor must exist at their respective locations.

| Old URL | Old anchor | New page | New anchor | Action |
|---|---|---|---|---|
| `architecture.html#smu-subsystem-overview` | `[[smu-subsystem-overview]]` | `smu/index.html` | `[[smu-subsystem-overview]]` | Add compat anchor at top of SMU index |
| `architecture.html#smu-axi-crossbar` | `[[smu-axi-crossbar]]` | `smu/index.html` | `[[smu-axi-crossbar]]` | Move section; keep compat anchor in architecture.adoc |
| `dtp/index.html#debug-test-ports` | `[[debug-test-ports]]` | `dtp/index.html` | `[[debug-test-ports]]` | Keep anchor at same page — no change needed |
| `dtp/jtag.html#dtp-jtag-integration` | `[[dtp-jtag-integration]]` | `dtp/jtag.html` | `[[dtp-jtag-integration]]` | Keep anchor at same page |
| `ip/jtag_ptap/doc/index.html#jtag-ptap` | `[[jtag-ptap]]` | same | same | Keep anchor — no URL change |
| `ip/jtag_ptap/doc/architecture.html#ptap-architecture` | `[[ptap-architecture]]` | same | same | Keep anchor |
| `ip/jtag_stap/doc/index.html#jtag-stap` | `[[jtag-stap]]` | same | same | Keep anchor |
| `ip/cross_trigger_network/doc/index.html#cross-trigger-network` | `[[cross-trigger-network]]` | same | same | Keep anchor |
| `ip/cross_trigger_port/doc/index.html` | — | same | — | No existing anchor; add `[[cross-trigger-port]]` |
| `ip/cross_trigger_matrix/doc/index.html` | — | same | — | No existing anchor; add `[[cross-trigger-matrix]]` |

**Prototype proof:** The 002b prototype demonstrates the `[[smu-subsystem-overview]]`
compatibility anchor. HTML: `id="smu-subsystem-overview"` present on `smu/index.html`.
PDF: named destination `smu-subsystem-overview` confirmed by `pdfinfo -dests`.

---

## 7. Prototype and fixture evidence

### 002b prototype

Location: `/tmp/claude-1000/task-002b/proto/`, HEAD `e43a607`.

Source files committed (no build output in git):

```
doc/modules/ROOT/nav/nav.adoc         ← single nested nav file
doc/modules/ROOT/pages/index.adoc
doc/modules/smu/pages/index.adoc      ← [[smu-subsystem-overview]] compat anchor
doc/modules/smu/partials/crossbar-table.adoc
doc/modules/dtp/pages/index.adoc      ← [[debug-test-ports]] compat anchor
doc/modules/dtp/pages/jtag.adoc       ← [[dtp-jtag]] target
doc/modules/dtp/pages/cross-trigger.adoc  ← [[dtp-ctn]] target; CTN reg stub
doc/modules/dtp/partials/ctn-reg-stub.adoc
doc/modules/dtp/assets/images/dtp_arch.svg  ← illustrative SVG, no text fallback
book.adoc                             ← PDF assembly (leveloffset, no tag::body)
```

### Build commands

```bash
cd /tmp/claude-1000/task-002b/proto

# HTML (clean first)
find _build -mindepth 1 -delete 2>/dev/null; true
node /tmp/claude-1000/npm-cache/_npx/def697450dda4c3a/node_modules/@antora/cli/bin/antora \
  --log-failure-level error antora-playbook.yml

# PDF
GEM_HOME=$TMPDIR/gems $TMPDIR/gems/bin/asciidoctor-pdf -D _build/pdf book.adoc

# Check PDF annotations (must be empty)
pdfinfo -url _build/pdf/book.pdf

# Check PDF named destinations
pdfinfo -dests _build/pdf/book.pdf
```

Both exit 0, zero errors. The clean step is required; Antora does not remove
stale pages from a previous build.

### Measured results

**HTML** — 5 pages, all with correct `<title>`:

| URL | `<title>` |
|---|---|
| `index.html` | `OCAH Prototype TRM :: OCAH Prototype TRM` |
| `smu/index.html` | `System Management Unit :: OCAH Prototype TRM` |
| `dtp/index.html` | `Debug and Test Ports (DTP) :: OCAH Prototype TRM` |
| `dtp/jtag.html` | `JTAG Operation :: OCAH Prototype TRM` |
| `dtp/cross-trigger.html` | `Cross-Trigger Network :: OCAH Prototype TRM` |

**Nav depth** (measured from `data-depth` attributes in rendered HTML):

```
[2] System Management Unit
  [3] Debug & Test Ports
    [4] JTAG Operation
    [4] Cross-Trigger Network
```

DTP is at depth 3, nested under SMU. JTAG/cross-trigger are at depth 4.

**PDF TOC:** Part "System Management Unit" → Ch.1 SMU (§1.1 Composition, §1.2 AXI Crossbar) → Ch.2 DTP (§2.1 Architecture Overview, §2.2 Reading Route, §2.3 JTAG Operation, §2.4 Cross-Trigger Network).

**PDF annotations:** `pdfinfo -url` table is empty — no external file links.

**Named destinations confirmed:** `smu-axi-crossbar`, `smu-subsystem-overview`,
`debug-test-ports`, `dtp-jtag`, `dtp-ctn`, `dtp-jtag-ptap`, `dtp-jtag-stap`.

**Illustrative SVG:** `dtp_arch.svg` is a hand-authored SVG with native SVG
text elements. It renders legibly in HTML and PDF with no fallback text.
Repair of the production DTP diagram remains a later task.

### Staging fixture

Location: `/tmp/claude-1000/task-002b/fixture/`. Run `bash stage.sh`.

Demonstrates: `hw/sys/smu/doc/index.adoc` → `staged/modules/smu/pages/` (page);
`hw/sys/smu/doc/crossbar-table.adoc` → `staged/modules/smu/partials/` (partial);
`hw/sys/smu/dv/defines.adoc` → excluded (DV content, not staged);
`hw/sys/smu/assets/smu_block.svg` → `staged/modules/smu/assets/images/` (image).

Both exclusion checks exit 0 (verified by script `PASS:` output).
