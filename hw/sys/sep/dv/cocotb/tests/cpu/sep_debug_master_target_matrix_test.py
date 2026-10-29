# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The core JTAG TAP and DMI path: enable gates, the debug-module system bus and the debug reset.

The leaf drives the core TAP pins (bench hook, ``jtag_bench_own_i`` = 1) through
``env/sep_jtag_dmi`` on the shared ``OcahJtagMasterDriver`` and reads the DMI
data from ``jtag_tdo_o``. It drives ``dmi_core_enable_i`` and
``dmi_uncore_enable_i`` (bench hooks); the bench holds ``dmi_uncore_rdata`` at 0.
One module serves two testlist entries, both on the full-CPU build, because the
EL2 debug module exists only in the full ``sep_cpu``:

* Entry C (``cpu`` run mode, ``sep_debug_master_target_matrix_test``): the core
  runs a one-instruction spin loop at the boot ROM base (``jal x0, 0``, written
  into the ROM macro by backdoor before ``rst_ni`` rises). Steps 1 to 4 and 9 to
  12 of the procedure.
* Entry S (``no_cpu`` run mode on the ``default`` target,
  ``sep_debug_master_target_matrix_test_sba``, ``+sep_ext_port_responder``): the
  core is held by ``mpc_reset_run_req`` = 0 and the bench LSU master on the LSU
  force splice is the independent register path. Steps 1 to 8, the three
  local-alias legs, then the reset-controller and SPI host targets, the entropy
  pool, the extension port, the boot ROM and ICCM, the AP and STEE remaps, and
  a leg of six targets: an HMAC register in reset and two system registers
  (graded), and three targets with no stated response (``OBS-DBG-SBA``).

Checks:
  CHK-DTMCS     : the first ``dtmcs`` read after the TAP reset is 0x0000_0071:
                  version 1, abits 7, dmistat 0, idle 0 (EL2 Programmer's
                  Reference Manual section 11.1.1.2, Table 11.3, linked from
                  ``hw/sys/sep/doc/cpu.adoc``).
  CHK-DMI-GATE  : a write of ``dmcontrol.dmactive`` = 1 with
                  ``dmi_core_enable_i`` low does not land: after the enable
                  rises ``dmactive`` reads 0 (``hw/sys/sep/doc/port_table.adoc``,
                  ``dmi_core_enable_i``). The DTM request tap before the core
                  and uncore mux (``dmi_req_probe_o``) shows exactly the two
                  requests the leaf issues with the enable low, one write and
                  one read at 0x10, so a write that never leaves the DTM
                  fails. Control: a write of 1 with the enable high reads
                  back 1. The read data with the enable low is logged only.
  CHK-DBG-SBA   : (entry S) for each of the nine accesses (SRAM word 0 and its
                  local alias at 32 and 64 bits, ``WDOG_BARK_THOLD``, HMAC
                  ``MSG_LENGTH_LOWER``, ``SEP_SW_DEBUG``, cold scratch word 0,
                  secure DMA ``INTR_SRC_ADDR_0[0]`` at 32 bits), and for
                  ``SW_RESET_N`` and the SPI host ``CSID`` at 32 bits, compared
                  at the full access width (field mask for a register): the
                  independent path (``sram_word0_probe_o`` or the bench LSU
                  master) reads the debug-master write value, and the value
                  before the write differs from it. The bench LSU master then
                  writes a second drawn value ``new`` that differs from the
                  write value in a graded bit and reads it back; the debug-master
                  read returns ``new`` in the one R beat on PR-DBG-SB (the lane
                  of the access) and in ``sbdata``, and the independent path
                  still reads ``new`` after it. ``sbdata`` holds the write value
                  from the write, so a read whose data never arrives fails.
                  ``sberror`` reads 0 after the write and after the read. On
                  PR-DBG-SB each access shows one write and one read record
                  with ID bits [2:1] = 0, AWSIZE = ARSIZE = log2 of the access
                  bytes, AWLEN = ARLEN = 0, one W beat whose strobes are the byte
                  lanes of the access and one R beat (``hw/sys/sep/doc/cpu.adoc``,
                  chapter introduction: AXI4, 64-bit data). A 32-bit SRAM access
                  leaves the upper half of SRAM word 0 at its value before the
                  access at every independent read. ``SW_RESET_N`` fields are RW
                  (``hw/sys/sep/regs/gen/adoc/blocks/sep_reset_ctrl.adoc:24-30``);
                  its draws keep KM held and the TRNG released (their reset
                  values) and draw the OTBN, AES, HMAC, KMAC and Adams Bridge
                  bits. ``CSID`` is one RW field of 32 bits
                  (``vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/doc/registers.md:262-264``).
                  The debug master reaches the reset controller and the SPI host
                  (``hw/sys/sep/doc/assets/sep_axi_connectivity.svg:123``, ``:142``).
  CHK-DMI-UNCORE: (entry C) with ``dmi_uncore_enable_i`` = 0,
                  ``dmi_uncore_en_o`` and ``dmi_uncore_wr_en_o`` are 0 on every
                  ``clk_i`` cycle from step 1 to the end of step 9, which holds
                  DMI reads and writes at 0x50 and 0x7F and ``dmcontrol`` reads
                  with the core enable high and low
                  (``hw/sys/sep/doc/port_table.adoc``). The DTM request tap
                  (``dmi_req_probe_o``) shows, in the same cycles, exactly one
                  read and one write request at each of 0x50 and 0x7F with the
                  core enable high and again with it low (8 requests at 0x50
                  and above), so an access that never leaves the DTM fails.
                  Control: in the window with the enable at 1
                  ``dmi_uncore_en_o`` rises for a read and a write and
                  ``dmi_uncore_wr_en_o`` for the write.
  CHK-DBG-RST   : (entry C) after a ``dbg_rstb_i`` pulse ``dmactive`` reads 0, a
                  retirement follows on the trace port, and the
                  ``sep_cpu_reset_n`` and ``sep_reset_n`` taps stay high from
                  the start of the pulse to the readback
                  (``hw/sys/sep/doc/reset_controller.adoc:45-53``, the terms of
                  ``sep_reset_n`` and ``sep_cpu_reset_n``; ``:81``,
                  ``dbg_rstb_i``). Controls:
                  ``dmactive`` reads 1 before the pulse; the ``wdt_rst_ni_i``
                  pulse of step 12 drops the ``sep_cpu_reset_n`` tap; the cold
                  reset holds the ``sep_reset_n`` tap low until its release.
  CHK-DBG-ALIAS-MOVE : (entry S) after the bench LSU master moves
                  ``SEP_LOCAL_BASE_ADDR`` to the drawn base B, a debug-master
                  access at B (32 and 64 bits) reaches SRAM word 0: graded as
                  CHK-DBG-SBA, and on the PR-DBG-IN/PR-DBG-OUT tap pair at
                  ``u_dbg_local_alias_remap`` the input address B leaves as
                  0x1000_0000 (``hw/sys/sep/doc/memory_map.adoc``, local alias;
                  ``hw/sys/sep/doc/cpu.adoc``, chapter introduction).
  CHK-DBG-ALIAS-OLD  : (entry S) with the base at B, a debug-master read and
                  write at the old alias 0xD000_0000 pass the remap unchanged:
                  the PR-DBG-OUT address equals the PR-DBG-IN address.
  CHK-DBG-ALIAS-BELOW: (entry S) the same for B - 8, just below the moved window.
                  Control of both: in the CHK-DBG-ALIAS-MOVE leg the same tap
                  pair shows a rewritten address.
  CHK-DBG-POOL-RD : (entry S) one 64-bit debug-master read of the entropy-pool
                  ``STATUS`` (``hw/sys/sep/doc/entropy_pool.adoc:34``,
                  non-destructive; ``:40-41``, one 64-bit access) shows one AR at
                  ``STATUS`` with ARSIZE 3 and one R beat on PR-DBG-SB,
                  ``sberror`` 0, the bench LSU 64-bit reads of ``STATUS`` before
                  and after it agree, and ``sbdata`` equals both on the
                  ``STATUS`` fields
                  (``hw/sys/sep/doc/assets/sep_axi_connectivity.svg:149``).
  CHK-DBG-POOL-WR : (entry S) one 64-bit debug-master write of a drawn word to
                  ``STATUS`` shows one AW at ``STATUS`` and one W beat on
                  PR-DBG-SB, and its B beat answers SLVERR
                  (``hw/sys/sep/doc/entropy_pool.adoc:38-39``); ``sberror`` is
                  not 0 (RISC-V debug ``sbcs.sberror``, EL2 debug module, PRM
                  cited at ``hw/sys/sep/doc/cpu.adoc:23``), and the LSU read of
                  ``STATUS`` after it equals the one before it on the fields.
  CHK-DBG-EXT   : (entry S) a debug-master 64-bit read and write of a drawn word
                  of the extension window above the eFuse shim, once with the
                  bench responder set to OKAY and once to SLVERR. Each access
                  leaves once on PR-EXT at the issued address (AR with ARLEN 0
                  and ARSIZE 3, or AW and one W beat with the written data and
                  all strobes) (``hw/sys/sep/doc/fabric.adoc:162-164``), and the
                  PR-DBG-SB R or B beat carries the code the port returned, and
                  the R beat its word (``hw/sys/sep/regs/gen/adoc/memory_map.adoc:86``
                  "Adopter-defined", ``doc/trm/src/memory_map.adoc:111-112``: the
                  adopter's implementation answers). ``sberror`` is 0 for OKAY
                  and not 0 for SLVERR; an OKAY read returns the word in
                  ``sbdata``. The reply on PR-EXT-RSP is the bench value (CTL).
  CHK-DBG-NC    : (entry S) a debug-master 64-bit read and write at the boot ROM
                  base and at a drawn ICCM word: each shows its request on
                  PR-DBG-SB (one AR, or one AW and one W, at the issued address)
                  and its returned R or B beat, while PR-ROM and PR-XBAR-TCM take
                  no handshake (``hw/sys/sep/doc/assets/sep_axi_connectivity.svg``:
                  the ``cpu_tcm`` row, ``:93-98``, has only the DMA dot, and the
                  boot ROM row, ``:159-162``, the IFU and LSU dots). Positive
                  probes on the same tap objects, before the graded accesses and
                  outside every window: an LSU read of the boot ROM base gives a
                  PR-ROM request, and a secure DMA copy of one SRAM word to the
                  ICCM word gives a PR-XBAR-TCM AW (the DMA reaches ``cpu_tcm``,
                  ``:98``); each count must be at least 1. The response
                  code, ``sberror`` and read data are logged only
                  (``OBS-DBG-NOTCONN``): the specification states no response.
  CHK-DBG-REMAP : (entry S) with AP region i and STEE region j programmed (valid,
                  drawn offset O at or above 4 GiB) and an outbound filter pair
                  over each remapped word, a debug-master 64-bit write and read
                  of word a of each region leave once on PR-OUT at
                  ``{O[55:19], a[18:0]}`` with AxUSER 0 in all 12 bits (``OTHERS``)
                  and NS 1 (AP) or the inverse of bit 55 of the remapped address
                  (STEE), and the W beat carries the written word
                  (``hw/sys/sep/doc/fabric.adoc:178-181``, ``:314-315``,
                  ``:320``). The responses come from the bench outbound responder
                  and are logged only.
  CHK-DBG-SBA-ISO: (entry S) with ``hmac_sw_rst_n`` written 0, a debug-master
                  4-byte read and write of HMAC ``MSG_LENGTH_LOWER`` each show
                  one R or B beat on PR-DBG-SB that answers SLVERR, the R beat
                  carries 0x1501A7ED in the 32-bit lane of the access, and
                  ``sberror`` is not 0 (``hw/sys/sep/doc/reset_controller.adoc:139-141``:
                  new transactions on an isolated path complete with SLVERR and
                  that read data; the HMAC host path is isolated, ``:153``;
                  the debug master reaches ``sep_crypto``,
                  ``hw/sys/sep/doc/assets/sep_axi_connectivity.svg:129``).
  CHK-DBG-SBA-REG: (entry S) 64-bit debug-master read and write of
                  ``START_ADDR`` of a disabled inbound filter entry and of
                  ``DEMOTE_2``: each R or B beat answers OKAY and ``sberror``
                  reads 0; the read returns in ``sbdata`` the value the bench LSU
                  master read before the instance; after the write the bench LSU
                  master reads the written value on the ``start_addr`` field,
                  rounded to the granule only when START and END share one
                  (``hw/ip/axi_filter/regs/filter_ctrl.rdl:94-102``), and for
                  ``DEMOTE_2`` the value before OR the drawn bit (every field
                  ``onwrite = woset``,
                  ``hw/sys/sep/regs/blocks/sep_lifecycle_ctrl/sep_lifecycle_ctrl.rdl:22-45``).
                  The debug master reaches the system CSRs and ``sep_crypto``
                  (``hw/sys/sep/doc/fabric.adoc:139-140``;
                  ``sep_axi_connectivity.svg:129``, ``:136``).
  CHK-DBG-AXPROT: (entry S) every AR and AW of each debug-master instance on
                  PR-DBG-SB carries AxPROT 0b001
                  (``hw/sys/sep/doc/cpu.adoc``, table ``sep-cpu-axprot-table``).

The expected values are the drawn write values, the addresses of the generated
register map and the rules of the specification; no expected value is read
from the DUT except the independent-path reads of a live register. The
responses of the accesses outside the moved window (OLD, BELOW) and of the
PIC base, the hole word and the word past the secure DMA map are logged only;
the specification states no debug-master response for them.

FCOV: each graded instance runs in its own owner window, opened before its
first access. The cells of the debug points and of the DMI points that the
instance hits are held by the sampler; the leaf releases the cells its checks
grade (``set_dbg_sba_pass``) and the debug AxPROT values
(``set_dbg_axprot_pass``) only after every check of the instance passed, then
closes the window. A FAIL closes the window first, and no later window opens.

Randomization (``SepSeededRng`` from the run seed): the order of the seven
targets, the size order of each SRAM target, every write value (redrawn while
it equals the value before the write), the LSU value ``new`` of each access
(redrawn while it equals the write value in the graded bits), the set-up value
of SRAM word 0, the moved base B (16 MiB aligned, 0xD100_0000 to 0xEF00_0000,
so the reset alias and B - 8 are below the moved window and every moved alias
is below 2**32) and the size order of the moved-alias leg. After the alias legs
the leaf draws, in this order: the reset-controller and CSID values, the pool
write word, the extension word and its reply and write words, the ICCM word, the DMA
probe word,
the write words of the boot ROM and ICCM legs, and for AP then STEE the region,
the word offset, the remap offset and the write word; then for the logged leg
the hole word, the disabled inbound filter entry, the DEMOTE_2 rsvd bit and
the write word of each target. Every leg runs on every seed. Entry C uses
only the uncore DMI write data, which no check grades; both entries run one
seed per regression.

VCS only (``tools = ["vcs"]``), ``+skip_fuse_sense``. The leaf fails on a build
without the full ``sep_cpu``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_common import (
    FILTER_ADDR_MASK,
    OTHERS_SOURCE_ID,
    OUTBOUND_MBX_MAGIC,
    RESP_OKAY,
    RESP_SLVERR,
    granule8,
    outbound_ns,
)
from env.sep_fabric_tap import SepFabricTap, TapMark, check_axprot
from env.sep_fcov_gate import (
    close_graded_window,
    dbg_sba_bits,
    open_graded_window,
    set_dbg_axprot_pass,
    set_dbg_sba_pass,
)
from env.sep_field_compare import field_compare, lane32
from env.sep_filter_model import FilterEntry
from env.sep_jtag_dmi import (
    DM_DMCONTROL,
    DMCONTROL_DMACTIVE,
    IR_DMI,
    IR_WIDTH,
    PIN_MAP,
    DmiError,
    SepJtagDmi,
)
from env.sep_seeded_rng import SepSeededRng
from ocah_jtag_vip import OcahJtagMasterDriver
from sep_base_test import sep_base_test
from sep_reg_meta import AP_OUTPUT_REMAP_CTRL_0, SEP_RESET_CTRL, RegBlock, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_dma_ops import SepDmaOps, SepMemWords
from seq_lib.sep_fabric_csr_bank_seq import (
    AP_BASE,
    DBW_LSB,
    DBW_MASK,
    F_ALLOW_BURST,
    F_ENTRY_ENABLED,
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    INFILT_BASE,
    INFILT_ENTRIES,
    REMAP_ATTRS,
    REMAP_STRIDE,
    STEE_BASE,
)
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_outbound_remap_seq import (
    AP_REGION_BASE,
    IDX_START,
    N_REGIONS,
    STEE_REGION_BASE,
)
from seq_lib.sep_wdt_aon_seq import WDT_CDC_CLKS

TEST = "sep_debug_master_target_matrix_test"

_CPU_CTRL = RegBlock("SEP_CPU_CTRL")
_WDT = RegBlock("WDT_TIMER")
WDT_BARK = _WDT.addr("WDOG_BARK_THOLD")
_HMAC = RegBlock("HMAC")
_COLD = RegBlock("SEP_SCRATCH_COLD")
_DMA = RegBlock("SECURE_DMA")
_SPI = RegBlock("SPI_CONTROLLER")
_POOL = RegBlock("SEP_ENTROPY_POOL")

ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
SRAM_WORD = sym("SEP_SRAM_MEM_BASE_ADDR")  # SRAM word 0: sram_word0_probe_o
# hw/sys/sep/doc/memory_map.adoc: 0xD000_0000 aliases 0x1000_0000; the alias of a
# direct address is the window base plus its offset from 0x1000_0000.
ALIAS_TARGET = 0x1000_0000
LOCAL_BASE_ADDR = _CPU_CTRL.addr("SEP_LOCAL_BASE_ADDR")
LOCAL_BASE_RESET = _CPU_CTRL.reset("SEP_LOCAL_BASE_ADDR")
OLD_ALIAS = LOCAL_BASE_RESET + (SRAM_WORD - ALIAS_TARGET)
if SRAM_WORD % 8:
    raise RuntimeError("SRAM word 0 is not 8-byte aligned")

# Moved window base B (16 MiB aligned in [MOVED_LO, MOVED_HI]).
MOVED_LO = 0xD100_0000
MOVED_HI = 0xEF00_0000
MOVED_ALIGN = 0x0100_0000
if MOVED_LO <= OLD_ALIAS:
    raise RuntimeError("the reset alias of the SRAM word is not below the moved window")

# The five register targets, 32-bit only: (name, address, RDL field mask of the word).
REG_TARGETS = (
    ("WDOG_BARK_THOLD", _WDT.addr("WDOG_BARK_THOLD"), _WDT.mask("WDOG_BARK_THOLD")),
    ("HMAC_MSG_LENGTH_LOWER", _HMAC.addr("MSG_LENGTH_LOWER"), _HMAC.mask("MSG_LENGTH_LOWER")),
    ("SEP_SW_DEBUG", _CPU_CTRL.addr("SEP_SW_DEBUG"), _CPU_CTRL.mask32("SEP_SW_DEBUG")),
    ("SCRATCH_COLD_0", _COLD.addr("SCRATCH_0_"), _COLD.mask("SCRATCH_0_")),
    (
        "DMA_INTR_SRC_ADDR_0_0",
        sym("SECURE_DMA_INTR_SRC_ADDR_0_0__REG_ADDR"),
        _DMA.mask("INTR_SRC_ADDR_0"),
    ),
)
SRAM_TARGETS = (("SRAM_WORD", SRAM_WORD), ("SRAM_ALIAS", OLD_ALIAS))
for _n, _a, _m in REG_TARGETS:
    if _a % 4 or (_m & 0xFFFF_FFFF) == 0:
        raise RuntimeError(f"{_n}: not a 32-bit register word")

# SW_RESET_N (hw/sys/sep/regs/gen/adoc/blocks/sep_reset_ctrl.adoc:24-30, RW
# fields). The leg draws the OTBN, AES, HMAC, KMAC and Adams Bridge bits; KM
# stays held and the TRNG released (their reset values), because a KM release
# starts the Key Manager boot, which this leaf does not set up.
SW_RESET_N = SEP_RESET_CTRL.addr("SW_RESET_N")
SW_RESET_MASK = SEP_RESET_CTRL.mask32("SW_RESET_N")
SW_RESET_DEFAULT = SEP_RESET_CTRL.reset32("SW_RESET_N")
SW_RESET_FREE = 0
for _f in ("otbn_sw_rst_n", "aes_sw_rst_n", "hmac_sw_rst_n", "kmac_sw_rst_n", "abr_sw_rst_n"):
    SW_RESET_FREE |= SEP_RESET_CTRL.field_mask("SW_RESET_N", _f)
SW_RESET_FIXED = SW_RESET_DEFAULT & (
    SEP_RESET_CTRL.field_mask("SW_RESET_N", "km_sw_rst_n")
    | SEP_RESET_CTRL.field_mask("SW_RESET_N", "trng_sw_rst_n")
)
SPI_CSID = _SPI.addr("CSID")
SPI_CSID_MASK = _SPI.mask32("CSID")
SPI_CSID_RESET = _SPI.reset32("CSID")
# The register targets after the alias legs: (name, address, RDL field mask,
# fixed bits, drawn bits or None for every bit of the access, value restored
# after the instance).
APPENDED_TARGETS = (
    ("SW_RESET_N", SW_RESET_N, SW_RESET_MASK, SW_RESET_FIXED, SW_RESET_FREE, SW_RESET_DEFAULT),
    ("SPI_CSID", SPI_CSID, SPI_CSID_MASK, 0, None, SPI_CSID_RESET),
)

# Entropy pool STATUS (hw/sys/sep/regs/gen/adoc/blocks/sep_entropy_pool.adoc:25-29).
POOL_STATUS = sym("ENTROPY_POOL_STATUS_REG_ADDR")
POOL_STATUS_MASK = _POOL.mask("STATUS")

# Extension window above the eFuse shim (hw/sys/sep/doc/fabric.adoc:162-164).
EXT_BASE = sym("SEP_EXTERNAL_REG_MAP_BASE_ADDR")
EXT_FIRST = (EXT_BASE + sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_SIZE") + 7) & ~7
EXT_LAST = EXT_BASE + sym("SEP_EXTERNAL_REG_MAP_SIZE") - 8

ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
ICCM_SIZE = sym("SEP_ICCM_MEM_SIZE")
# Liveness probe of the PR-XBAR-TCM tap: one 4-byte secure DMA copy from an SRAM
# word to the ICCM word (the DMA reaches cpu_tcm:
# hw/sys/sep/doc/assets/sep_axi_connectivity.svg:98).
DMA_PROBE_SRC = SRAM_WORD + 0x100
DMA_WORD_BYTES = 4
DMA_WIDTH_ENC = 2  # TRANSFER_WIDTH: 4-byte beats

# Targets of the step-21 leg. The specification states no debug-master response
# for PIC_BASE, HOLE and PAST (the memory-map codes are stated at the inbound
# port only), so those are logged; ISOLATED, FILT_START and LC_RSVD are graded.
PIC_BASE = sym("PIC_REG_MAP_BASE_ADDR")
HOLE_FIRST = 0x1080_4000  # unmapped words above the secure DMA register map
HOLE_LAST = 0x108F_FFF8
DMA_PAST = sym("SECURE_DMA_REG_MAP_BASE_ADDR") + sym("SECURE_DMA_REG_MAP_SIZE")
HMAC_RST_FIELD = SEP_RESET_CTRL.field_mask("SW_RESET_N", "hmac_sw_rst_n")
# A new transaction on an isolated path completes SLVERR with this read data in
# each 32-bit word (hw/sys/sep/doc/reset_controller.adoc:139-141).
ISO_DATA = 0x1501_A7ED
# Every DEMOTE_2 field is sw=rw with onwrite=woset
# (hw/sys/sep/regs/blocks/sep_lifecycle_ctrl/sep_lifecycle_ctrl.rdl:22-45), so a
# set bit stays set; that write is the last access of the leaf.
DEMOTE_2 = sym("SEP_LIFECYCLE_CTRL_DEMOTE_2_REG_ADDR")

# AP and STEE output remap (hw/sys/sep/doc/fabric.adoc:178-181, :314-315).
REMAP_OFFSET_FIELD = AP_OUTPUT_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "offset")
REMAP_VALID_FIELD = AP_OUTPUT_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "valid")
REGION_MASK = (1 << IDX_START) - 1
ADDR_BITS = 56  # the outbound address width (hw/sys/sep/doc/fabric.adoc:172-173)
# (path, region window base, remap CSR base, outbound filter pair)
REMAP_PATHS = (
    ("ap", AP_REGION_BASE, AP_BASE, (0, 1)),
    ("stee", STEE_REGION_BASE, STEE_BASE, (2, 3)),
)

# AxPROT of the debug master (hw/sys/sep/doc/cpu.adoc, table
# sep-cpu-axprot-table).
AXPROT_DBG = 0b001

# Cells each debug-master target releases after its check passes.
SBA_CELL = {
    "SRAM_WORD": "sram",
    "SRAM_ALIAS": "sram_alias",
    "MOVED_ALIAS": "sram_alias",
    "WDOG_BARK_THOLD": "wdt",
    "HMAC_MSG_LENGTH_LOWER": "hmac",
    "SEP_SW_DEBUG": "cpu_ctrl_sw_debug",
    "SCRATCH_COLD_0": "scratch_cold",
    "DMA_INTR_SRC_ADDR_0_0": "dma",
    "SW_RESET_N": "reset_ctrl_rw",
    "SPI_CSID": "spi_csid_rw",
}

# Environment choices (logged).
TCK_CLKS = 4  # clk_i periods per TCK period
TRST_TCK = 4  # TCK cycles of the jtag_trst_ni pulse
RETIRE_BOUND = 20_000  # clk_i cycles for a retirement on the trace port
PULSE_CLKS = 16  # clk_i cycles of the dbg_rstb_i and wdt_rst_ni_i pulses (test parameter)
TAP_BOUND = 2_000  # clk_i cycles for the sep_cpu_reset_n fall and rise
RST_HOLD = 20  # clk_i cycles of rst_ni low at bring-up
SETTLE = 8  # clk_i cycles after a system-bus access before a tap is read
LABEL_HOLD = 2  # clk_i cycles a pass label holds its value
# sbcs reads while sbbusy is 1 (and DMI busy retries). A watchdog register sits in
# the clk_wdt_i domain (5 us period on this bench), so its access waits for the
# register CDC; 1024 reads of about 0.5 us each bound it with margin.
SB_BUSY_READS = 1024
UNCORE_ADDRS = (0x50, 0x7F)  # lowest and highest 7-bit DMI address at or above 0x50
UNCORE_FIRST = UNCORE_ADDRS[0]
# dmi_req_probe_o (tb/sep_tb_signal_list.svh): bit 8 dmi_en, bit 7 dmi_wr_en,
# bits 6:0 dmi_addr of the DTM, before the core and uncore mux.
DTM_EN = 1 << 8
DTM_WR = 1 << 7
DTM_ADDR = 0x7F
SPIN_LOOP = 0x0000_006F  # jal x0, 0
# dtmcs after the TAP reset: version 1, abits 7, dmistat 0, idle 0 (EL2 PRM
# section 11.1.1.2, Table 11.3, linked from hw/sys/sep/doc/cpu.adoc).
DTMCS_RESET = (7 << 4) | 1


@dataclass
class _Access:
    target: str
    addr: int
    size: int
    mask: int
    before: int = 0
    wr: int = 0
    mid: int = 0
    new: int = 0
    new_rb: int = 0
    rd: int | None = None
    after: int | None = None
    sberr: tuple[int, int] = (0, 0)
    sb: tuple = ()
    # Whole SRAM word 0 (64 bits) at each independent read of an SRAM target, in
    # the order before, cpu_path, new_rb, cpu_path_end. Empty for a register.
    words: tuple = ()
    pair: tuple = ()
    # Drawn values are ``fixed | (draw & free)``; ``free`` None draws every bit.
    fixed: int = 0
    free: int | None = None


@dataclass(frozen=True)
class _DtmReq:
    """One DMI request on the DTM request tap and the enable levels of its cycle."""

    clk: int
    wr: int
    addr: int
    core_en: int
    uncore_en: int
    never: bool


def _h(v: int | None, w: int = 16) -> str:
    return "X" if v is None else f"0x{v:0{w}x}"


@pyuvm.test()
class sep_debug_master_target_matrix_test(sep_base_test):
    """DMI enable gates, debug-module system-bus targets and the debug reset."""

    def build_phase(self) -> None:
        # Entry S uses the bench LSU master as the independent register path; in
        # entry C the core owns the LSU.
        self.entry_c = "cpu_boot" in cocotb.plusargs
        self.build_env = not self.entry_c
        super().build_phase()

    # ---------------------------------------------------------------- set-up
    def _draw(self) -> None:
        seed = self.random_seed()
        self.rng = SepSeededRng(seed)
        self.logger.info("INFO-SEED seed=%d", seed)
        rng = self.rng
        targets = [n for n, _ in SRAM_TARGETS] + [n for n, _, _ in REG_TARGETS]
        rng.shuffle(targets)
        self.sram_sizes = {}
        for name, _ in SRAM_TARGETS:
            sizes = [4, 8]
            rng.shuffle(sizes)
            self.sram_sizes[name] = sizes
        self.target_order = targets
        self.sram_init = rng.getrandbits(64)
        self.moved_base = MOVED_LO + MOVED_ALIGN * rng.randrange(
            (MOVED_HI - MOVED_LO) // MOVED_ALIGN + 1
        )
        moved_sizes = [4, 8]
        rng.shuffle(moved_sizes)
        self.moved_sizes = moved_sizes
        self.logger.info("INFO-DRAW target_order=%s", ",".join(targets))
        self.logger.info(
            "INFO-DRAW sram_sizes=%s",
            " ".join(f"{n}:{'/'.join(str(s) for s in v)}" for n, v in self.sram_sizes.items()),
        )
        self.logger.info("INFO-DRAW sram_init=0x%016x", self.sram_init)
        self.logger.info(
            "INFO-DRAW moved_base=0x%08x moved_sizes=%s",
            self.moved_base,
            "/".join(str(s) for s in moved_sizes),
        )
        self.logger.info(
            "INFO-ENV tck_clks=%d trst_tck=%d retire_bound=%d pulse_clks=%d tap_bound=%d "
            "rst_hold=%d settle=%d sb_busy_reads=%d uncore_addrs=%s",
            TCK_CLKS,
            TRST_TCK,
            RETIRE_BOUND,
            PULSE_CLKS,
            TAP_BOUND,
            RST_HOLD,
            SETTLE,
            SB_BUSY_READS,
            ",".join(f"0x{a:02x}" for a in UNCORE_ADDRS),
        )

    def _shape(self, acc: _Access, v: int) -> int:
        return v if acc.free is None else acc.fixed | (v & acc.free)

    def _draw_value(self, acc: _Access) -> int:
        """A write value of the full access width that differs from ``before``."""
        bits = 8 * acc.size
        while True:
            v = self._shape(acc, self.rng.getrandbits(bits))
            if v != acc.before:
                return v

    def _draw_word(self) -> int:
        """A 64-bit write word with no outbound-mailbox magic word in either half."""
        while True:
            d = self.rng.getrandbits(64)
            if (d & 0xFFFF_FFFF) not in OUTBOUND_MBX_MAGIC and (d >> 32) not in OUTBOUND_MBX_MAGIC:
                return d

    # ---------------------------------------------------------------- sampler
    async def _sampler(self) -> None:
        """Per clk_i: reset taps, trace port, DTM requests, DMI uncore outputs."""
        dut = cocotb.top
        prev_cpu = None
        while not self._stop:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.clk += 1
            cpu_tap = self.rd(dut.sep_cpu_reset_n_o)
            sep_tap = self.rd(dut.dbg_sep_reset_n_o)
            if not self.released:
                self.cold_sep_low += sep_tap == 0
            if self.entry_c and self.rd(dut.cpu_trace_valid_o):
                self.retired += 1
            if self.dbg_window:
                self.dbg_samples += 1
                self.dbg_cpu_low += cpu_tap == 0
                self.dbg_sep_low += sep_tap == 0
            if prev_cpu == 1 and cpu_tap == 0:
                self.cpu_falls += 1
            if prev_cpu == 0 and cpu_tap == 1:
                self.cpu_rises += 1
            prev_cpu = cpu_tap
            if self.dtm_on:
                act = self.rd(dut.dmi_active_probe_o)
                self.dmi_act_high += act == 1
                self.dmi_act_rises += self.prev_act == 0 and act == 1
                self.prev_act = act
            if self.dtm_on and self.rd(dut.dmi_req_probe_o, DTM_EN):
                req = self.rd(dut.dmi_req_probe_o)
                self.dtm.append(
                    _DtmReq(
                        clk=self.clk,
                        wr=int((req & DTM_WR) != 0),
                        addr=req & DTM_ADDR,
                        core_en=self.rd(dut.dmi_core_enable_i),
                        uncore_en=self.rd(dut.dmi_uncore_enable_i),
                        never=self.uncore_never,
                    )
                )
            if self.uncore_armed:
                en = self.rd(dut.dmi_uncore_en_o)
                wr = self.rd(dut.dmi_uncore_wr_en_o)
                if self.uncore_never:
                    self.never_cycles += 1
                    self.never_en += en
                    self.never_wr += wr
                if self.uncore_ctl is not None:
                    self.uncore_ctl["en"] += en and not self.prev_en
                    self.uncore_ctl["wr"] += wr and not self.prev_wr
                self.prev_en, self.prev_wr = en, wr

    def _pair_mark(self) -> tuple[TapMark, TapMark]:
        return self.din_tap.mark(), self.dout_tap.mark()

    def _pair_since(self, mark: tuple[TapMark, TapMark]) -> tuple[list, list]:
        pin = [(b.ch, b.addr) for b in self.din_tap.since(mark[0])]
        pout = [(b.ch, b.addr) for b in self.dout_tap.since(mark[1])]
        return pin, pout

    # ---------------------------------------------------------------- grading
    def _grade(self, chk: str, ok: bool, text: str) -> bool:
        """Log one check; a FAIL closes the owner window before it is recorded."""
        self.n_checks += 1
        if ok:
            self.logger.info("%s PASS: %s", chk, text)
        else:
            close_graded_window(self.logger)
            self.logger.error("%s FAIL: %s", chk, text)
            self.failures.append(f"{chk}: {text}")
        return ok

    async def _inst_open(self, *, axprot: bool = True) -> None:
        """Start one graded instance: both labels 0, the AxPROT tap, the owner window.

        No window opens after a FAIL. Every label and window write runs after a
        clock edge, outside a read-only phase.
        """
        clk = cocotb.top.clk_i
        await RisingEdge(clk)
        set_dbg_sba_pass(0)
        set_dbg_axprot_pass(False)
        self.axp_tap = SepFabricTap("PR-DBG-SB").start() if axprot else None
        await RisingEdge(clk)
        if not self.failures:
            open_graded_window(TEST, self.logger)
        await RisingEdge(clk)

    def _grade_axprot(self) -> bool:
        """CHK-DBG-AXPROT on the AR and AW records of the instance."""
        ok = True
        for ch in ("ar", "aw"):
            self.n_checks += 1
            try:
                check_axprot(self.logger, "CHK-DBG-AXPROT", self.axp_tap, "dbg", ch, AXPROT_DBG)
            except AssertionError as exc:
                close_graded_window(self.logger)
                self.failures.append(str(exc))
                ok = False
        return ok

    async def _inst_close(self, cells: int) -> None:
        """End one instance: CHK-DBG-AXPROT, the release of ``cells``, the window close.

        The release runs only when every check of the run so far passed. The
        labels hold LABEL_HOLD clocks and return to 0 before the window closes.
        """
        clk = cocotb.top.clk_i
        await RisingEdge(clk)
        axprot = self.axp_tap is not None
        if axprot:
            await self.axp_tap.stop()
            self._grade_axprot()
            self.axp_tap = None
        if not self.failures:
            set_dbg_sba_pass(cells, self.logger)
            set_dbg_axprot_pass(axprot, self.logger)
            await ClockCycles(clk, LABEL_HOLD)
            set_dbg_sba_pass(0)
            set_dbg_axprot_pass(False)
            await RisingEdge(clk)
        close_graded_window(self.logger)

    # ---------------------------------------------------------------- bring-up
    def _stage_rom(self) -> None:
        mem = cocotb.top.u_dut.u_sep_ip_integration.u_sep_boot_rom.mem
        mem[0].value = (SPIN_LOOP << 32) | SPIN_LOOP
        self.logger.info("INFO-STAGE rom word0 <- 0x%016x", (SPIN_LOOP << 32) | SPIN_LOOP)

    def _check_rom_stage(self) -> None:
        """CTRL-STAGE-ROM: the staged spin loop is in the ROM array after the bring-up."""
        word = int(cocotb.top.u_dut.u_sep_ip_integration.u_sep_boot_rom.mem[0].value)
        want = (SPIN_LOOP << 32) | SPIN_LOOP
        line = f"rom word0=0x{word:016x} expect=0x{want:016x} (jal x0, 0 at 0x{ROM_BASE:08x})"
        if word != want:
            self.logger.error("CTRL-MISSING STAGE-ROM: %s", line)
            self.failures.append(f"CTRL-MISSING STAGE-ROM: {line}")
        else:
            self.logger.info("CTRL-STAGE-ROM: %s", line)

    async def _bring_up(self) -> None:
        """Step 1: cold reset with dbg_rstb_i low until the rst_ni release."""
        dut = cocotb.top
        if self.entry_c:

            async def _hook() -> None:
                self._stage_rom()
                cocotb.start_soon(self._sampler())

            await self.bring_up_cpu_boot(0, pre_reset_hook=_hook)
            self._check_rom_stage()
        else:
            self.drive_idle_defaults(dut, cpu_run=False)
            await self.assert_cold_reset(dut)
            self._set_pin(dut, "dbg_rstb_i", 0)
            self.start_clocks(dut)
            cocotb.start_soon(self._sampler())
            await ClockCycles(dut.clk_i, RST_HOLD)
            dut.rst_ni.value = 1
            self._set_pin(dut, "dbg_rstb_i", 1)
            await ClockCycles(dut.clk_i, 2)
            self.cfg.reset_done.set()
            await self.wait_fuse_sense()
        # The sampler counts the sep_reset_n tap low cycles until here.
        self.released = True
        # Entry C grades the count in CHK-DBG-RST; entry S records it only.
        self.logger.info(
            "%s: sep_reset_n tap low for %d clk_i cycles of the cold reset",
            "CTRL-COLD" if self.entry_c else "INFO-COLD",
            self.cold_sep_low,
        )

    async def _tap_setup(self) -> None:
        """Step 1: TAP pins to the bench, TRST pulse, Run-Test/Idle, DMI selected."""
        dut = cocotb.top
        tap = OcahJtagMasterDriver(
            dut,
            name="sep_core_tap",
            tck_period_ns=int(round(TCK_CLKS * self.cfg.sys_clk_period_ns * 1000)),
            ir_width=IR_WIDTH,
            tap_type="dtm",
            signal_map=dict(PIN_MAP),
            time_unit="ps",
        )
        self.dmi = SepJtagDmi(tap, dut=dut, log=self.logger, busy_bound=SB_BUSY_READS)
        self.dmi.take_pins()
        await self.dmi.trst_pulse(tck_cycles=TRST_TCK)
        await tap.goto_state("RUN_TEST_IDLE")
        await tap.shift_ir(IR_DMI, IR_WIDTH, back_to_rti=True)
        dtmcs = await self.dmi.read_dtmcs()
        self._grade(
            "CHK-DTMCS",
            dtmcs == DTMCS_RESET,
            f"dtmcs=0x{dtmcs:08x} expect=0x{DTMCS_RESET:08x}",
        )
        # The TAP is out of reset: the sampler records DTM requests from here.
        self.dtm_on = True

    async def _wait_retire(self, after: int, what: str) -> int:
        for _ in range(RETIRE_BOUND):
            if self.retired > after:
                return self.retired
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError(f"{what}: no retirement within {RETIRE_BOUND} clk_i cycles")

    # ---------------------------------------------------------------- steps 2-4
    async def _gate(self) -> None:
        dut = cocotb.top
        await self._inst_open(axprot=False)
        # Step 2: the write with the enable low; the read data is logged only.
        dut.dmi_core_enable_i.value = 0
        await ClockCycles(dut.clk_i, 2)
        mark = len(self.dtm)
        act_high, act_rises = self.dmi_act_high, self.dmi_act_rises
        await self.dmi.dmi_write(DM_DMCONTROL, DMCONTROL_DMACTIVE)
        gated_rd = await self.dmi.dmi_read(DM_DMCONTROL)
        await ClockCycles(dut.clk_i, SETTLE)
        gated = [(r.wr, r.addr, r.core_en) for r in self.dtm[mark:]]
        n_wr = gated.count((1, DM_DMCONTROL, 0))
        n_rd = gated.count((0, DM_DMCONTROL, 0))
        n_other = len(gated) - n_wr - n_rd
        # Step 3.
        dut.dmi_core_enable_i.value = 1
        await ClockCycles(dut.clk_i, 2)
        after = await self.dmi.dmi_read(DM_DMCONTROL)
        # Step 4: control with the enable high.
        await self.dmi.dmi_write(DM_DMCONTROL, DMCONTROL_DMACTIVE)
        ctl = await self.dmi.dmi_read(DM_DMCONTROL)
        enabled_rd_after = after & DMCONTROL_DMACTIVE
        control_rd = ctl & DMCONTROL_DMACTIVE
        ok = self._grade(
            "CHK-DMI-GATE",
            n_wr == 1 and n_rd == 1 and n_other == 0 and enabled_rd_after == 0 and control_rd == 1,
            f"dtm_wr_0x10_enable0={n_wr} dtm_rd_0x10_enable0={n_rd} dtm_other={n_other} "
            f"enabled_rd_after={enabled_rd_after} control_wr=1 "
            f"control_rd={control_rd} gated_rd_obs=0x{gated_rd:08x} "
            f"dmcontrol_after=0x{after:08x} dmcontrol_control=0x{ctl:08x}",
        )
        # No spec states when dmi_active is high, so its level over the DMI
        # requests of steps 2 to 4 is logged.
        self.logger.info(
            "OBS-DMI-ACTIVE requests=%d rises=%d high_clk=%d",
            len(self.dtm) - mark,
            self.dmi_act_rises - act_rises,
            self.dmi_act_high - act_high,
        )
        await self._inst_close(dbg_sba_bits("enable0_core", "enable1_core") if ok else 0)

    # ---------------------------------------------------------------- entry S
    async def _lsu(self, op: SepAxiOp, addr: int, data: int = 0, length: int = 4) -> int:
        seq = SepAxiAccessSeq(
            f"dbgm_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=data,
            length=length,
            size=2 if length == 4 else 3,
            allow_unverified_write_resp=op is SepAxiOp.WRITE,
            allow_ungraded_read_resp=op is SepAxiOp.READ,
        )
        # A watchdog register access waits for the clk_wdt_i register CDC of the
        # previous write, which is longer than the default bus timeout.
        saved = self.cfg.axi_timeout_ns
        if addr == WDT_BARK:
            self.cfg.axi_timeout_ns = max(saved, WDT_CDC_CLKS * self.cfg.wdt_clk_period_ns)
        try:
            await self.start_seq(seq)
        finally:
            self.cfg.axi_timeout_ns = saved
        if seq.timed_out:
            raise AssertionError(f"LSU {op.value} @0x{addr:08x} got no response")
        if seq.resp_code != 0:
            raise AssertionError(f"LSU {op.value} @0x{addr:08x} resp={seq.resp_code}")
        return int(seq.rdata) & ((1 << (8 * length)) - 1)

    def _probe(self, size: int) -> int:
        word = self.rd(cocotb.top.sram_word0_probe_o)
        return word & ((1 << (8 * size)) - 1)

    @staticmethod
    def _is_sram(acc: _Access) -> bool:
        return acc.target in ("SRAM_WORD", "SRAM_ALIAS", "MOVED_ALIAS")

    async def _independent(self, acc: _Access) -> int:
        if self._is_sram(acc):
            acc.words = (*acc.words, self._probe(8))
            return self._probe(acc.size)
        return await self._lsu(SepAxiOp.READ, acc.addr)

    async def _independent_write(self, acc: _Access, value: int) -> None:
        """Write the location by the bench LSU master (SRAM word at its direct address)."""
        addr = SRAM_WORD if self._is_sram(acc) else acc.addr
        await self._lsu(SepAxiOp.WRITE, addr, value, length=acc.size)
        await ClockCycles(cocotb.top.clk_i, SETTLE)

    def _draw_new(self, acc: _Access) -> int:
        """A value that differs from the debug-master write value in a graded bit."""
        while True:
            v = self._shape(acc, self.rng.getrandbits(8 * acc.size))
            if (v ^ acc.wr) & acc.mask:
                return v

    async def _sba_access(self, acc: _Access) -> None:
        """Step 7: before, debug write, CPU-path value, LSU write, debug read, after.

        Between the debug-master write and the debug-master read the bench LSU
        master writes a second drawn value, so the read value differs from the
        value that ``sbdata`` holds from the write.
        """
        acc.before = await self._independent(acc)
        acc.wr = self._draw_value(acc)
        sb_mark = self.sb_tap.mark()
        lx_mark = self.lx_tap.mark()
        pair_mark = self._pair_mark()
        try:
            werr = await self.dmi.sba_write(acc.addr, acc.wr, size=acc.size)
            await ClockCycles(cocotb.top.clk_i, SETTLE)
            acc.mid = await self._independent(acc)
            acc.new = self._draw_new(acc)
            await self._independent_write(acc, acc.new)
            acc.new_rb = await self._independent(acc)
            acc.rd, rerr = await self.dmi.sba_read(acc.addr, size=acc.size)
        except DmiError:
            pin, pout = self._pair_since(pair_mark)
            self.logger.error(
                "CHK-DBG-SBA FAIL: stall target=%s addr=0x%08x size=%d dbg_sb=%s dbg_in=%s dbg_out=%s",
                acc.target,
                acc.addr,
                acc.size,
                " ".join(x.fmt() for x in self.sb_tap.since(sb_mark)) or "-",
                pin,
                pout,
            )
            self.logger.error(
                "CHK-DBG-SBA FAIL: stall lsu_xbar=%s rvalid=%s rready=%s",
                " ".join(x.fmt() for x in self.lx_tap.since(lx_mark)) or "-",
                cocotb.top.pr_dbg_sb_rvalid_o.value,
                cocotb.top.pr_dbg_sb_rready_o.value,
            )
            raise
        acc.sberr = (werr, rerr)
        await ClockCycles(cocotb.top.clk_i, SETTLE)
        acc.after = await self._independent(acc)
        acc.sb = tuple(self.sb_tap.since(sb_mark))
        acc.pair = self._pair_since(pair_mark)

    def _sb_shape(self, acc: _Access) -> tuple[bool, str]:
        beats = acc.sb
        aw = [b for b in beats if b.ch == "aw"]
        ar = [b for b in beats if b.ch == "ar"]
        w = [b for b in beats if b.ch == "w"]
        r = [b for b in beats if b.ch == "r"]
        bb = [b for b in beats if b.ch == "b"]
        ids = [b.id for b in aw + ar + bb + r]
        id_hi = 0
        for i in ids:
            id_hi |= 0b11 if i is None else (i >> 1) & 0b11
        # AXI4 single transfer on the 64-bit debug master (hw/sys/sep/doc/cpu.adoc,
        # chapter introduction): AxSIZE = log2 of the access bytes, AxLEN = 0, one
        # W beat whose strobes are the byte lanes of the access, one R beat.
        exp_size = acc.size.bit_length() - 1
        exp_strb = ((1 << acc.size) - 1) << (acc.addr & (8 - acc.size))
        aw_size = aw[0].size if len(aw) == 1 else None
        ar_size = ar[0].size if len(ar) == 1 else None
        aw_len = aw[0].len if len(aw) == 1 else None
        ar_len = ar[0].len if len(ar) == 1 else None
        strb = w[0].strb if len(w) == 1 else None
        ok = (
            len(aw) == 1
            and len(ar) == 1
            and bool(ids)
            and id_hi == 0
            and len(w) == 1
            and len(r) == 1
            and aw_size == exp_size
            and ar_size == exp_size
            and aw_len == 0
            and ar_len == 0
            and strb == exp_strb
        )

        def h(v: int | None) -> str:
            return "X" if v is None else f"0x{v:x}"

        text = (
            f"id_hi=0b{id_hi:02b} beats=w{len(w)}/r{len(r)} records=aw{len(aw)}/ar{len(ar)} "
            f"bus_aw=0x{(aw[0].addr or 0) if aw else 0:08x} "
            f"bus_ar=0x{(ar[0].addr or 0) if ar else 0:08x} "
            f"awsize={h(aw_size)} arsize={h(ar_size)} exp_axsize={exp_size} "
            f"awlen={h(aw_len)} arlen={h(ar_len)} wstrb={h(strb)} exp_wstrb=0x{exp_strb:02x}"
        )
        return ok, text

    @staticmethod
    def _r_beat(acc: _Access) -> tuple[int | None, int | None]:
        """(data, resp) of the one R beat of the access on PR-DBG-SB.

        The data is the lane of the access (``lane32`` for 4 bytes, the whole
        beat for 8). None when the access has no R beat, more than one, or a
        data or response field that holds X or Z.
        """
        r = [b for b in acc.sb if b.ch == "r"]
        if len(r) != 1:
            return None, None
        data, resp = r[0].data, r[0].resp
        if data is not None and acc.size == 4:
            data = lane32(data, acc.addr)
        return data, resp

    def _value_ok(self, acc: _Access) -> tuple[bool, str]:
        # Write leg: the CPU path reads the debug-master write value. Read leg:
        # the bench LSU master then writes ``new``, and the R beat of the
        # debug-master read on PR-DBG-SB and the sbdata readback both carry
        # ``new``. sbdata holds ``wr`` from the write, and ``new`` differs from
        # ``wr`` in a graded bit, so a read whose data never arrives fails.
        r_data, r_resp = self._r_beat(acc)
        mask = acc.mask
        pairs = (
            ("cpu_path", acc.mid, acc.wr),
            ("new_rb", acc.new_rb, acc.new),
            ("r_data", r_data, acc.new),
            ("rd", acc.rd, acc.new),
            ("cpu_path_end", acc.after, acc.new),
        )
        ok = True
        rsvd = []
        for name, got, exp in pairs:
            if got is None:
                ok = False
                rsvd.append(f"rsvd_{name}=X")
                continue
            c = field_compare(got, exp, mask)
            ok = ok and c.ok
            rsvd.append(f"rsvd_{name}=0x{c.rsvd:x}")
        if self._is_sram(acc):
            cmp = f"mask=0x{mask:x}"
            if acc.size == 4:
                # A 32-bit SRAM access leaves the upper half of the 64-bit word as
                # it was before the access; a write issued at a wider size changes it.
                ups = [wd >> 32 for wd in acc.words]
                up_ok = len(ups) == 4 and all(u == ups[0] for u in ups)
                ok = ok and up_ok
                cmp += " upper=" + "/".join(f"0x{u:08x}" for u in ups)
                cmp += f" upper_kept={int(up_ok)}"
        else:
            cmp = f"field_mask=0x{mask:x} " + " ".join(rsvd)
        ok = ok and acc.before != acc.wr and acc.sberr == (0, 0)
        w = 2 * acc.size

        def h(v: int | None) -> str:
            return "X" if v is None else f"0x{v:0{w}x}"

        text = (
            f"target={acc.target} addr=0x{acc.addr:08x} size={acc.size} "
            f"before={h(acc.before)} wr={h(acc.wr)} cpu_path={h(acc.mid)} "
            f"new={h(acc.new)} new_rb={h(acc.new_rb)} r_data={h(r_data)} rd={h(acc.rd)} "
            f"cpu_path_end={h(acc.after)} sberror_wr={acc.sberr[0]} sberror_rd={acc.sberr[1]} "
            f"rresp_obs={'X' if r_resp is None else r_resp} {cmp}"
        )
        return ok, text

    def _log_pair(self, acc: _Access) -> None:
        pin, pout = acc.pair
        self.logger.info(
            "INFO-DBG-PAIR: target=%s in=%s out=%s",
            acc.target,
            ",".join(f"{c}:0x{a:08x}" for c, a in pin),
            ",".join(f"{c}:0x{a:08x}" for c, a in pout),
        )

    async def _sba_instance(self, acc: _Access) -> None:
        """One CHK-DBG-SBA access in its own owner window."""
        await self._inst_open()
        await self._sba_access(acc)
        v_ok, v_text = self._value_ok(acc)
        s_ok, s_text = self._sb_shape(acc)
        ok = self._grade("CHK-DBG-SBA", v_ok and s_ok, f"{v_text} {s_text}")
        self._log_pair(acc)
        cells = dbg_sba_bits(SBA_CELL[acc.target], "id_hi_zero_r", "id_hi_zero_w")
        await self._inst_close(cells if ok else 0)

    async def _sba_matrix(self) -> None:
        """Steps 5 to 8: nine accesses in the drawn order, each graded in its own window."""
        dut = cocotb.top
        dut.dmi_core_enable_i.value = 1
        # Set-up: SRAM word 0 holds a known value before the first access.
        await self._lsu(SepAxiOp.WRITE, SRAM_WORD, self.sram_init, length=8)
        await ClockCycles(dut.clk_i, SETTLE)
        got = self._probe(8)
        if got != self.sram_init:
            raise AssertionError(
                f"set-up: SRAM word 0 reads 0x{got:016x}, wrote 0x{self.sram_init:016x}"
            )
        self.logger.info("CTRL-SRAM-INIT: sram_word0=0x%016x", got)
        # Step 5.
        self.sb_tap = SepFabricTap("PR-DBG-SB").start()
        self.lx_tap = SepFabricTap("PR-LSU-XBAR").start()
        self.din_tap = SepFabricTap("PR-DBG-IN").start()
        self.dout_tap = SepFabricTap("PR-DBG-OUT").start()
        accs: list[_Access] = []
        addrs = dict(SRAM_TARGETS)
        regs = {n: (a, m) for n, a, m in REG_TARGETS}
        for name in self.target_order:
            if name in addrs:
                for size in self.sram_sizes[name]:
                    acc = _Access(name, addrs[name], size, (1 << (8 * size)) - 1)
                    await self._sba_instance(acc)
                    accs.append(acc)
            else:
                a, m = regs[name]
                acc = _Access(name, a, 4, m & 0xFFFF_FFFF)
                await self._sba_instance(acc)
                accs.append(acc)
        # Step 8.
        await self.sb_tap.stop()
        if len(accs) != 9:
            raise AssertionError(f"{len(accs)} accesses ran, expected 9")

    @staticmethod
    def _rewritten(acc: _Access) -> bool:
        pin, pout = acc.pair
        return bool(pin) and len(pin) == len(pout) and any(i[1] != o[1] for i, o in zip(pin, pout))

    async def _alias_legs(self) -> None:
        """The moved local-alias legs: MOVE, OLD and BELOW, each in its own window."""
        base = self.moved_base
        # Set-up: move the window with the bench LSU master and read it back.
        await self._lsu(SepAxiOp.WRITE, LOCAL_BASE_ADDR, base)
        rb = await self._lsu(SepAxiOp.READ, LOCAL_BASE_ADDR)
        if rb != base:
            raise AssertionError(
                f"set-up: SEP_LOCAL_BASE_ADDR reads 0x{rb:08x}, wrote 0x{base:08x}"
            )
        self.logger.info("CTRL-BASE-MOVE: SEP_LOCAL_BASE_ADDR=0x%08x readback=0x%08x", base, rb)
        self.sb_tap = SepFabricTap("PR-DBG-SB").start()
        moved_addr = base + (SRAM_WORD - ALIAS_TARGET)
        moved: list[_Access] = []
        for size in self.moved_sizes:
            acc = _Access("MOVED_ALIAS", moved_addr, size, (1 << (8 * size)) - 1)
            await self._inst_open()
            await self._sba_access(acc)
            moved.append(acc)
            v_ok, v_text = self._value_ok(acc)
            s_ok, s_text = self._sb_shape(acc)
            pin, pout = acc.pair
            exp_out = SRAM_WORD
            p_ok = (
                sorted(c for c, _ in pin) == ["ar", "aw"]
                and sorted(c for c, _ in pout) == ["ar", "aw"]
                and all(a == acc.addr for _, a in pin)
                and all(a == exp_out for _, a in pout)
            )
            ok = self._grade(
                "CHK-DBG-ALIAS-MOVE",
                v_ok and s_ok and p_ok,
                f"base=0x{base:08x} {v_text} {s_text} "
                f"dbg_in={','.join(f'{c}:0x{a:08x}' for c, a in pin)} "
                f"dbg_out={','.join(f'{c}:0x{a:08x}' for c, a in pout)} "
                f"expected_out=0x{exp_out:08x}",
            )
            cells = dbg_sba_bits(SBA_CELL[acc.target], "id_hi_zero_r", "id_hi_zero_w")
            await self._inst_close(cells if ok else 0)
        control = int(all(self._rewritten(a) for a in moved) and bool(moved))
        for chk, addr in (
            ("CHK-DBG-ALIAS-OLD", OLD_ALIAS),
            ("CHK-DBG-ALIAS-BELOW", base - 8),
        ):
            await self._inst_open()
            probe0 = self._probe(8)
            pair_mark = self._pair_mark()
            val = self.rng.getrandbits(32)
            werr = await self.dmi.sba_write(addr, val, size=4)
            rd, rerr = await self.dmi.sba_read(addr, size=4)
            await ClockCycles(cocotb.top.clk_i, SETTLE)
            pin, pout = self._pair_since(pair_mark)
            ok = (
                sorted(c for c, _ in pin) == ["ar", "aw"]
                and sorted(c for c, _ in pout) == ["ar", "aw"]
                and all(a == addr for _, a in pin)
                and pout == pin
                and control == 1
            )
            self._grade(
                chk,
                ok,
                f"base=0x{base:08x} addr=0x{addr:08x} "
                f"dbg_in={','.join(f'{c}:0x{a:08x}' for c, a in pin)} "
                f"dbg_out={','.join(f'{c}:0x{a:08x}' for c, a in pout)} "
                f"control_rewrite={control}",
            )
            self.logger.info(
                "OBS-ALIAS-OUTSIDE: %s addr=0x%08x wr=0x%08x sberror_wr=%d rd=0x%08x sberror_rd=%d "
                "sram_word0=0x%016x->0x%016x",
                chk,
                addr,
                val,
                werr,
                rd,
                rerr,
                probe0,
                self._probe(8),
            )
            await self._inst_close(0)
        await self.sb_tap.stop()
        # Clean-up: the window back at its reset base.
        await self._lsu(SepAxiOp.WRITE, LOCAL_BASE_ADDR, LOCAL_BASE_RESET & 0xFFFF_FFFF)
        rb = await self._lsu(SepAxiOp.READ, LOCAL_BASE_ADDR)
        self.logger.info("INFO-BASE-RESTORE: SEP_LOCAL_BASE_ADDR readback=0x%08x", rb)

    # ------------------------------------------------- entry S, after the alias legs
    def _beats(self, tap: SepFabricTap, mark: TapMark, ch: str) -> list:
        return tap.since(mark, ch)

    async def _appended_targets(self) -> None:
        """SW_RESET_N and the SPI host CSID, graded as CHK-DBG-SBA."""
        for name, addr, mask, fixed, free, restore in APPENDED_TARGETS:
            acc = _Access(name, addr, 4, mask, fixed=fixed, free=free)
            await self._sba_instance(acc)
            # Clean-up, outside the window: the reset value back.
            await self._lsu(SepAxiOp.WRITE, addr, restore)
            rb = await self._lsu(SepAxiOp.READ, addr)
            if (rb ^ restore) & mask:
                raise AssertionError(
                    f"clean-up: {name} reads 0x{rb:08x}, wrote 0x{restore:08x} (mask 0x{mask:x})"
                )
            self.logger.info("CTRL-RESTORE: %s=0x%08x readback=0x%08x", name, restore, rb)

    async def _pool_leg(self) -> None:
        """CHK-DBG-POOL-RD and CHK-DBG-POOL-WR in one window."""
        clk = cocotb.top.clk_i
        wval = self.rng.getrandbits(64)
        self.logger.info("INFO-DRAW pool_write=0x%016x", wval)
        await self._inst_open()
        before = await self._lsu(SepAxiOp.READ, POOL_STATUS, length=8)
        mark = self.sb_tap.mark()
        rd, rerr = await self.dmi.sba_read(POOL_STATUS, size=8)
        await ClockCycles(clk, SETTLE)
        ar = self._beats(self.sb_tap, mark, "ar")
        r = self._beats(self.sb_tap, mark, "r")
        after = await self._lsu(SepAxiOp.READ, POOL_STATUS, length=8)
        c0 = field_compare(rd, before, POOL_STATUS_MASK)
        c1 = field_compare(rd, after, POOL_STATUS_MASK)
        # STATUS does not move over the leg: the LSU reads before and after agree.
        stable = field_compare(before, after, POOL_STATUS_MASK)
        r_data = r[0].data if len(r) == 1 else None
        rd_ok = self._grade(
            "CHK-DBG-POOL-RD",
            len(ar) == 1
            and ar[0].addr == POOL_STATUS
            and ar[0].size == 3
            and ar[0].len == 0
            and len(r) == 1
            and r_data == rd
            and rerr == 0
            and stable.ok
            and c0.ok
            and c1.ok,
            f"addr=0x{POOL_STATUS:08x} ar={len(ar)} r={len(r)} "
            f"arsize={_h(ar[0].size if ar else None, 1)} sberror={rerr} "
            f"sbdata={_h(rd)} r_data={_h(r_data)} lsu_before={_h(before)} "
            f"lsu_after={_h(after)} lsu_stable={int(stable.ok)} field_mask=0x{POOL_STATUS_MASK:x} "
            f"rsvd_obs=0x{c0.rsvd:x} rresp_obs={_h(r[0].resp if r else None, 1)}",
        )
        mark = self.sb_tap.mark()
        werr = await self.dmi.sba_write(POOL_STATUS, wval, size=8)
        await ClockCycles(clk, SETTLE)
        aw = self._beats(self.sb_tap, mark, "aw")
        w = self._beats(self.sb_tap, mark, "w")
        b = self._beats(self.sb_tap, mark, "b")
        after_wr = await self._lsu(SepAxiOp.READ, POOL_STATUS, length=8)
        c2 = field_compare(after_wr, after, POOL_STATUS_MASK)
        bresp = b[0].resp if len(b) == 1 else None
        wr_ok = self._grade(
            "CHK-DBG-POOL-WR",
            len(aw) == 1
            and aw[0].addr == POOL_STATUS
            and len(w) == 1
            and w[0].data == wval
            and len(b) == 1
            and bresp == RESP_SLVERR
            and werr != 0
            and c2.ok,
            f"addr=0x{POOL_STATUS:08x} aw={len(aw)} w={len(w)} b={len(b)} "
            f"wdata={_h(wval)} bus_wdata={_h(w[0].data if w else None)} "
            f"bresp={_h(bresp, 1)} expect_bresp=0x{RESP_SLVERR:x} sberror={werr} "
            f"lsu_before={_h(after)} lsu_after={_h(after_wr)} field_mask=0x{POOL_STATUS_MASK:x}",
        )
        cells = 0
        if rd_ok:
            cells |= dbg_sba_bits("pool_status_r64")
        if wr_ok:
            cells |= dbg_sba_bits("pool_w_slverr")
        await self._inst_close(cells)

    def _ext_program(self, code: int, rword: int) -> None:
        top = cocotb.top
        top.ext_port_rsp_bresp_i.value = code
        top.ext_port_rsp_rresp_i.value = code
        top.ext_port_rsp_rdata_i.value = rword

    async def _ext_leg(self) -> None:
        """CHK-DBG-EXT: OKAY and SLVERR replies of the extension port, read and write."""
        clk = cocotb.top.clk_i
        on = self.rd(cocotb.top.ext_port_rsp_on_o)
        if on != 1:
            msg = "CTRL-EXT-RSP FAIL: ext_port_rsp_on_o=0; the entry needs +sep_ext_port_responder"
            self.logger.error(msg)
            raise AssertionError(msg)
        word = EXT_FIRST + 8 * self.rng.randrange((EXT_LAST - EXT_FIRST) // 8 + 1)
        self.logger.info("INFO-DRAW ext_word=0x%08x", word)
        ext = SepFabricTap("PR-EXT").start()
        rsp = SepFabricTap("PR-EXT-RSP").start()
        for code in (RESP_OKAY, RESP_SLVERR):
            rword = self.rng.getrandbits(64)
            wword = self.rng.getrandbits(64)
            self.logger.info(
                "INFO-DRAW ext_code=%d ext_reply=0x%016x ext_write=0x%016x", code, rword, wword
            )
            self._ext_program(code, rword)
            await self._inst_open()
            # Read.
            em, rm, sm = ext.mark(), rsp.mark(), self.sb_tap.mark()
            rd, rerr = await self.dmi.sba_read(word, size=8)
            await ClockCycles(clk, SETTLE)
            p_ar = self._beats(ext, em, "ar")
            p_aw = self._beats(ext, em, "aw")
            p_r = self._beats(rsp, rm, "r")
            s_ar = self._beats(self.sb_tap, sm, "ar")
            s_r = self._beats(self.sb_tap, sm, "r")
            sr = s_r[0] if len(s_r) == 1 else None
            rd_ok = self._grade(
                "CHK-DBG-EXT",
                len(p_ar) == 1
                and not p_aw
                and p_ar[0].addr == word
                and p_ar[0].len == 0
                and p_ar[0].size == 3
                and len(s_ar) == 1
                and s_ar[0].addr == word
                and sr is not None
                and sr.resp == code
                and sr.data == rword
                and (rerr == 0) == (code == RESP_OKAY)
                and (code != RESP_OKAY or rd == rword),
                f"dir=R code={code} addr=0x{word:08x} port_ar={len(p_ar)} port_aw={len(p_aw)} "
                f"port_addr={_h(p_ar[0].addr if p_ar else None, 8)} "
                f"port_arlen={_h(p_ar[0].len if p_ar else None, 1)} "
                f"port_arsize={_h(p_ar[0].size if p_ar else None, 1)} dbg_ar={len(s_ar)} "
                f"dbg_r={len(s_r)} dbg_rresp={_h(sr.resp if sr else None, 1)} "
                f"dbg_rdata={_h(sr.data if sr else None)} reply={_h(rword)} sberror={rerr} "
                f"sbdata={_h(rd)}",
            )
            self.logger.info(
                "INFO-EXT-RSP-DRIVE: dir=R port_r=%s set_code=%d set_word=0x%016x",
                " ".join(x.fmt() for x in p_r) or "-",
                code,
                rword,
            )
            # Write.
            em, rm, sm = ext.mark(), rsp.mark(), self.sb_tap.mark()
            werr = await self.dmi.sba_write(word, wword, size=8)
            await ClockCycles(clk, SETTLE)
            p_aw = self._beats(ext, em, "aw")
            p_ar = self._beats(ext, em, "ar")
            p_w = self._beats(ext, em, "w")
            p_b = self._beats(rsp, rm, "b")
            s_aw = self._beats(self.sb_tap, sm, "aw")
            s_b = self._beats(self.sb_tap, sm, "b")
            sb = s_b[0] if len(s_b) == 1 else None
            wr_ok = self._grade(
                "CHK-DBG-EXT",
                len(p_aw) == 1
                and not p_ar
                and p_aw[0].addr == word
                and len(p_w) == 1
                and p_w[0].data == wword
                and p_w[0].strb == 0xFF
                and len(s_aw) == 1
                and s_aw[0].addr == word
                and sb is not None
                and sb.resp == code
                and (werr == 0) == (code == RESP_OKAY),
                f"dir=W code={code} addr=0x{word:08x} port_aw={len(p_aw)} port_ar={len(p_ar)} "
                f"port_addr={_h(p_aw[0].addr if p_aw else None, 8)} port_w={len(p_w)} "
                f"port_wdata={_h(p_w[0].data if p_w else None)} wdata={_h(wword)} "
                f"port_wstrb={_h(p_w[0].strb if p_w else None, 2)} dbg_aw={len(s_aw)} "
                f"dbg_b={len(s_b)} dbg_bresp={_h(sb.resp if sb else None, 1)} sberror={werr}",
            )
            self.logger.info(
                "INFO-EXT-RSP-DRIVE: dir=W port_b=%s set_code=%d",
                " ".join(x.fmt() for x in p_b) or "-",
                code,
            )
            cell = "ext_ok" if code == RESP_OKAY else "ext_err"
            await self._inst_close(dbg_sba_bits(cell) if rd_ok and wr_ok else 0)
        await ext.stop()
        await rsp.stop()

    async def _nc_leg(self) -> None:
        """CHK-DBG-NC: the boot ROM base and an ICCM word, read and write."""
        clk = cocotb.top.clk_i
        iccm = ICCM_BASE + 8 * self.rng.randrange(ICCM_SIZE // 8)
        self.logger.info("INFO-DRAW iccm_word=0x%08x", iccm)
        rom = SepFabricTap("PR-ROM").start()
        tcm = SepFabricTap("PR-XBAR-TCM").start()
        live_rom, live_tcm = await self._nc_live(rom, tcm, iccm)
        for name, addr, cell in (("ROM", ROM_BASE, "rom"), ("ICCM", iccm, "iccm")):
            wval = self.rng.getrandbits(64)
            self.logger.info("INFO-DRAW nc_write target=%s value=0x%016x", name, wval)
            await self._inst_open()
            passed = []
            for d in ("r", "w"):
                rm, tm, sm = rom.mark(), tcm.mark(), self.sb_tap.mark()
                if d == "r":
                    data, err = await self.dmi.sba_read(addr, size=8)
                else:
                    data, err = None, await self.dmi.sba_write(addr, wval, size=8)
                await ClockCycles(clk, SETTLE)
                n_rom = len(rom.since(rm))
                n_tcm = len(tcm.since(tm))
                req = self._beats(self.sb_tap, sm, "ar" if d == "r" else "aw")
                w = self._beats(self.sb_tap, sm, "w")
                rsp = self._beats(self.sb_tap, sm, d if d == "r" else "b")
                ok = self._grade(
                    "CHK-DBG-NC",
                    len(req) == 1
                    and req[0].addr == addr
                    and (d == "r" or (len(w) == 1 and w[0].data == wval))
                    and len(rsp) == 1
                    and n_rom == 0
                    and n_tcm == 0
                    and live_rom >= 1
                    and live_tcm >= 1,
                    f"target={name} dir={d.upper()} addr=0x{addr:08x} dbg_req={len(req)} "
                    f"dbg_addr={_h(req[0].addr if req else None, 8)} dbg_w={len(w)} "
                    f"dbg_rsp={len(rsp)} pr_rom_beats={n_rom} pr_xbar_tcm_beats={n_tcm} "
                    f"probe_pr_rom_beats={live_rom} probe_pr_xbar_tcm_beats={live_tcm}",
                )
                self.logger.info(
                    "OBS-DBG-NOTCONN: target=%s dir=%s resp=%s sberror=%d data=%s",
                    name,
                    d.upper(),
                    _h(rsp[0].resp if rsp else None, 1),
                    err,
                    _h(data),
                )
                if ok:
                    passed.append(f"{cell}_{d}")
            await self._inst_close(dbg_sba_bits(*passed) if len(passed) == 2 else 0)
        await rom.stop()
        await tcm.stop()

    async def _nc_live(self, rom: SepFabricTap, tcm: SepFabricTap, iccm: int) -> tuple[int, int]:
        """Positive probes of the two silence taps, outside every window.

        An LSU read of the boot ROM base must put a request on PR-ROM, and a
        secure DMA copy of one SRAM word to the ICCM word must put a write on
        PR-XBAR-TCM. The counts are read on the tap objects that CHK-DBG-NC
        reads; a count of 0 fails CHK-DBG-NC.
        """
        clk = cocotb.top.clk_i
        word = self.rng.getrandbits(32)
        self.logger.info("INFO-DRAW nc_probe_word=0x%08x", word)
        rm = rom.mark()
        await self.start_seq(
            SepAxiAccessSeq(
                "nc_probe_rom_rd",
                op=SepAxiOp.READ,
                addr=ROM_BASE,
                length=8,
                size=3,
                allow_ungraded_read_resp=True,
            )
        )
        await ClockCycles(clk, SETTLE)
        live_rom = len(rom.since(rm, "req"))
        dma = SepDmaOps(self)
        await SepMemWords(self).fill(DMA_PROBE_SRC, [word])
        await dma.clean_state()
        await dma.program_range(0x0, 0xFFFF_FFFF, valid=True)
        await dma.program_transfer(
            src=DMA_PROBE_SRC,
            dst=iccm,
            total=DMA_WORD_BYTES,
            chunk=DMA_WORD_BYTES,
            width_enc=DMA_WIDTH_ENC,
        )
        tm = tcm.mark()
        await dma.go()
        st = await dma.poll_status(
            lambda x: bool(x.done or x.error), dma.done_bound(DMA_WORD_BYTES), "nc probe"
        )
        await ClockCycles(clk, SETTLE)
        live_tcm = len(tcm.since(tm, "aw"))
        self.logger.info(
            "CTRL-NC-LIVE: lsu_rom_read pr_rom_req=%d dma_copy src=0x%08x dst=0x%08x "
            "status=%s pr_xbar_tcm_aw=%d",
            live_rom,
            DMA_PROBE_SRC,
            iccm,
            st.fmt(),
            live_tcm,
        )
        return live_rom, live_tcm

    async def _sba_obs_leg(self) -> None:
        """Step 21: debug-master read and write of six targets in one instance.

        CHK-DBG-AXPROT grades the AR and AW beats of the instance.
        CHK-DBG-SBA-ISO grades both accesses of ISOLATED (HMAC in software
        reset): the PR-DBG-SB R or B beat answers SLVERR, the R beat carries
        ``0x1501A7ED`` in the 32-bit lane of the access, and ``sberror`` is not
        0. CHK-DBG-SBA-REG grades the bench-LSU readback after the write to
        FILT_START (the written value on the ``start_addr`` field, rounded only
        when START and END share a granule) and to LC_RSVD (the value before
        the write OR the written bit), and the debug-master read of each, which
        returns the bench-LSU value read before the instance in ``sbdata``. The
        R or B beat of all four register accesses answers OKAY and ``sberror``
        reads 0. PIC_BASE, HOLE and PAST are logged as OBS-DBG-SBA.
        """
        clk = cocotb.top.clk_i
        hole = HOLE_FIRST + 8 * self.rng.randrange((HOLE_LAST - HOLE_FIRST) // 8 + 1)
        disabled = {}
        for i in range(INFILT_ENTRIES):
            cfg = await self._lsu(SepAxiOp.READ, INFILT_BASE + i * FILTER_STRIDE + FILTER_CONFIG)
            if not cfg & F_ENTRY_ENABLED:
                disabled[i] = cfg
        if not disabled:
            raise AssertionError("set-up: no disabled inbound filter entry")
        filt = self.rng.choice(list(disabled))
        filt_start = INFILT_BASE + filt * FILTER_STRIDE + FILTER_START_ADDR
        demote_bit = 2 + self.rng.randrange(62)
        targets = (
            ("PIC_BASE", PIC_BASE, 4),
            ("HOLE", hole, 8),
            ("PAST", DMA_PAST, 4),
            ("ISOLATED", _HMAC.addr("MSG_LENGTH_LOWER"), 4),
            ("FILT_START", filt_start, 8),
            ("LC_RSVD", DEMOTE_2, 8),
        )
        wvals = {
            name: (1 << demote_bit) if name == "LC_RSVD" else self.rng.getrandbits(8 * size)
            for name, _addr, size in targets
        }
        self.logger.info(
            "INFO-DRAW sba_obs hole=0x%08x filt_entry=%d demote_bit=%d writes=%s",
            hole,
            filt,
            demote_bit,
            " ".join(f"{n}:0x{v:x}" for n, v in wvals.items()),
        )
        sw_rst = await self._lsu(SepAxiOp.READ, SW_RESET_N)
        start_before = await self._lsu(SepAxiOp.READ, filt_start, length=8)
        end_rb = await self._lsu(
            SepAxiOp.READ, filt_start - FILTER_START_ADDR + FILTER_END_ADDR, length=8
        )
        lc_before = await self._lsu(SepAxiOp.READ, DEMOTE_2, length=8)
        # START_ADDR write-back (hw/ip/axi_filter/regs/filter_ctrl.rdl:94-102): the
        # granule is 4 KiB with allow_burst, else 2^data_bus_width bytes; hardware
        # writes the rounded START back only when START and END share a granule.
        cfg = disabled[filt]
        gran = 0x1000 if cfg & F_ALLOW_BURST else 1 << ((cfg >> DBW_LSB) & DBW_MASK)
        start_w = wvals["FILT_START"] & FILTER_ADDR_MASK
        same = start_w // gran == (end_rb & FILTER_ADDR_MASK) // gran
        before = {"FILT_START": start_before, "LC_RSVD": lc_before}
        expect = {
            "FILT_START": start_w & ~(gran - 1) if same else start_w,
            "LC_RSVD": lc_before | wvals["LC_RSVD"],
        }
        await self._inst_open()
        for name, addr, size in targets:
            if name == "ISOLATED":
                await self._lsu(SepAxiOp.WRITE, SW_RESET_N, sw_rst & ~HMAC_RST_FIELD)
            for d in ("r", "w"):
                sm = self.sb_tap.mark()
                if d == "r":
                    data, err = await self.dmi.sba_read(addr, size=size)
                else:
                    data, err = None, await self.dmi.sba_write(addr, wvals[name], size=size)
                await ClockCycles(clk, SETTLE)
                rsp = self._beats(self.sb_tap, sm, d if d == "r" else "b")
                codes = " ".join(_h(b.resp, 1) for b in rsp) or "-"
                if name == "ISOLATED":
                    lane = lane32(rsp[0].data, addr) if d == "r" and len(rsp) == 1 else None
                    self._grade(
                        "CHK-DBG-SBA-ISO",
                        len(rsp) == 1
                        and rsp[0].resp == RESP_SLVERR
                        and err != 0
                        and (d == "w" or lane == ISO_DATA),
                        f"target=ISOLATED dir={d.upper()} addr=0x{addr:08x} beats={len(rsp)} "
                        f"resp={codes} expect_resp=0x{RESP_SLVERR:x} sberror={err} "
                        + (
                            f"r_data={_h(rsp[0].data if rsp else None)} lane={_h(lane, 8)} "
                            f"expect_lane=0x{ISO_DATA:08x}"
                            if d == "r"
                            else "expect_sberror=nonzero"
                        ),
                    )
                elif name in expect:
                    mask = FILTER_ADDR_MASK if name == "FILT_START" else (1 << 64) - 1
                    if d == "r":
                        got, exp = data, before[name]
                    else:
                        got, exp = await self._lsu(SepAxiOp.READ, addr, length=8), expect[name]
                    fc = field_compare(got, exp, mask)
                    # The request address on PR-DBG-SB: a read that reaches another
                    # word that also reads 0 cannot pass on the data alone.
                    ax = [b.addr for b in self._beats(self.sb_tap, sm, "ar" if d == "r" else "aw")]
                    self._grade(
                        "CHK-DBG-SBA-REG",
                        fc.ok
                        and len(rsp) == 1
                        and rsp[0].resp == RESP_OKAY
                        and err == 0
                        and ax == [addr],
                        f"target={name} dir={d.upper()} addr=0x{addr:08x} "
                        f"pr_dbg_sb_{'ar' if d == 'r' else 'aw'}={[_h(a) for a in ax]} "
                        f"wr={'-' if d == 'r' else _h(wvals[name])} "
                        f"{'sbdata' if d == 'r' else 'lsu_rb'}={_h(got)} expect={_h(exp)} "
                        f"field_mask=0x{mask:x} resp={codes} sberror={err}"
                        + (
                            f" end={_h(end_rb)} granule=0x{gran:x} same_granule={int(same)}"
                            if name == "FILT_START"
                            else f" before={_h(lc_before)}"
                        ),
                    )
                else:
                    self.logger.info(
                        "OBS-DBG-SBA target=%s dir=%s addr=0x%08x resp=%s sberror=%d data=%s",
                        name,
                        d.upper(),
                        addr,
                        codes,
                        err,
                        "-" if d == "w" else _h(data),
                    )
            if name == "ISOLATED":
                await self._lsu(SepAxiOp.WRITE, SW_RESET_N, sw_rst)
            if name == "FILT_START":
                await self._lsu(SepAxiOp.WRITE, filt_start, start_before & 0xFFFF_FFFF)
                await self._lsu(SepAxiOp.WRITE, filt_start + 4, start_before >> 32)
        await self._inst_close(0)

    async def _remap_program(self, csr_base: int, region: int, word: int) -> None:
        attrs = csr_base + region * REMAP_STRIDE + REMAP_ATTRS
        await self._lsu(SepAxiOp.WRITE, attrs, word & 0xFFFF_FFFF)
        await self._lsu(SepAxiOp.WRITE, attrs + 4, word >> 32)
        got = await self._lsu(SepAxiOp.READ, attrs) | (
            await self._lsu(SepAxiOp.READ, attrs + 4) << 32
        )
        fc = field_compare(got, word, REMAP_OFFSET_FIELD | REMAP_VALID_FIELD)
        if not fc.ok:
            raise AssertionError(f"set-up: remap region {region} attrs {fc.fields()}")
        self.logger.info(
            "CTRL-REMAP-PROGRAM: csr=0x%08x region=%d %s", csr_base, region, fc.fields()
        )

    async def _remap_leg(self) -> None:
        """CHK-DBG-REMAP: a debug-master write and read of one AP and one STEE word."""
        clk = cocotb.top.clk_i
        filt = SepFilterBank(self, "out")
        classes = []
        for path, region_base, csr_base, pair in REMAP_PATHS:
            region = self.rng.randrange(N_REGIONS)
            intra = self.rng.randrange(1 << IDX_START) & ~7
            local = region_base + (region << IDX_START) + intra
            while True:
                offset = self.rng.getrandbits(ADDR_BITS - IDX_START) << IDX_START
                if offset >> 32:
                    break
            translated = offset | (local & REGION_MASK)
            wval = self._draw_word()
            self.logger.info(
                "INFO-DRAW remap path=%s region=%d local=0x%08x offset=0x%014x translated=0x%014x "
                "write=0x%016x",
                path,
                region,
                local,
                offset,
                translated,
                wval,
            )
            await self._remap_program(csr_base, region, offset | REMAP_VALID_FIELD)
            lo, hi = granule8(translated)
            for idx, ns in zip(pair, (0, 1)):
                await filt.program(
                    idx,
                    FilterEntry(
                        start=lo,
                        end=hi,
                        enabled=True,
                        read_allowed=True,
                        write_allowed=True,
                        allow_ns=bool(ns),
                        src_id=OTHERS_SOURCE_ID,
                    ),
                )
            classes.append((path, csr_base, region, local, translated, wval, pair))
        out = SepFabricTap("PR-OUT").start()
        for path, _csr, _region, local, translated, wval, _pair in classes:
            ns = outbound_ns(path, translated)
            await self._inst_open()
            passed = []
            for d in ("w", "r"):
                om, sm = out.mark(), self.sb_tap.mark()
                if d == "w":
                    err = await self.dmi.sba_write(local, wval, size=8)
                    data = None
                else:
                    data, err = await self.dmi.sba_read(local, size=8)
                await ClockCycles(clk, SETTLE)
                ach = "aw" if d == "w" else "ar"
                cap = self._beats(out, om, ach)
                other = self._beats(out, om, "ar" if d == "w" else "aw")
                ow = self._beats(out, om, "w")
                req = self._beats(self.sb_tap, sm, ach)
                c = cap[0] if len(cap) == 1 else None
                prot1 = None if c is None or c.prot is None else (c.prot >> 1) & 1
                ok = self._grade(
                    "CHK-DBG-REMAP",
                    c is not None
                    and not other
                    and c.addr == translated
                    and c.user == OTHERS_SOURCE_ID
                    and prot1 == ns
                    and (d == "r" or (len(ow) == 1 and ow[0].data == wval))
                    and len(req) == 1
                    and req[0].addr == local,
                    f"path={path} dir={d.upper()} local=0x{local:08x} dbg_req={len(req)} "
                    f"out_captures={len(cap)} out_other={len(other)} "
                    f"out_addr={_h(c.addr if c else None, 14)} expect_addr=0x{translated:014x} "
                    f"out_user={_h(c.user if c else None, 3)} "
                    f"expect_user=0x{OTHERS_SOURCE_ID:03x} ns={_h(prot1, 1)} expect_ns={ns} "
                    f"out_w={len(ow)} out_wdata={_h(ow[0].data if ow else None)} "
                    f"wdata={_h(wval) if d == 'w' else 'na'}",
                )
                self.logger.info(
                    "OBS-DBG-REMAP-RESP: path=%s dir=%s sberror=%d data=%s",
                    path,
                    d.upper(),
                    err,
                    _h(data),
                )
                if ok:
                    passed.append(f"{path}_{d}")
            await self._inst_close(dbg_sba_bits(*passed) if len(passed) == 2 else 0)
        await out.stop()
        # Clean-up, outside the windows: regions invalid, filter entries at reset.
        for _path, csr_base, region, _l, _t, _w, pair in classes:
            await self._remap_program(csr_base, region, 0)
            for idx in pair:
                await filt.restore_reset(idx)

    async def _after_alias(self) -> None:
        self.sb_tap = SepFabricTap("PR-DBG-SB").start()
        await self._appended_targets()
        await self._pool_leg()
        await self._ext_leg()
        await self._nc_leg()
        await self._remap_leg()
        await self._sba_obs_leg()
        await self.sb_tap.stop()
        await self.lx_tap.stop()
        await self.din_tap.stop()
        await self.dout_tap.stop()

    # ---------------------------------------------------------------- entry C
    async def _uncore_never(self) -> None:
        """Step 9: accesses at 0x50 and 0x7F and a dmcontrol read, core enable high, then low.

        The owner window opens here and stays open through the step 10 control
        and the grade of CHK-DMI-UNCORE.
        """
        dut = cocotb.top
        await self._inst_open(axprot=False)
        for core_en in (1, 0):
            dut.dmi_core_enable_i.value = core_en
            await ClockCycles(dut.clk_i, 2)
            low = await self.dmi.dmi_read(DM_DMCONTROL)
            self.logger.info("OBS-UNCORE-LOW: core_en=%d dmcontrol=0x%08x", core_en, low)
            for addr in UNCORE_ADDRS:
                rd = await self.dmi.dmi_read(addr)
                await self.dmi.dmi_write(addr, self.rng.getrandbits(32))
                self.logger.info(
                    "OBS-UNCORE-RD: core_en=%d addr=0x%02x rdata=0x%08x", core_en, addr, rd
                )
        dut.dmi_core_enable_i.value = 1
        await ClockCycles(dut.clk_i, SETTLE)
        self.uncore_never = False

    async def _uncore_control(self) -> dict[str, int]:
        """Step 10: the read and the write at 0x50 with dmi_uncore_enable_i at 1."""
        dut = cocotb.top
        dut.dmi_uncore_enable_i.value = 1
        await ClockCycles(dut.clk_i, 2)
        res = {}
        self.uncore_ctl = {"en": 0, "wr": 0}
        rd = await self.dmi.dmi_read(UNCORE_ADDRS[0])
        await ClockCycles(dut.clk_i, SETTLE)
        res["rd_en"], res["rd_wr"] = self.uncore_ctl["en"], self.uncore_ctl["wr"]
        self.uncore_ctl = {"en": 0, "wr": 0}
        await self.dmi.dmi_write(UNCORE_ADDRS[0], self.rng.getrandbits(32))
        await ClockCycles(dut.clk_i, SETTLE)
        res["wr_en"], res["wr_wr"] = self.uncore_ctl["en"], self.uncore_ctl["wr"]
        self.uncore_ctl = None
        dut.dmi_uncore_enable_i.value = 0
        await ClockCycles(dut.clk_i, 2)
        self.logger.info("OBS-UNCORE-CTL-RD: rdata=0x%08x (bench holds 0)", rd)
        return res

    def _grade_uncore(self, ctl: dict[str, int]) -> bool:
        never = [r for r in self.dtm if r.never]
        upper = [(r.core_en, r.addr, r.wr) for r in never if r.addr >= UNCORE_FIRST]
        never_uncore_en = sum(r.uncore_en for r in never)
        want = sorted((c, a, w) for c in (0, 1) for a in UNCORE_ADDRS for w in (0, 1))
        ok = (
            self.never_en == 0
            and self.never_wr == 0
            and self.never_cycles > 0
            and sorted(upper) == want
            and never_uncore_en == 0
            and ctl["rd_en"] >= 1
            and ctl["wr_en"] >= 1
            and ctl["wr_wr"] >= 1
        )
        return self._grade(
            "CHK-DMI-UNCORE",
            ok,
            f"en_o_cycles={self.never_en} wr_en_o_cycles={self.never_wr} "
            f"dtm_reqs={len(never)} dtm_at_or_above_0x50={len(upper)} "
            f"dtm_upper_core0={sum(1 for u in upper if u[0] == 0)} "
            f"dtm_upper_core1={sum(1 for u in upper if u[0] == 1)} "
            f"dtm_upper_cells_ok={int(sorted(upper) == want)} "
            f"dtm_uncore_enable_high={never_uncore_en} "
            f"control_en_o_rise={ctl['rd_en'] + ctl['wr_en']} "
            f"control_wr_en_o_rise={ctl['wr_wr']} window_cycles={self.never_cycles} "
            f"control_read_en_o_rise={ctl['rd_en']} control_read_wr_en_o_rise={ctl['rd_wr']} "
            f"control_write_en_o_rise={ctl['wr_en']}",
        )

    async def _dbg_reset(self) -> dict[str, int]:
        """Step 11: dbg_rstb_i pulse with dmactive set.

        The owner window opens here and stays open through step 12 and the
        grade of CHK-DBG-RST.
        """
        dut = cocotb.top
        before = await self.dmi.dmi_read(DM_DMCONTROL)
        await self._inst_open(axprot=False)
        self.dbg_window = True
        dut.dbg_rstb_i.value = 0
        await ClockCycles(dut.clk_i, PULSE_CLKS)
        dut.dbg_rstb_i.value = 1
        at_release = self.retired
        await self._wait_retire(at_release, "after dbg_rstb_i")
        after = await self.dmi.dmi_read(DM_DMCONTROL)
        self.dbg_window = False
        return {
            "before": before & DMCONTROL_DMACTIVE,
            "after": after & DMCONTROL_DMACTIVE,
            "pc_advance": self.retired - at_release,
            "cpu_low": self.dbg_cpu_low,
            "sep_low": self.dbg_sep_low,
            "samples": self.dbg_samples,
        }

    async def _wdt_control(self) -> int:
        """Step 12: wdt_rst_ni_i pulse; the sep_cpu_reset_n tap falls and rises."""
        dut = cocotb.top
        falls0, rises0 = self.cpu_falls, self.cpu_rises
        await RisingEdge(dut.clk_i)
        dut.wdt_rst_ni_i.value = 0
        await ClockCycles(dut.clk_i, PULSE_CLKS)
        dut.wdt_rst_ni_i.value = 1
        for _ in range(TAP_BOUND):
            if self.cpu_falls > falls0 and self.cpu_rises > rises0:
                return 1
            await RisingEdge(dut.clk_i)
        self.logger.info(
            "INFO-WDT-CONTROL: sep_cpu_reset_n tap falls=%d rises=%d within %d clk_i cycles",
            self.cpu_falls - falls0,
            self.cpu_rises - rises0,
            TAP_BOUND,
        )
        return 0

    # ---------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        dut = cocotb.top
        if not self.full_cpu_build():
            msg = "CTRL-FULL-CPU FAIL: the build has the CPU stub, which has no EL2 debug module"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.clk = 0
        self._stop = False
        self.released = False
        self.cold_sep_low = 0
        self.retired = 0
        self.dbg_window = False
        self.dbg_samples = self.dbg_cpu_low = self.dbg_sep_low = 0
        self.cpu_falls = self.cpu_rises = 0
        self.uncore_armed = False
        self.uncore_never = False
        self.dtm_on = False
        self.dtm: list[_DtmReq] = []
        self.dmi_act_high = self.dmi_act_rises = 0
        self.prev_act = None
        self.uncore_ctl = None
        self.never_cycles = self.never_en = self.never_wr = 0
        self.prev_en = self.prev_wr = 0
        self.failures: list[str] = []
        self.n_checks = 0
        self.axp_tap = None
        if self.entry_c:
            self.required_evidence = ("CHK-DTMCS", "CHK-DMI-GATE", "CHK-DMI-UNCORE", "CHK-DBG-RST")
        else:
            self.required_evidence = (
                "CHK-DTMCS",
                "CHK-DMI-GATE",
                "CHK-DBG-SBA",
                "CHK-DBG-ALIAS-MOVE",
                "CHK-DBG-ALIAS-OLD",
                "CHK-DBG-ALIAS-BELOW",
                "CHK-DBG-POOL-RD",
                "CHK-DBG-POOL-WR",
                "CHK-DBG-EXT",
                "CHK-DBG-NC",
                "CHK-DBG-REMAP",
                "CHK-DBG-SBA-ISO",
                "CHK-DBG-SBA-REG",
                "CHK-DBG-AXPROT",
            )
        self.logger.info(
            "INFO-BUILD: entry=%s full_cpu=1 required_evidence=%s",
            "C" if self.entry_c else "S",
            ",".join(self.required_evidence),
        )
        self._draw()

        await self._bring_up()
        await self._tap_setup()
        if self.entry_c:
            # The uncore never window covers every DMI access from step 1.
            self.uncore_armed = True
            self.uncore_never = True
            first = await self._wait_retire(0, "first retirement after the cold reset")
            self.logger.info("CTRL-RETIRE: first retirement seen (count %d)", first)
        await self._gate()
        if self.entry_c:
            await self._uncore_never()
            ctl = await self._uncore_control()
            ok = self._grade_uncore(ctl)
            await self._inst_close(
                dbg_sba_bits(
                    "enable0_core",
                    "enable0_upper",
                    "enable1_core",
                    "enable1_upper",
                    "disabled_lower_never",
                    "disabled_upper_never",
                )
                if ok
                else 0
            )
            dbg = await self._dbg_reset()
            wdt_low = await self._wdt_control()
            ok = (
                dbg["before"] == 1
                and dbg["after"] == 0
                and dbg["pc_advance"] > 0
                and dbg["cpu_low"] == 0
                and dbg["sep_low"] == 0
                and dbg["samples"] > 0
                and wdt_low == 1
                and self.cold_sep_low > 0
            )
            ok = self._grade(
                "CHK-DBG-RST",
                ok,
                f"dmactive {dbg['before']}->{dbg['after']} after dbg_rstb_i; "
                f"pc_advance={dbg['pc_advance']} sep_cpu_reset_n_low={dbg['cpu_low']} "
                f"sep_reset_n_low={dbg['sep_low']} control_wdt_sep_cpu_reset_n_low={wdt_low} "
                f"window_samples={dbg['samples']} control_cold_sep_reset_n_low={self.cold_sep_low}",
            )
            await self._inst_close(dbg_sba_bits("dmactive_cleared") if ok else 0)
        else:
            await self._sba_matrix()
            await self._alias_legs()
            await self._after_alias()
        dut.dmi_core_enable_i.value = 0
        self.dmi.release_pins()
        self._stop = True
        await ClockCycles(dut.clk_i, 2)
        close_graded_window(self.logger)
        if self.failures:
            raise AssertionError("; ".join(self.failures))
        self.result_pass(TEST, self.random_seed(), self.n_checks)
