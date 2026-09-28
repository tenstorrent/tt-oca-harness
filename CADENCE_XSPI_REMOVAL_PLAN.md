# Cadence / xSPI Reference Removal Plan — SEP ROM

Status: proposal. Survey against `inmcm/integrate_oca_boot_manifest_clean`
@ `7831b7973`, 2026-09-15.

**Goal.** Remove every reference to *Cadence* and *xSPI* from the SEP ROM code
base. **Explicitly not a goal:** removing the transport option or the driver
override path. The weak stub in `src/sep_spi.c` and the
`NONFREE_BOOTCODE_SOURCES` hook are **preserved by design** so a third-party
memory-mapped-flash driver can still be linked in.

Survey scope: tracked files in this repo. Excluded — `prod/build/*` artifacts,
the `tt-oca-manifest` submodule, the `tt-oca-harness-model` submodule (§7), and
the stale `.claude/worktrees/doc-open-questions` copy.

---

## 1. Headline: in ROM code this is a comment-only change

**All 16 vendor references in the ROM are comments.** No identifier, macro,
filename, symbol or build variable under `hw/sys/sep/bootrom/prod/` contains
`cadence`, `cdns` or `xspi`. The ROM also touches **zero** Cadence registers —
`OCH_SEP_CDNS_*` has no references in `src/` or `include/`.

Consequences worth planning around:

- The ROM-side scrub **cannot change behaviour**. The compiled output must be
  byte-identical, and §9 makes that the acceptance gate rather than a test pass.
- It needs **no DV time**. The ~14h `rom_fw` group is not on the critical path
  for the code portion; run it once before merge as a formality.
- The real work is `hw/sys/sep/doc/rom.adoc` (14 refs, including a whole section
  and two PlantUML branches), not the C.

Total: **16 ROM-code comments + 14 doc refs + 5 VP-harness comments = 35 sites
across 11 files**, plus 2 dead macros in SEP DV firmware (§6). §5 carries the
verified grep that reproduces exactly this count.

---

## 2. What is preserved (the requirement, stated so no one "tidies" it away)

| Kept | Why it must stay |
|---|---|
| `src/sep_spi.c` — all 5 `__attribute__((weak))` symbols | The link seam a third-party driver overrides. Deleting it removes the integration path. |
| `include/sep_spi.h` — `spi_set_rotate`, `spi_init`, `spi_reinit`, `spi_primary_tlv_failed`, `spi_set_sysclk` | The ABI a third-party driver implements. Signatures do **not** change. |
| `NONFREE_BOOTCODE_SOURCES` (Makefile) + `$(BUILD_DIR)/sep_spi.o` in `OBJS` | The injection mechanism. Its comment gets **generalized**, not deleted. |
| `BOOT_SPI_CONTROLLER_OT` and **both** branches of `boot_flash.h` / `oca_boot.c` / `rom_main.c` | The two-transport selection is the feature. Only the prose describing it changes. |
| `include/spi_tlv.h` | Contains **zero** vendor references (it never names Cadence). It is unreferenced today, but it is the natural config contract for a memory-mapped driver. Leave it; retiring dead code is a separate question. |
| Slot `+0x0000` SPI-configuration-TLV region in the flash layout | Part of the flash contract producers honour. Only its *description* is de-vendored. |
| `tools/dv/check_no_vendor_paths.yaml` `/vendor_ip/cadence` entry | A **guard against** vendor IP paths, not a reference. See §5. |

---

## 3. Terminology

### The forced constraint: "XIP" stays

`SEP_SPI_BASE` and `SEP_SPI_MAX_SIZE` are defined from **RDL-generated** names at
5 sites — `OCH_SEP_TOP_SEP_EXTERNAL_XIP_REGION_BASE_ADDR` and `..._SIZE`
(`sep_dma.c:34,37`, `boot_flash.h:93,96`, `oca_boot.c:48`). "XIP" therefore
cannot be removed from ROM code without renaming the RDL region, which is a
hardware change outside ROM scope.

That is fine, and it resolves the naming cleanly: **XIP is not a vendor term.**
It is "eXecute In Place" — a generic description of a memory-mapped flash
window, distinct from xSPI (the JEDEC/Cadence controller interface). Use it as
the neutral name for the transport.

> If "XIP" must also go, that is an RDL rename of `SEP_EXTERNAL_XIP_REGION`
> first, and this plan becomes downstream of it. Flagging rather than assuming.

### Substitutions

| Current | Replacement |
|---|---|
| "Cadence xSPI" / "Cadence xSPI (octal) controller" | "memory-mapped (XIP) flash controller" |
| "the Cadence path" | "the XIP path" |
| "the Cadence controller reads" | "the XIP driver reads" |
| "No Cadence registers are touched" | "No external controller registers are touched" |
| "the real Cadence xSPI driver (companion-supplied)" | "a third-party XIP controller driver (overlay-supplied)" |
| "has NO Cadence xSPI" | "fits no memory-mapped flash controller" |
| "Cadence path only: PHY tuning parameters" | "XIP path only: driver-defined tuning parameters" |
| "Cadence xSPI controller \| ctrl `0x20002000` region" | "External SPI flash controller (vendor IP) \| `0x20002000` region" |
| `===== Cadence xSPI Path` | `===== Memory-Mapped (XIP) Path` |

Keep "OpenTitan" / "OT" throughout — it is an open-source implementation the
tree already depends on by name, and it is not in scope.

---

## 4. Site-by-site edits

### A. ROM code — 16 comments, `hw/sys/sep/bootrom/prod/`

| File:line | Note |
|---|---|
| `src/sep_spi.c:6,7,12,14,34` | The file header is the main one. Rewrite it to describe the **stub's contract** — a weak default that reports "no controller fitted", overridden by an overlay-supplied driver — with no vendor named. This is the file a third-party integrator reads first, so it is worth writing properly rather than search-replacing. |
| `include/sep_spi.h:15` | `// Initialise SPI (Cadence xSPI).` → `// Initialise the memory-mapped (XIP) flash controller.` |
| `include/boot_flash.h:11` | Transport-list bullet. |
| `include/boot_flash.h:35` | Slot-geometry prose: "the SPI configuration TLV the Cadence controller reads". |
| `include/boot_flash.h:91` | `/* Cadence xSPI XIP window ... */` → `/* XIP window (memory-mapped flash), matching sep_dma.c. */` |
| `include/boot_flash.h:199` | Bounds-gate `#else` comment. |
| `src/oca_boot.c:82,93` | `manifest_src_read` contract comment — describes the offset-vs-absolute-address split between transports. Reword carefully; this comment carries the security reasoning for the bounds gate (SEP-ROM-SPI-010). |
| `src/rom_main.c:320` | "The Cadence path caches a PHY-tuning TLV…" → "The XIP path caches a driver-defined tuning TLV…". |
| `src/sep_dma.c:31` | `// Cadence xSPI direct flash access / XIP window` → `// Direct (memory-mapped) flash access / XIP window`. |
| `Makefile:10` | Header comment: keep the point (SPI is stubbed because the OSS DUT fits no such controller), drop the vendor. |
| `Makefile:61` | `# 0 = Cadence xSPI (default, memory-mapped XIP)` → `# 0 = memory-mapped XIP controller (default)`. |

Also reword, though they name no vendor, because they will read as stale next to
the above: `include/sep_ot_spi.h:7,19`.

### B. ROM specification — `hw/sys/sep/doc/rom.adoc`, 14 refs

This is the bulk of the work and the part a reader actually consumes.

- **L207, L259, L261–262** — address-map / transport-option rows.
- **L756, L825, L895** — PMP tables. ⚠ **L825 and L895 already contradict each
  other today**: L825 lists "xSPI controller/XIP windows" as `RW-`, L895 says the
  XIP window "ha[s] no entry". Resolve against the actual PMP programming while
  you are in there; do not propagate whichever line you edit first.
- **L1236, L1241** — boot-flash-layout table, "Cadence path only" TLV rows. ⚠
  This table is **normative for image producers**; the `configs/oca_*_image.yaml`
  offsets must still agree. Re-read the section whole, do not line-edit.
- **L1296–1298** — the `===== Cadence xSPI Path` section: retitle and rewrite.
- **L1318, L1333** — two PlantUML `else (Cadence xSPI)` / `else (Cadence)`
  branch labels. Rebuild the diagrams after editing.
- **L2502** — transport reinit note.

### C. VP harness (tracked here) — 5 refs

`virtual_platform/Makefile:167,170`, `virtual_platform/sepvp/paths.py:36,39`,
`virtual_platform/sepvp/pytest_plugin.py:174`.

These explain *why* the VP needs `BOOT_SPI_CONTROLLER_OT=1` — the VP models only
the OpenTitan SPI host. That reason survives de-vendoring, so **rewrite, don't
delete**, or the next reader loses why those paths point at `build_ot/`.

### D. SEP DV — nothing to do

`hw/sys/sep/dv/testlists/rom_fw.toml`, `sep_sim_cfg.toml` and
`cocotb/tests/cpu/sep_rom_ot_dma_boot_test.py` discuss "the weak `sep_spi.c`
stub" and `BOOT_SPI_CONTROLLER_OT` but **name no vendor**. They stay accurate
under this plan — the stub is being kept. No edits.

---

## 5. The grep trap (read before running a sweep)

`grep -ri cadence` over this tree produces **false positives that must not be
renamed**:

1. **The English word.** "timing cadence", "reseed cadence", "valid cadence" —
   `hw/sys/sep/dv/cocotb/env/sep_entropy_golden.py:334,338,347`,
   `sep_decor_golden.py:245,271`,
   `hw/sys/sep/dv/fw/tests/sep_aes_mb_stream_test/sep_aes_mb_stream_test.c:13`.
   **Leave all 6 alone.**
2. **`tools/dv/check_no_vendor_paths.yaml`** — the `/vendor_ip/cadence` forbidden
   prefix is a lint **guard**. Removing it weakens the OSS-hygiene check. **Keep.**
3. **Scope, not cleverness.** A repo-wide word-boundary regex was tried and
   rejected: `cadence[ -]?(xspi|controller|path|driver|...)` silently **misses
   "Cadence XIP window"** (3 sites in `rom.adoc`), and a repo-wide sweep returns
   ~177 hits dominated by the out-of-scope submodule (§7). Scope the plain grep
   to the files in play instead — it is exact and it is auditable.

Verified recipe. This returns **35** today (16 + 14 + 5) and must reach **0**:

```bash
grep -rn -i -e cadence -e cdns -e xspi \
  hw/sys/sep/bootrom/prod/src \
  hw/sys/sep/bootrom/prod/include \
  hw/sys/sep/bootrom/prod/Makefile \
  hw/sys/sep/doc/rom.adoc \
  virtual_platform/Makefile virtual_platform/sepvp \
  | grep -v tt-oca-manifest | wc -l
```

The ROM-code subset alone (first three paths) is **16** and must reach 0.

---

## 6. Adjacent: two dead Cadence identifiers in SEP DV firmware

`hw/sys/sep/dv/fw/tests/common/sep_smu_axi_extension_decode_protocol.h`:

- `:28` `#define SMU007_CDNS_BOUND_CYC 2000000`
- `:41` `#define SMU007_CDNS_OK 0x00720002`

Unlike everything in §4, these are **identifiers, not comments** — the only real
Cadence identifiers in SEP software. **Both are defined and never used anywhere
in the tree**, so they are free to rename (`..._XIP_BOUND_CYC` / `..._XIP_OK`,
matching the neighbouring `SMU007_XIP_OFF` / `SMU007_SEL_XIP`) or simply delete.

Recommend renaming rather than deleting: the surrounding `SMU007_*` block reads
as a numbered bring-up protocol, and a gap in it is more confusing than a
renamed constant. Either way it is a one-line commit with no users to update.

---

## 7. Out of scope

- `hw/common/dv/fw/sep.h` — `OCH_SEP_CDNS_SPI_CTRL__*`. **RDL-generated** and
  `#ifdef`-guarded; it regenerates. Changing it is an RDL/RTL decision.
- `hw/top/sep_ip_integration.sv:678-679` — `cdns_xip_axi_req/resp`. RTL.
- **`hw/sys/smc/**` — a much larger, unrelated Cadence footprint.** The SMC ROM
  carries a Cadence **I3C** driver: 33 refs in
  `bootrom/prod/drivers/src/i3c_hci_driver.c`, 20 in
  `dv/fw/common/occp/i3c_controller_driver.c`, 3 in its `Makefile`, 2 in
  `lib/src/occp.c` — plus **4,685 `CDNS_I3C_*` symbols in the generated
  `bootrom/prod/registers/smc_top_regs.h`**. Different IP (I3C, not xSPI),
  different subsystem, and **zero xSPI references in the SMC ROM**.
  Explicitly **out of scope** — but anyone handed "remove Cadence references"
  will find it, so it needs its own decision and its own ticket. Note most of the
  hand-written ones are *comparative* ("== Cadence `I3C_Start`", "same signatures
  as the Cadence driver") documenting an HCI driver written as a counterpart to a
  Cadence one; erasing the comparison would cost real explanatory value.
- `hw/sys/smu/**` — sim cfgs, `constraints.sdc`. Same treatment if wanted.
- `hw/common/dv/vip/ocah_spi_vip/` + `hw/common/dv/docs/vip-catalog.adoc` —
  `OcahSepSpiFlash` keeps a legacy xSPI pin shape. VIP capability, separate call.
- **`virtual_platform/tt-oca-harness-model` (submodule)** — a separate repo
  carrying its own bootcode snapshot (`boot_flash.h`, `sep_spi.c/.h`,
  `rom_main.c:333`, plus a `manifest_load.c` with 4 more `#if` sites this tree
  folded into `oca_boot.c`) **and ~20 `*xspi*` DV test directories**
  (`xspi_flash_read_test`, `spi_sanity_cadence`, `spi_xspi_dma_test`, …). By file
  count this is the **larger half of the whole job** and needs its own PR. Not
  blocked by this one; its README (L186–193) goes stale only if defaults change,
  which this plan does not do.

---

## 8. Optional follow-up — a real bug found during the survey

Not part of the reference scrub. Recorded so it is not lost.

`src/sep_dma.c:96` permits `[SEP_SPI_BASE, +SEP_SPI_MAX_SIZE)` — the 256 MiB XIP
window at `0x3000_0000` — as a legal secure-DMA **source** in **every** build,
including the two OpenTitan builds that ship today and have no XIP window at all.
It should be conditional on the XIP transport being selected:

```c
#if !BOOT_SPI_CONTROLLER_OT
    /* XIP source is only legal when the memory-mapped transport is fitted. */
#endif
```

This is a **behaviour change** (a permission reduction on the secure DMA), so it
must not ride along in a comment-only commit. Own commit, own `/security-review`,
and `sep_rom_ot_dma_boot_test` as the direct exercise — it passing proves the
removed clause was not being relied on.

---

## 9. Verification

The acceptance gate for §4A is **not** a test pass — it is that nothing changed:

```bash
cd hw/sys/sep/bootrom/prod
make all && make ot-toolchain-images && make ot-pio-toolchain-images
# against pre-change copies:
cmp build/boot_rom.vmem      ../prod.orig/build/boot_rom.vmem
cmp build_ot/boot_rom.vmem   ../prod.orig/build_ot/boot_rom.vmem
cmp build_ot_pio/boot_rom.vmem ../prod.orig/build_ot_pio/boot_rom.vmem
```

Three identical `.vmem` files prove the C edits were comment-only. If any
differs, something other than a comment was touched — find it before going on.

Note the `BUILD_FLAGS` stamp mechanism: dropping or changing a recorded flag
forces a full rebuild by design. This plan changes no flags, so an incremental
build is expected; a surprise full rebuild means a flag moved.

| Gate | Command | Applies to |
|---|---|---|
| Vendor terms → 0 (35 today: 16 code + 14 doc + 5 VP) | §5 recipe | §4A–C |
| Three `.vmem` byte-identical | above | §4A |
| Docs build | Antora ROM/TRM playbook | §4B |
| VP still launches | `virtual_platform` pytest smoke | §4C |
| DV formality before merge | `rom_fw` group (~14h — stage it; build breakage fails in seconds) | all |
| Security review | `/security-review` | §8 only |

Per the DV long-run playbook: if a `rom_fw` run looks hung, measure the
simulated-time rate before killing it — slow is not hung.

Prereq, once per clone: `git submodule update --init
hw/sys/sep/bootrom/prod/tools/tt-oca-manifest`.

---

## 10. Commit sequence

```
1. rom/sep: Describe the boot-flash transports without naming a vendor     (§4A, 16 comments)
2. doc/sep: Retitle the ROM spec's XIP transport section and address map   (§4B, 14 refs)
3. vp: Drop the vendor name from the SEP VP build-selection comments       (§4C, 5 refs)
4. dv/sep: Rename the unused SMU007 Cadence bring-up constants             (§6, 2 macros)
```

Commits 1–4 are independent, carry no behaviour change, and can land in any
order or as one PR. The §8 DMA fix is deliberately **not** in this list — it is a
separate change with a separate review.

`AGENTS.md` asks that anything materially affecting it lands in the same PR;
check it for SPI-transport claims before opening.
