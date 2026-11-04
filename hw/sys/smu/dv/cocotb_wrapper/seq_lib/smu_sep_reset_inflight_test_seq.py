# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMU_SEP_SCN_011 ANCHOR: smu_sep_reset_inflight_test
# DV-TESTCASE-CONTRACT-REVISION: 4 RECORD-SHA256: f3f66a20f44e7f77f94138ab59ec1cabcacf092a44bd8bb36194e38ec7e84132
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_SEP_SCN_VPLAN_DETAIL_RESET.md @ artifact_revision 5 ENV: cocotb
"""SEP-side resets with crossbar traffic in flight, on the SEP=1 wrapper.

Bring-up is ``smu_dtp_sep_dm_dmi_test`` (TEST_DEV posture, SEP STAP, dmactive); the SEP debug
module's system bus then programs the SEP aperture (SEP_GLOBAL_BASE_ADDR 0x0400_0000,
SEP_REGION_SIZE 0x1100_0000, so global = 0x0400_0000 + SEP-local) and SEP outbound filter entry 1
over the egress page, as ``smu_axi_in_sep_aperture_test`` and ``smu_dtp_sep_dm_sba_test`` do.

The SEP fabric connects the Reset Controller register block to the lsu, dbg and dma initiators
only (``hw/sys/sep/doc/fabric.adoc``), so every SW_RESET_N access is a debug-module system-bus
access; ext_in carries the crypto-window, SRAM, mailbox, eFuse, lifecycle and TRNG accesses.

Expected values (``hw/sys/sep/doc/reset_controller.adoc``): a new access to an isolated path
completes SLVERR with read data 0x1501A7ED in each 32-bit word; SW_RESET_N resets to 0x7E
(``sep_reset_ctrl.adoc``); the Key Manager mailbox, eFuse, lifecycle and external TRNG ports are
never isolated; the external TRNG window of the reference integration answers DECERR with
0xBADCAB1E in each 32-bit lane (``memory_map.adoc``); ``sep_reset_n`` resets the Reset
Controller and the system peripherals, so SW_RESET_N and the aperture registers return to their
reset values (SEP_GLOBAL_BASE_ADDR 0x0, SEP_REGION_SIZE 0x100_0000, ``sep_cpu_ctrl.adoc``); the
bite resets the CPU, and the watchdog reset drains nothing: an access hung across it stays hung
until the cold reset (``doc/trm/src/reset.adoc``, ``doc/programmer/src/sep-programming.adoc``).
With the warm-scratch read orphaned at the bite, the DMA_BUS_ERR_STATUS / PERIPH_BUS_ERR_STATUS
readback and the egress write / read over the system bus are OBS-SEPRST-BITE-ORPHAN observation
windows, never compared.

The VeeR EL2 debug module has no program buffer, so a CPU-issued ``sep_out`` access is made by a
four-instruction stub written into the ICCM with abstract memory writes (``lw t0, 0(a0)``,
``ebreak``, ``sb a1, 0(a0)``, ``ebreak``), entered through ``dpc`` with ``dcsr.ebreakm`` set.
A resume request and the system-bus write it must overlap travel in consecutive DMI scans, so
the write lands inside the responder's bounded hold of the CPU's load.

S1  SETUP: aperture, egress filter, system-bus SW_RESET_N precondition read.
S2  DRAIN: five domains x two cells: four held reads, the system-bus 0 write, RREADY released
    before (cell a) or after (cell b) the write reports complete; SW_RESET_N is read back after
    the 0 write and after the 1 write.
S3  ISOLATED: new 64/32-bit reads and a write during the drain and with the reset held.
S4  RELEASE: the 1 write, a fresh read and write.
S5  TRNG: the S2 cells on ESRC with bit 5, then ESRC/CSRNG/EDN, the pool, release.
S6  KM: the mailbox status word (offset 0xC) with bit 0 held from power-up, released and
    held again; SW_RESET_N is read back after each of the three writes.
S7  ALL_DOMAINS: a CPU egress load held across a system-bus SW_RESET_N = 0x00, read back as
    0x00, a CPU load into the SMC window, never-isolated targets with every domain held.
S8  EARLY: 0 then 1 at gaps of 0 and 8 debug-bus operations for OTBN, AES and TRNG; the
    written domain's bits of the SEP crypto isolation request (``host_otbn``, ``host_aes``, the
    three ``trng_*`` bits) are sampled each cycle of every pair and must leave their value from
    before the 0 write (``reset_controller.adoc``: a 0 bit makes the domain's sequencer request
    isolation, the 1 write releases it); another domain's bit moving does not count.
S9  JTAG: SW_RESET_N = 0x7F read back, then the IC_RESET sep_reset_n override with ext_in
    and a CPU egress load outstanding;
    the debug-module bring-up is repeated when the first system-bus access reports busy.
S10 BITE: the SEP watchdog bite with ext_in and a CPU egress load outstanding; the SEP SRAM
    read is issued with RREADY held before the bite request rises, and its ext_in AR handshake
    must precede the watchdog reset (``rst_wdt_n`` low, ``doc/trm/src/reset.adoc:44``; the SEP
    ``wdt_rst_ni`` that resets the CPU and holds the bite request until it asserts,
    ``hw/sys/sep/doc/port_table.adoc:25-26``) and its R handshake follow it; the same
    conditional bring-up after the bite; the status readback, the watchdog registers and the
    egress accesses after the bite are bounded observation windows.
S11 TIMEOUT: every proof-path wait is bounded and logged with its bound, the cycles used and its
    last state, and its sites per kind are compared with the step list; every observation
    window is listed separately by name with its bound, the cycles used and expired=<0|1>.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_reset_inflight_test --target compile_smu_chiplet
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_DECERR, RESP_OKAY, RESP_SLVERR, resp_name, worst_resp

from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO, c_header_u32
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_axi_in_sep_aperture_test_seq import (
    WIN_BASE,
    WIN_SIZE,
    smu_axi_in_sep_aperture_test_seq,
)
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_DR_WIDTH,
    DMI_IDLE_TCKS,
    DMI_OP_NOP,
    DMI_OP_READ,
    DMI_OP_WRITE,
    DMI_STATUS_OK,
    SEP_TAP_IR_DMI,
    network_ir_scan,
    network_scan,
    pack_dmi,
    sep_dr_from_capture,
    smu_dtp_sep_dm_dmi_test_seq,
    unpack_dmi,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    DMI_RETRIES,
    DMI_STATUS_BUSY,
    EGRESS_ADDR,
    EGRESS_PAGE_END,
    OUTBOUND_CFG_OPEN,
    OUTBOUND_END_ADDR,
    OUTBOUND_FILTER_CONFIG,
    OUTBOUND_START_ADDR,
    PORT_POLL_CYCLES,
    SBA_POLLS,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBACCESS_32,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
)
from seq_lib.smu_dtp_sep_ic_reset_effect_test_seq import (
    ALL_ONES,
    SEP_CONTROL_BIT,
    SEP_ENABLE_BIT,
    SEP_HELD,
    SEP_STAGED,
)
from seq_lib.smu_jtag_helpers import (
    DTP_IR_IC_RESET,
    DTP_IR_TAP_3DCR,
    PTAP_3DCR_WIDTH,
    SMU_IC_RESET_LEN,
    ptap_3dcr_value,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset, smu_scope

_REPO = Path(__file__).resolve().parents[6]
_SEP_C = _REPO / "hw/sys/sep/regs/gen/c"
_SEP_ADDR_H = _SEP_C / "sep_addr.h"
_SEP_CPU_CTRL_H = _SEP_C / "blocks" / "sep_cpu_ctrl.h"
_SEP_RESET_CTRL_H = _SEP_C / "blocks" / "sep_reset_ctrl.h"
_AON_H = _REPO / "vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/gen/c/aon_timer.h"
_DMA_H = _REPO / "vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/gen/c/secure_dma.h"


def _a(symbol: str) -> int:
    return c_header_u32(_SEP_ADDR_H, symbol)


# hw/sys/sep/doc/reset_controller.adoc:139-141: the isolation response word.
ISO_WORD = 0x1501A7ED
# hw/sys/sep/regs/gen/adoc/memory_map.adoc:41, :94: the DECERR read word.
DECERR_WORD = 0xBADCAB1E
_SWRST_FIELDS = ("KM", "OTBN", "AES", "HMAC", "KMAC", "TRNG", "ABR")


def _swrst(field: str, suffix: str) -> int:
    return c_header_u32(_SEP_RESET_CTRL_H, f"SEP_RESET_CTRL__SW_RESET_N__{field}_SW_RST_N_{suffix}")


# sep_reset_ctrl.h: the SW_RESET_N power-on value, assembled from the field reset values.
SWRST_POR = sum(_swrst(f, "reset") << _swrst(f, "bp") for f in _SWRST_FIELDS)
SWRST_ALL_HELD = 0x00
SWRST_TRNG_BIT = _swrst("TRNG", "bp")
SWRST_FIELD_MASK = sum(_swrst(f, "bm") for f in _SWRST_FIELDS)
SWRST_ALL_RELEASED = SWRST_FIELD_MASK
# sep_cpu_ctrl.h: SEP_GLOBAL_BASE_ADDR and SEP_REGION_SIZE reset values.
APERTURE_RESET = (
    c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__SEP_GLOBAL_BASE_ADDR__ADDR_reset"),
    c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__SEP_REGION_SIZE__SIZE_reset"),
)

SWRST_LOCAL = _a("SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR")
SRAM_LOCAL = _a("SEP_TOP_SEP_SRAM_BASE_ADDR")
WSCRATCH_LOCAL = _a("SEP_TOP_SEP_SCRATCH_WARM_BASE_ADDR")
BOOT_ROM_LOCAL = _a("SEP_TOP_SEP_BOOT_ROM_BASE_ADDR")
BOOT_ROM_END = BOOT_ROM_LOCAL + _a("SEP_TOP_SEP_BOOT_ROM_SIZE")
ICCM_BASE = _a("SEP_TOP_SEP_ICCM_BASE_ADDR")
ICCM_END = ICCM_BASE + _a("SEP_TOP_SEP_ICCM_SIZE")
# (name, SW_RESET_N bit, SEP-local window): reset_controller.adoc bits 1..4 and 6.
DOMAINS = (
    ("otbn", 1, _a("SEP_TOP_OTBN_BASE_ADDR")),
    ("aes", 2, _a("SEP_TOP_AES_BASE_ADDR")),
    ("hmac", 3, _a("SEP_TOP_HMAC_BASE_ADDR")),
    ("kmac", 4, _a("SEP_TOP_KMAC_BASE_ADDR")),
    ("abr", 6, _a("SEP_TOP_ABR_BASE_ADDR")),
)
DOMAIN_BY_NAME = {name: (bit, local) for name, bit, local in DOMAINS}
TRNG_PATHS = (
    ("esrc", _a("SEP_TOP_ENTROPY_SOURCE_BASE_ADDR")),
    ("csrng", _a("SEP_TOP_CSRNG_BASE_ADDR")),
    ("edn", _a("SEP_TOP_EDN_BASE_ADDR")),
)
POOL_LOCAL = _a("SEP_TOP_ENTROPY_POOL_BASE_ADDR")
KM_MAILBOX_LOCAL = _a("SEP_TOP_KM_MAILBOX_SEP_BASE_ADDR")
# Stimulus offsets, not expected values: S6 / S7 read the readable status word at 0xC and
# write the inbound data register at 0x0.
KM_STATUS_LOCAL = KM_MAILBOX_LOCAL + 0x00C
KM_WRITE_LOCAL = KM_MAILBOX_LOCAL
# The eFuse MMR token-input words at the window base have no reset value (efuse_mmr.adoc), so
# the MMR read targets RMA_SIP_TOKEN_MATCH, which has one.
EFUSE_LOCALS = (
    _a("SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR"),
    _a("SEP_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR"),
    _a("SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_MATCH_BASE_ADDR"),
)
LC_LOCAL = _a("SEP_TOP_SEP_LIFECYCLE_CTRL_BASE_ADDR")
EXT_TRNG_LOCAL = _a("SEP_TOP_TRNG_BASE_ADDR")
# memory_map.adoc:41: the reserved SEP-local range the DMA reads to latch its bus fault.
DMA_RESERVED_SRC = 0x1005_0000
DMA_DST = SRAM_LOCAL + 0x3000
DMA_REGS = {
    name: _a(f"SEP_TOP_SECURE_DMA_{name}_BASE_ADDR")
    for name in (
        "ENABLED_MEMORY_RANGE_LIMIT",
        "RANGE_VALID",
        "SRC_ADDR_LO",
        "DST_ADDR_LO",
        "TOTAL_DATA_SIZE",
        "CHUNK_DATA_SIZE",
        "CONTROL",
    )
}
DMA_GO = c_header_u32(_DMA_H, "SECURE_DMA__CONTROL__GO_bm") | c_header_u32(
    _DMA_H, "SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm"
)
DMA_RANGE_ALL = 0xFFFF_FFFF
DMA_WORD = 4
DMA_ERR_STATUS = _a("SEP_TOP_SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_BASE_ADDR")
PERIPH_ERR_STATUS = _a("SEP_TOP_SEP_CPU_CTRL_PERIPH_BUS_ERR_STATUS_BASE_ADDR")
PERIPH_AES_BM = c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__PERIPH_BUS_ERR_STATUS__AES_bm")
WDOG = {
    name: _a(f"SEP_TOP_WDT_TIMER_WDOG_{name}_BASE_ADDR")
    for name in ("CTRL", "BITE_THOLD", "COUNT", "REGWEN")
}
WDOG_ENABLE = c_header_u32(_AON_H, "AON_TIMER__WDOG_CTRL__ENABLE_bm")
WDOG_BITE_TICKS = 0x20

# RV32I encodings of the ICCM stub, placed in the last ICCM page.
INSN_LW_T0_A0 = 0x0005_2283
INSN_SB_A1_A0 = 0x00B5_0023
INSN_EBREAK = 0x0010_0073
STUB_LOAD = ICCM_END - 0x100
STUB_LOAD_DONE = STUB_LOAD + 4
STUB_STORE = STUB_LOAD + 8
# sep_cpu_ctrl.h SEP_NMI_VEC reset value: the NMI handler address in the ICCM. An ebreak there
# turns a pending NMI (the byte store's bus error, the watchdog bark) into a debug halt.
_NMI_VEC = "SEP_CPU_CTRL__SEP_NMI_VEC_NMI_VEC_A3690E40__NMI_VEC"
NMI_VECTOR = c_header_u32(_SEP_CPU_CTRL_H, f"{_NMI_VEC}_reset") << c_header_u32(
    _SEP_CPU_CTRL_H, f"{_NMI_VEC}_bp"
)
STUB = (
    (STUB_LOAD, INSN_LW_T0_A0),
    (STUB_LOAD_DONE, INSN_EBREAK),
    (STUB_STORE, INSN_SB_A1_A0),
    (STUB_STORE + 4, INSN_EBREAK),
    (NMI_VECTOR, INSN_EBREAK),
)

# RISC-V Debug Specification 0.13 debug module registers and fields.
DATA0 = 0x04
DATA1 = 0x05
DMCONTROL = 0x10
DMSTATUS = 0x11
ABSTRACTCS = 0x16
COMMAND = 0x17
DMACTIVE = 1 << 0
HALTREQ = 1 << 31
RESUMEREQ = 1 << 30
ALLHALTED = 1 << 9
ALLRESUMEACK = 1 << 17
ABSTRACTCS_BUSY = 1 << 12
CMDERR_SHIFT = 8
CMDERR_MASK = 0x7
AARSIZE_32 = 2 << 20
TRANSFER = 1 << 17
WRITE = 1 << 16
CMD_ACCESS_MEMORY = 2 << 24
GPR = 0x1000
REG_T0, REG_A0, REG_A1 = GPR + 5, GPR + 10, GPR + 11
CSR_DCSR = 0x7B0
CSR_DPC = 0x7B1
# dcsr.ebreakm with prv = M.
DCSR_EBREAKM_M = (1 << 15) | 0x3
# sbcs.sbversion (bits 31:29) reads 0 while dmcontrol.dmactive is clear.
SBCS_SBVERSION_SHIFT = 29
STORE_BYTE = 0xA5

# Bounds, in clk_smu_i cycles unless named otherwise.
EXT_IN_BOUND = 4000
HS_BOUND = 400
RESPONDER_HOLD = 4000
# The responder's own repeating stall guard; the graded hold is RESPONDER_HOLD from the AR edge.
RESPONDER_GUARD = 2 * RESPONDER_HOLD
EGRESS_AR_BOUND = 4000
RESET_LEVEL_BOUND = 20000
RETIRE_BOUND = 100000
BITE_RISE_BOUND = 200000
BITE_FALL_BOUND = 20000
HALT_POLLS = 16
EBREAK_POLLS = 8
ABSTRACT_POLLS = 32
HELD_CELL_GAP = 2000
BITE_DURING_GAP = 4
CELLS = ("rready_before", "rready_after")
GAPS = (0, 8)
EARLY_DOMAINS = (("otbn", 1), ("aes", 2), ("trng", SWRST_TRNG_BIT))
FENCE = (
    "SETUP",
    "DRAIN",
    "ISOLATED",
    "RELEASE",
    "TRNG",
    "KM",
    "ALL_DOMAINS",
    "EARLY",
    "JTAG",
    "BITE",
)
FENCE_GAP = 2

# The reset controller's per-path isolation request to the crypto interconnect, sampled
# passively under smu_scope; S8 grades that the written domain's bits move within each 0-then-1
# pair. Field order of sep_pkg::sep_crypto_isolate_t (sep_pkg.sv, MSB first); sep_reset_ctrl.sv
# drives host_<engine> from that engine's isolate request alone, the three trng_* bits from the
# TRNG request, and km_* from the engine's or the Key Manager's request.
ISO_REQ_PATH = "gen_sep.u_sep.u_sep_reset_ctrl.sep_crypto_isolate_req_o"
ISO_REQ_FIELDS = (
    "trng_entropy_source",
    "trng_csrng",
    "trng_edn",
    "host_otbn",
    "host_aes",
    "host_hmac",
    "host_kmac",
    "host_abr",
    "km_otbn",
    "km_aes",
    "km_hmac",
    "km_kmac",
    "km_abr",
    "km_efuse",
)


def _iso_mask(*fields: str) -> int:
    return sum(1 << (len(ISO_REQ_FIELDS) - 1 - ISO_REQ_FIELDS.index(f)) for f in fields)


# S8: the bits a domain's own isolate request drives, by the EARLY_DOMAINS name.
EARLY_ISO_MASK = {
    "otbn": _iso_mask("host_otbn"),
    "aes": _iso_mask("host_aes"),
    "trng": _iso_mask("trng_entropy_source", "trng_csrng", "trng_edn"),
}

DRAIN_IDS = (0x10, 0x11, 0x12, 0x13)
EARLY_IDS = (0x14, 0x15)
CELL_IDS = {"rd64": 0x20, "rd32": 0x21, "wr": 0x22}
MISC_ID = 0x05
S9_OUT_IDS = {("sram", "w"): 0x30, ("sram", "r"): 0x31, ("swrst", "r"): 0x32}
S9_HELD_IDS = {("sram", "w"): 0x33, ("sram", "r"): 0x34, ("swrst", "r"): 0x35, ("lc", "r"): 0x36}
S10_IDS = {"wscratch": 0x37, "sram": 0x38, "during": 0x39, "after": 0x3A}
BITE_ORPHAN_LEGS = ("status_dma", "status_periph", "egress_wr", "egress_rd")
# Observation windows per OBS line, from the step list: S2/S5 drain reads, S9 in-flight and
# held accesses, S10 warm-scratch reads, orphaned system-bus legs and watchdog registers, and
# the first system-bus access after each SEP reset.
WINDOW_PLAN = Counter(
    {
        "OBS-SEPRST-DRAIN": (len(DOMAINS) + 1) * len(CELLS) * len(DRAIN_IDS),
        "OBS-SEPRST-JTAG-INFLIGHT": len(S9_OUT_IDS) + len(S9_HELD_IDS),
        "OBS-SEPRST-WSCRATCH": 3,
        "OBS-SEPRST-BITE-ORPHAN": len(BITE_ORPHAN_LEGS),
        "OBS-SEPRST-WDOG-POST": len(WDOG),
        "OBS-SEPRST-REBRINGUP": 2,
    }
)


def _lanes(data: bytes, nbytes: int) -> tuple[int, ...]:
    data = bytes(data)[:nbytes].ljust(nbytes, b"\0")
    return tuple(int.from_bytes(data[i : i + 4], "little") for i in range(0, nbytes, 4))


def _hex_lanes(lanes: tuple[int, ...]) -> str:
    return "".join(f"{x:08x}" for x in lanes[::-1]) or "-"


def _iso_seen(resp: int, lanes: tuple[int, ...]) -> bool:
    return resp == RESP_SLVERR and ISO_WORD in lanes


def _site_plan() -> dict[str, Counter]:
    """Proof-path wait sites per step and kind, from the step list (S11); 'dmi' retries are
    data-dependent and observation windows are counted against WINDOW_PLAN."""
    n_dom = len(DOMAINS)
    n_cells = len(CELLS)
    cell = Counter(handshake=1, sba_busy=4, ext_in=len(DRAIN_IDS))
    plan = {
        "S1": Counter(sba_busy=2 + 3 + 1, port_settle=2),
        "S2": Counter({k: v * n_dom * n_cells for k, v in cell.items()}),
        # Per domain: the 0 write, two cells of three, SRAM write and read; two cross reads.
        "S3": Counter(sba_busy=n_dom, ext_in=n_dom * (3 + 3 + 2) + 2),
        "S4": Counter(sba_busy=n_dom, ext_in=n_dom * 2),
        "S5": Counter({k: v * n_cells for k, v in cell.items()})
        + Counter(sba_busy=2, ext_in=2 * len(TRNG_PATHS) + 1 + 2 + len(TRNG_PATHS)),
        "S6": Counter(sba_busy=6, ext_in=3),
        # Halt, two ebreak waits; stub 4 + dcsr, a0/dpc twice, t0 once; never-isolated 8.
        "S7": Counter(
            dm_status=3,
            abstract=len(STUB) + 1 + 2 + 1 + 2,
            egress_ar=1,
            responder_hold=1,
            sba_busy=3,
            ext_in=2 + len(EFUSE_LOCALS) + 1 + 2,
        ),
        "S8": Counter(
            sba_busy=len(EARLY_DOMAINS) * len(GAPS) + 1,
            ext_in=len(EARLY_DOMAINS) * len(GAPS) * (len(EARLY_IDS) + 1),
        ),
        "S9": Counter(
            sba_busy=1 + 1 + 2 + 3 + 1 + 2,
            abstract=2,
            ext_in=2,
            egress_ar=1,
            reset_level=2,
            responder_hold=1,
            retire=1,
            port_settle=2,
        ),
        "S10": Counter(
            dm_status=3,
            abstract=len(STUB) + 1 + 3 + 2 + 2,
            sba_busy=len(DMA_REGS) + 2 + 2 + 1,
            ext_in=2 + 1 + 2,
            egress_ar=1,
            responder_hold=1,
            bite_req=2,
            reset_level=1,
            retire=1,
        ),
    }
    return plan


class smu_sep_reset_inflight_test_seq(smu_axi_in_sep_aperture_test_seq):
    """SEP software, JTAG and watchdog resets with ext_in and sep_out traffic outstanding."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.sb = test.env.scoreboard
        self.mem = test.cfg.axi_out_mem
        self.period = float(self.cfg.smu_clk_period_ns)
        self.master = None
        self.cyc = 0
        self.ar_hs: list[tuple[int, int]] = []
        self.aw_hs: list[tuple[int, int]] = []
        self.r_hs: list[tuple[int, int, int]] = []
        self.b_hs: list[tuple[int, int, int]] = []
        self.out_ar_valid: list[tuple[int, int]] = []
        self.out_ar_hs: list[tuple[int, int]] = []
        self.out_r_hs: list[int] = []
        self._out_arvalid_prev = 0
        self.sites: list[dict] = []
        self.windows: list[dict] = []
        self.dmi_ops = 0
        self.sba_writes = 0
        self.slow: Counter = Counter()
        self.spacing_ops = 0
        self.last_update = 0
        self.sb_mode: str | None = None
        self.sb_addr: int | None = None
        self.step = "S0"
        self.term = "SETUP"
        self.terms: dict[str, list] = {}
        self.failures: list[str] = []
        self.steps: dict[str, bool] = {}
        self.fallbacks: Counter = Counter()
        self.unverified: list[str] = []
        self.soft = False
        self.r: dict[str, object] = {}
        self.done = False

    # ---- bookkeeping ---------------------------------------------------------------------

    def _now(self) -> float:
        return float(get_sim_time(unit="ns"))

    def _enter(self, term: str, step: str, text: str) -> None:
        self.term = term
        self.step = step
        if term not in self.terms:
            self.terms[term] = [self._now(), 0]
        self._log(f"STEP {step} @{self._now():.1f}ns term={term}: {text}")

    def _count(self) -> None:
        self.terms.setdefault(self.term, [self._now(), 0])[1] += 1

    def _slow_op(self) -> None:
        self.slow[self.step] += 1
        self._count()

    def _site(self, kind: str, label: str, bound: int, used: int, last: str, expired: bool):
        self.sites.append(
            {
                "step": self.step,
                "kind": kind,
                "label": label,
                "bound": bound,
                "used": used,
                "last": last,
                "expired": int(expired),
            }
        )
        if expired:
            if self.soft:
                self._log(
                    f"OBSERVATION {self.step} TIMEOUT {kind} {label}: bound={bound} used={used} "
                    f"last_state={last} (recorded as expired; the remaining graded legs still run)"
                )
                return
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={bound} used={used} last_state={last}"
            )

    def _obs_window(self, obs: str, label: str, bound: int, used: int, done: bool, last: str):
        """An observation window: listed with its bound and cycles used, never a passed wait;
        one that ends without its completion is expired."""
        self.windows.append(
            {
                "step": self.step,
                "obs": obs,
                "label": label,
                "bound": bound,
                "used": used,
                "done": int(done),
                "expired": int(not done),
                "last": last,
            }
        )

    def _verdict(self, chk: str, line: str, got, want) -> None:
        """One checker compare; the scoreboard prints the evidence line only on a pass."""
        try:
            self.sb.expect_eq(line, got, want, evidence=chk)
        except AssertionError as exc:
            self.failures.append(str(exc))

    def _g(self, local: int) -> int:
        return WIN_BASE + local

    async def _tap(self) -> None:
        """Every ext_in handshake and the outbound AR/R activity, stamped with a cycle count."""
        dut = self.dut
        out = dut.u_axi_out_if
        while True:
            await RisingEdge(dut.clk_smu_i)
            self.cyc += 1
            c = self.cyc
            if sample(dut.ext_in_arvalid, "ext_in_arvalid") and sample(
                dut.ext_in_arready, "ext_in_arready"
            ):
                self.ar_hs.append((c, sample(dut.ext_in_arid, "ext_in_arid")))
            if sample(dut.ext_in_awvalid, "ext_in_awvalid") and sample(
                dut.ext_in_awready, "ext_in_awready"
            ):
                self.aw_hs.append((c, sample(dut.ext_in_awid, "ext_in_awid")))
            if sample(dut.ext_in_rvalid, "ext_in_rvalid") and sample(
                dut.ext_in_rready, "ext_in_rready"
            ):
                self.r_hs.append(
                    (c, sample(dut.ext_in_rid, "ext_in_rid"), sample(dut.ext_in_rresp, "rresp"))
                )
            if sample(dut.ext_in_bvalid, "ext_in_bvalid") and sample(
                dut.ext_in_bready, "ext_in_bready"
            ):
                self.b_hs.append(
                    (c, sample(dut.ext_in_bid, "ext_in_bid"), sample(dut.ext_in_bresp, "bresp"))
                )
            arvalid = sample(out.arvalid, "u_axi_out_if.arvalid")
            if arvalid and not self._out_arvalid_prev:
                self.out_ar_valid.append((c, sample(out.araddr, "u_axi_out_if.araddr")))
            self._out_arvalid_prev = arvalid
            if arvalid and sample(out.arready, "u_axi_out_if.arready"):
                self.out_ar_hs.append((c, sample(out.araddr, "u_axi_out_if.araddr")))
            if sample(out.rvalid, "u_axi_out_if.rvalid") and sample(
                out.rready, "u_axi_out_if.rready"
            ):
                self.out_r_hs.append(c)

    # ---- ext_in --------------------------------------------------------------------------

    def _start(
        self,
        *,
        write: bool,
        local: int,
        data=None,
        nbytes: int = 8,
        size: int = 3,
        ident: int = MISC_ID,
    ) -> dict:
        addr = self._g(local)
        if write:
            event = self.master.init_write(addr, data, size=size, id=ident)
        else:
            event = self.master.init_read(addr, nbytes, size=size, id=ident)
        self._count()
        return {
            "event": event,
            "write": write,
            "addr": addr,
            "id": ident,
            "issue": self.cyc,
            "nbytes": nbytes if not write else len(data),
            "end": None,
        }

    def _collect(self, rec: dict) -> tuple[int, tuple[int, ...]]:
        raw = rec["event"].data
        resp = worst_resp(getattr(raw, "resp", None))
        lanes = () if rec["write"] else _lanes(getattr(raw, "data", b""), rec["nbytes"])
        rec["resp"], rec["lanes"] = resp, lanes
        if rec["end"] is None:
            rec["end"] = self.cyc
        return resp, lanes

    async def _done(self, rec: dict, label: str) -> tuple[int, tuple[int, ...]]:
        """A graded ext_in completion: expiry fails with its last state."""
        start = self.cyc
        try:
            await with_timeout(rec["event"].wait(), round(EXT_IN_BOUND * self.period), "ns")
        except Exception:  # noqa: BLE001 -- the expiry is recorded and raised with its last state
            self._site(
                "ext_in",
                label,
                EXT_IN_BOUND,
                self.cyc - start,
                f"addr=0x{rec['addr']:x} id=0x{rec['id']:x} pending",
                True,
            )
            return -1, ()
        resp, lanes = self._collect(rec)
        self._site(
            "ext_in",
            label,
            EXT_IN_BOUND,
            self.cyc - start,
            f"resp={resp_name(resp)} lanes={[hex(x) for x in lanes]}",
            False,
        )
        return resp, lanes

    async def _observe(self, rec: dict, obs: str, label: str) -> tuple[int, int, tuple[int, ...]]:
        """An OBS-only ext_in outcome: a bounded window that reports done=0 when it ends."""
        start = self.cyc
        done = 1
        if not rec["event"].is_set():
            try:
                await with_timeout(rec["event"].wait(), round(EXT_IN_BOUND * self.period), "ns")
            except Exception:  # noqa: BLE001 -- an unanswered OBS access is reported as done=0
                done = 0
        if done:
            resp, lanes = self._collect(rec)
        else:
            resp, lanes = -1, ()
        self._obs_window(
            obs,
            label,
            EXT_IN_BOUND,
            self.cyc - start,
            done,
            f"resp={resp_name(resp) if done else '-'}",
        )
        return done, resp, lanes

    async def _rd(self, local: int, label: str, nbytes: int = 8, size: int = 3, ident=MISC_ID):
        return await self._done(
            self._start(write=False, local=local, nbytes=nbytes, size=size, ident=ident), label
        )

    async def _wr(self, local: int, value: int, label: str, nbytes: int = 8, size: int = 3):
        data = (value & ((1 << (8 * nbytes)) - 1)).to_bytes(nbytes, "little")
        resp, _ = await self._done(
            self._start(write=True, local=local, data=data, size=size), label
        )
        return resp

    def _r_pause(self, held: bool) -> None:
        self.master.driver.channels["r_ready_delay"].pause = held

    def _b_pause(self, held: bool) -> None:
        self.master.driver.channels["b_ready_delay"].pause = held

    async def _wait_ar(self, idents, after: int, label: str) -> list[int]:
        used = 0
        while True:
            got = [c for c, i in self.ar_hs if c > after and i in idents]
            if len(got) >= len(idents):
                break
            if used >= HS_BOUND:
                self._site("handshake", label, HS_BOUND, used, f"ar seen={len(got)}", True)
            used += 1
            await RisingEdge(self.dut.clk_smu_i)
        self._site("handshake", label, HS_BOUND, used, f"ar seen={len(got)}", False)
        return got

    def _hs_cycle(self, hs, ident: int, after: int) -> int:
        for c, i, *_ in hs:
            if c > after and i == ident:
                return c
        return -1

    # ---- debug module transport ----------------------------------------------------------

    async def _scan(self, jtag, req: int) -> int:
        """One dmi DR scan; records the cycle its Update-DR completed."""
        value, width = network_scan(
            ptap_3dcr_value(config_hold=1, select=1), PTAP_3DCR_WIDTH, req, DMI_DR_WIDTH
        )
        captured = await jtag.shift_dr(value, width, back_to_rti=True)
        self.last_update = self.cyc
        for _ in range(DMI_IDLE_TCKS):
            await jtag.step_tms(0)
        return sep_dr_from_capture(captured, DMI_DR_WIDTH)

    async def _collect_dmi(self, jtag, label: str, after_op=None) -> int:
        if after_op is not None:
            after_op()
        status = DMI_STATUS_BUSY
        value = 0
        used = 0
        while used < DMI_RETRIES:
            _, value, status = unpack_dmi(await self._scan(jtag, pack_dmi(0, 0, op=DMI_OP_NOP)))
            used += 1
            if status != DMI_STATUS_BUSY:
                break
        self._site("dmi", label, DMI_RETRIES, used, f"status={status}", status == DMI_STATUS_BUSY)
        if status != DMI_STATUS_OK:
            raise AssertionError(f"DMI {label} status={status}")
        return value

    async def _dmi(self, jtag, addr: int, data: int, op: int, after_op=None) -> int:
        """One DMI op collected with NOP scans; after_op runs right after its Update-DR."""
        self.dmi_ops += 1
        await self._scan(jtag, pack_dmi(addr, data, op=op))
        update = self.last_update
        value = await self._collect_dmi(jtag, f"op{op}@0x{addr:02x}", after_op)
        self.last_update = update
        return value

    async def _dmi_chain(self, jtag, ops, label: str) -> list[int]:
        """Consecutive DMI ops, each scan collecting the one before; returns Update-DR cycles."""
        updates = []
        for i, (addr, data, op) in enumerate(ops):
            self.dmi_ops += 1
            captured = await self._scan(jtag, pack_dmi(addr, data, op=op))
            updates.append(self.last_update)
            if i:
                _, _, status = unpack_dmi(captured)
                if status != DMI_STATUS_OK:
                    raise AssertionError(f"DMI chain {label} op {i - 1} status={status}")
        await self._collect_dmi(jtag, label)
        return updates

    # ---- system bus ----------------------------------------------------------------------

    async def _sb_poll_raw(self, jtag) -> tuple[int, int]:
        """sbcs read until sbbusy clears or SBA_POLLS reads; returns (sbcs, reads used)."""
        used = 0
        sbcs = SBCS_SBBUSY
        while used < SBA_POLLS:
            sbcs = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            used += 1
            if not sbcs & SBCS_SBBUSY:
                break
        return sbcs, used

    async def _sb_poll(self, jtag, label: str) -> int:
        sbcs, used = await self._sb_poll_raw(jtag)
        self._site(
            "sba_busy", label, SBA_POLLS, used, f"sbcs=0x{sbcs:08x}", bool(sbcs & SBCS_SBBUSY)
        )
        return sbcs

    async def _sb_status(self, jtag, sbcs: int) -> int:
        if sbcs & SBCS_SBBUSY:
            self.sb_mode = None
            return 9
        err = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        if err or sbcs & SBCS_SBBUSYERROR:
            await self._dmi(jtag, SBCS_ADDR, SBCS_SBERROR_W1C | SBCS_SBBUSYERROR, DMI_OP_WRITE)
            self.sb_mode = None
            return err or 8
        return 0

    async def _sb_target(self, jtag, mode: str, addr: int) -> None:
        if self.sb_mode != mode:
            sbcs = SBCS_SBACCESS_32 | SBCS_SBERROR_W1C
            if mode == "r":
                sbcs |= SBCS_SBREADONADDR
            await self._dmi(jtag, SBCS_ADDR, sbcs, DMI_OP_WRITE)
            self.sb_mode = mode
            self.sb_addr = None
        if mode == "w" and self.sb_addr != addr:
            await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
            self.sb_addr = addr

    async def _sb_launch(self, jtag, data: int, after_op=None) -> int:
        """sbdata0 write that starts the prepared write; returns its Update-DR cycle."""
        self.sba_writes += 1
        self._slow_op()
        await self._dmi(jtag, SBDATA0_ADDR, data, DMI_OP_WRITE, after_op)
        return self.last_update

    async def _sbw(self, jtag, addr: int, data: int, label: str, *, strict: bool = True) -> int:
        await self._sb_target(jtag, "w", addr)
        await self._sb_launch(jtag, data)
        err = await self._sb_status(jtag, await self._sb_poll(jtag, label))
        if err and strict and not self.soft:
            raise AssertionError(f"system-bus write {label} 0x{addr:08x}: sberror={err}")
        return err

    async def _sbr(self, jtag, addr: int, label: str, *, strict: bool = True) -> tuple[int, int]:
        await self._sb_target(jtag, "r", addr)
        self._slow_op()
        await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
        self.sb_addr = addr
        err = await self._sb_status(jtag, await self._sb_poll(jtag, label))
        value = await self._dmi(jtag, SBDATA0_ADDR, 0, DMI_OP_READ) if not err else 0
        if err and strict and not self.soft:
            raise AssertionError(f"system-bus read {label} 0x{addr:08x}: sberror={err}")
        return err, value

    async def _sb_window(
        self, jtag, obs: str, label: str, addr: int, *, write: bool = False, data: int = 0
    ) -> tuple[int, int, int | None, int, int]:
        """A system-bus access whose busy poll is an observation window; returns
        (done, sberror, read value or None, last sbcs, polls used)."""
        if write:
            await self._sb_target(jtag, "w", addr)
            await self._sb_launch(jtag, data)
        else:
            await self._sb_target(jtag, "r", addr)
            self._slow_op()
            await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
            self.sb_addr = addr
        sbcs, used = await self._sb_poll_raw(jtag)
        done = int(not sbcs & SBCS_SBBUSY)
        err = await self._sb_status(jtag, sbcs)
        value = None
        if not write and done and not err:
            value = await self._dmi(jtag, SBDATA0_ADDR, 0, DMI_OP_READ)
        self._obs_window(obs, label, SBA_POLLS, used, done, f"sbcs=0x{sbcs:08x} sberror={err}")
        return done, err, value, sbcs, used

    async def _sba_wait(self, jtag, what: str) -> None:
        err = await self._sb_status(jtag, await self._sb_poll(jtag, what))
        if err:
            raise AssertionError(f"system-bus {what}: sberror={err}")

    async def _sba_write64(self, jtag, addr: int, data: int) -> None:
        self.sba_writes += 1
        self._slow_op()
        self.sb_mode = None
        await super()._sba_write64(jtag, addr, data)

    async def _port_settles(self, name: str, want: int) -> int:
        observed = await super()._port_settles(name, want)
        self._site(
            "port_settle", name, PORT_POLL_CYCLES, 0, f"{name}=0x{observed:x}", observed != want
        )
        return observed

    async def _swrst(self, jtag, value: int, label: str) -> int:
        return await self._sbw(jtag, SWRST_LOCAL, value, label)

    async def _program_window_and_filter(self, jtag) -> None:
        await self._window(jtag, WIN_BASE, WIN_SIZE)
        await self._sbw(jtag, OUTBOUND_START_ADDR, EGRESS_ADDR, "filter_start")
        await self._sbw(jtag, OUTBOUND_END_ADDR, EGRESS_PAGE_END, "filter_end")
        await self._sbw(jtag, OUTBOUND_FILTER_CONFIG, OUTBOUND_CFG_OPEN, "filter_cfg")

    # ---- hart control --------------------------------------------------------------------

    async def _abstract(self, jtag, command: int, label: str) -> None:
        self._slow_op()
        await self._dmi(jtag, COMMAND, command, DMI_OP_WRITE)
        used = 0
        status = ABSTRACTCS_BUSY
        while used < ABSTRACT_POLLS:
            status = await self._dmi(jtag, ABSTRACTCS, 0, DMI_OP_READ)
            used += 1
            if not status & ABSTRACTCS_BUSY:
                break
        self._site(
            "abstract",
            label,
            ABSTRACT_POLLS,
            used,
            f"abstractcs=0x{status:08x}",
            bool(status & ABSTRACTCS_BUSY),
        )
        cmderr = (status >> CMDERR_SHIFT) & CMDERR_MASK
        if cmderr:
            await self._dmi(jtag, ABSTRACTCS, CMDERR_MASK << CMDERR_SHIFT, DMI_OP_WRITE)
            raise AssertionError(f"abstract command {label} 0x{command:08x} cmderr={cmderr}")

    async def _reg_write(self, jtag, regno: int, value: int) -> None:
        await self._dmi(jtag, DATA0, value & 0xFFFF_FFFF, DMI_OP_WRITE)
        await self._abstract(jtag, AARSIZE_32 | TRANSFER | WRITE | regno, f"wr_reg_0x{regno:x}")

    async def _reg_read(self, jtag, regno: int) -> int:
        await self._abstract(jtag, AARSIZE_32 | TRANSFER | regno, f"rd_reg_0x{regno:x}")
        return await self._dmi(jtag, DATA0, 0, DMI_OP_READ)

    async def _mem_write(self, jtag, addr: int, value: int) -> None:
        await self._dmi(jtag, DATA1, addr, DMI_OP_WRITE)
        await self._dmi(jtag, DATA0, value, DMI_OP_WRITE)
        await self._abstract(jtag, CMD_ACCESS_MEMORY | AARSIZE_32 | WRITE, f"wr_mem_0x{addr:x}")

    async def _dm_wait(self, jtag, mask: int, polls: int, label: str, *, fallback=False) -> bool:
        used = 0
        status = 0
        while used < polls:
            status = await self._dmi(jtag, DMSTATUS, 0, DMI_OP_READ)
            used += 1
            if status & mask == mask:
                break
        reached = status & mask == mask
        self._site(
            "dm_status",
            label,
            polls,
            used,
            f"dmstatus=0x{status:08x}",
            not reached and not fallback,
        )
        return reached

    async def _halt(self, jtag, label: str) -> None:
        self._slow_op()
        await self._dmi(jtag, DMCONTROL, DMACTIVE | HALTREQ, DMI_OP_WRITE)
        await self._dm_wait(jtag, ALLHALTED, HALT_POLLS, f"{label}_halt")

    async def _stopped(self, jtag, label: str) -> bool:
        """The stub's ebreak after a resume: allresumeack and allhalted both set."""
        if await self._dm_wait(
            jtag, ALLHALTED | ALLRESUMEACK, EBREAK_POLLS, f"{label}_ebreak", fallback=True
        ):
            return True
        self.fallbacks[self.step] += 1
        await self._halt(jtag, f"{label}_fallback")
        return False

    async def _install_stub(self, jtag) -> None:
        for addr, insn in STUB:
            await self._mem_write(jtag, addr, insn)
        await self._reg_write(jtag, CSR_DCSR, DCSR_EBREAKM_M)

    def _hold_responder(self) -> None:
        self.mem.enable_backpressure(channels=("ar",), stall_cycles=RESPONDER_GUARD)

    def _release_responder(self, ar_valid: int, label: str) -> int:
        self.mem.disable_backpressure()
        used = self.cyc - ar_valid if ar_valid >= 0 else 0
        self._site(
            "responder_hold",
            label,
            RESPONDER_HOLD,
            used,
            f"ar_valid@{ar_valid} ar_hs={len(self.out_ar_hs)} r_hs={len(self.out_r_hs)}",
            used > RESPONDER_HOLD,
        )
        return used

    async def _wait_egress_ar(self, addr: int, after: int, label: str) -> int:
        """The CPU load's AR on smu_axi_out; an expiry is recorded as expired and returns -1
        so the remaining legs still run (the leg is reported unverified)."""
        used = 0
        while True:
            hit = [c for c, a in self.out_ar_valid if c > after and a == addr]
            if hit:
                break
            if used >= EGRESS_AR_BOUND:
                self.sites.append(
                    {
                        "step": self.step,
                        "kind": "egress_ar",
                        "label": label,
                        "bound": EGRESS_AR_BOUND,
                        "used": used,
                        "last": f"arvalid edges={len(self.out_ar_valid)} no load issued",
                        "expired": 1,
                    }
                )
                self.unverified.append(
                    f"{self.step} {label}: the CPU-issued load never reached smu_axi_out"
                )
                self._log(f"OBSERVATION {self.step} {label}: no CPU load AR within the bound")
                return -1
            used += 1
            await RisingEdge(self.dut.clk_smu_i)
        self._site("egress_ar", label, EGRESS_AR_BOUND, used, f"arvalid at {hit[0]}", False)
        return hit[0]

    async def _wait_pin(self, kind: str, label: str, handle, name: str, want: int, bound: int):
        used = 0
        while True:
            level = sample(handle, name)
            if level == want:
                break
            if used >= bound:
                self._site(kind, label, bound, used, f"{name}={level}", True)
            used += 1
            await RisingEdge(self.dut.clk_smu_i)
        self._site(kind, label, bound, used, f"{name}={level}", False)
        return self.cyc

    async def _first_retire(self, label: str) -> int:
        used = 0
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smu_i)
            if sample(dut.sep_trace_valid_o, "sep_trace_valid_o", allow_xz=True):
                pc = sample(dut.sep_pc_o, "sep_pc_o")
                break
            used += 1
            if used >= RETIRE_BOUND:
                self._site("retire", label, RETIRE_BOUND, used, "sep_trace_valid_o=0", True)
        self._site("retire", label, RETIRE_BOUND, used, f"pc=0x{pc:08x}", False)
        return pc

    async def _net_ir(self, jtag, opcode: int, label: str) -> None:
        value, width = network_ir_scan(opcode, SEP_TAP_IR_DMI)
        await jtag.shift_ir(value, width=width, back_to_rti=True)
        require_jtag_tdo_resolved(f"IR {label}")

    async def _ic_reset(self, jtag, image: int, label: str, sep_request: int | None = None):
        """One IC_RESET scan; returns the SEP dmi capture carried through the network."""
        request = pack_dmi(0, 0, op=DMI_OP_NOP) if sep_request is None else sep_request
        word, total = network_scan(image, SMU_IC_RESET_LEN, request, DMI_DR_WIDTH)
        raw = await jtag.shift_dr(word, total, back_to_rti=True)
        self.last_update = self.cyc
        require_jtag_tdo_resolved(f"DR {label}")
        for _ in range(DMI_IDLE_TCKS):
            await jtag.step_tms(0)
        self._slow_op()
        self._log(f"SCAN IC_RESET {label} image=0x{image:x} sep_request=0x{request:x}")
        return sep_dr_from_capture(raw, DMI_DR_WIDTH)

    async def _rebringup(self, jtag, why: str) -> None:
        """The S1 debug-module bring-up on the still-spliced SEP STAP: the network DMI IR and
        dmcontrol.dmactive, then the sticky system-bus error bits cleared."""
        await self._net_ir(jtag, DTP_IR_TAP_3DCR, f"dmi_{why}")
        self._slow_op()
        await self._dmi(jtag, DMCONTROL, DMACTIVE, DMI_OP_WRITE)
        await self._dmi(jtag, SBCS_ADDR, SBCS_SBERROR_W1C | SBCS_SBBUSYERROR, DMI_OP_WRITE)
        self.sb_mode = None
        self.sb_addr = None
        self._log(f"OBSERVATION debug path re-established after {why}: DMI IR, dmactive written")

    async def _first_sba(self, jtag, leg: str) -> int:
        """The first system-bus access after a SEP reset: a read of SW_RESET_N polled for the
        normal bound. Busy at the bound, a sticky busy error or an inactive debug module
        (sbcs.sbversion 0) repeats the bring-up. The poll is an observation window."""
        await self._sb_target(jtag, "r", SWRST_LOCAL)
        self._slow_op()
        await self._dmi(jtag, SBADDRESS0_ADDR, SWRST_LOCAL, DMI_OP_WRITE)
        self.sb_addr = SWRST_LOCAL
        sbcs, used = await self._sb_poll_raw(jtag)
        inactive = (sbcs >> SBCS_SBVERSION_SHIFT) == 0
        needed = int(bool(sbcs & (SBCS_SBBUSY | SBCS_SBBUSYERROR)) or inactive)
        self._obs_window(
            "OBS-SEPRST-REBRINGUP",
            f"{leg}_first_sba",
            SBA_POLLS,
            used,
            not sbcs & SBCS_SBBUSY,
            f"sbcs=0x{sbcs:08x}",
        )
        if needed:
            await self._rebringup(jtag, f"the {leg} reset")
        else:
            await self._sb_status(jtag, sbcs)
        self._log(
            f"OBS-SEPRST-REBRINGUP: leg={leg} needed={needed} sbcs=0x{sbcs:08x} polls={used} "
            f"dm_inactive={int(inactive)}"
        )
        return needed

    # ---- S1 ------------------------------------------------------------------------------

    async def _s1_setup(self, jtag) -> None:
        self._enter("SETUP", "S1", "aperture, egress filter, responder, SW_RESET_N precondition")
        await self._program_window_and_filter(jtag)
        self.master = await make_smu_axi_master(
            cocotb.top, self.dut.clk_smu_i, smc_primary_reset(self.dut)
        )
        _, sw = await self._sbr(jtag, SWRST_LOCAL, "s1_swrst")
        self._log(
            f"OBSERVATION S1 SW_RESET_N over the system bus value=0x{sw:x} "
            f"(precondition 0x{SWRST_POR:02x}, not claimed)"
        )
        self.steps["S1"] = True

    # ---- S2..S5 --------------------------------------------------------------------------

    async def _swrst_rd(self, jtag, label: str) -> tuple[int, int]:
        """SW_RESET_N over the system bus: (sberror, value under the field mask)."""
        err, value = await self._sbr(jtag, SWRST_LOCAL, label, strict=False)
        return err, value & SWRST_FIELD_MASK

    async def _drain_cell(self, jtag, dom: str, bit: int, local: int, cell: str) -> dict:
        """Four reads held by RREADY, the system-bus 0 write, RREADY released before / after;
        SW_RESET_N is read back after the 0 write and after the 1 write."""
        zero = SWRST_POR & ~(1 << bit)
        await self._sb_target(jtag, "w", SWRST_LOCAL)
        mark = self.cyc
        self._r_pause(True)
        reads = []
        try:
            for ident in DRAIN_IDS:
                reads.append(self._start(write=False, local=local, nbytes=8, ident=ident))
            ars = await self._wait_ar(DRAIN_IDS, mark, f"drain_{dom}_{cell}_ar")
            last_ar = max(ars)
            before = cell == "rready_before"
            write_cyc = await self._sb_launch(
                jtag, zero, after_op=(lambda: self._r_pause(False)) if before else None
            )
            err = await self._sb_status(jtag, await self._sb_poll(jtag, f"drain_{dom}_{cell}_wr0"))
            reported = self.cyc
        finally:
            self._r_pause(False)
        if err:
            raise AssertionError(f"system-bus SW_RESET_N 0x{zero:02x} sberror={err}")
        accepted = done = 0
        for rec in reads:
            ar = self._hs_cycle(self.ar_hs, rec["id"], mark)
            resp, lanes = await self._done(rec, f"drain_{dom}_{cell}_id{rec['id']:x}")
            used = self.sites[-1]["used"]
            r_cyc = self._hs_cycle(self.r_hs, rec["id"], ar)
            r_seen = int(r_cyc > 0)
            if 0 < ar < write_cyc:
                accepted += 1
                done += r_seen
            self._obs_window(
                "OBS-SEPRST-DRAIN",
                f"{dom}_{cell}_id{rec['id']:x}",
                EXT_IN_BOUND,
                used,
                r_seen,
                f"resp={resp_name(resp)}",
            )
            self._log(
                f"OBS-SEPRST-DRAIN: dom={dom} cell={cell} arid=0x{rec['id']:x} done={r_seen} "
                f"resp={resp_name(resp)} lane0=0x{lanes[0]:08x} lane1=0x{lanes[1]:08x} "
                f"offset_last_ar_to_wr={write_cyc - last_ar} cyc_from_0wr={r_cyc - write_cyc} "
                f"wr_reported_at={reported - write_cyc}"
            )
        held = await self._swrst_rd(jtag, f"drain_{dom}_{cell}_rd0")
        await self._swrst(jtag, SWRST_POR, f"drain_{dom}_{cell}_wr1")
        released = await self._swrst_rd(jtag, f"drain_{dom}_{cell}_rd1")
        self._log(
            f"OBSERVATION S2 {dom} {cell} SW_RESET_N after the 0 write=0x{held[1]:02x} "
            f"sberror={held[0]}, after the 1 write=0x{released[1]:02x} sberror={released[0]}"
        )
        return {"accepted": accepted, "done": done, "swrst": [held, released]}

    async def _cells(self, jtag, dom: str, bit: int, local: int) -> dict:
        totals = {"accepted": 0, "done": 0, "cells": 0, "swrst": []}
        for cell in CELLS:
            got = await self._drain_cell(jtag, dom, bit, local, cell)
            totals["accepted"] += got["accepted"]
            totals["done"] += got["done"]
            totals["cells"] += 1
            totals["swrst"] += got["swrst"]
        return totals

    @staticmethod
    def _cells_swrst_want(bit: int) -> list[tuple[int, int]]:
        """Each drain cell reads SW_RESET_N back as the 0 write, then as the 1 write."""
        return [(0, SWRST_POR & ~(1 << bit)), (0, SWRST_POR)] * len(CELLS)

    async def _new_cell(self, dom: str, local: int, cell: str) -> dict:
        recs = {
            "rd64": self._start(write=False, local=local, nbytes=8, size=3, ident=CELL_IDS["rd64"]),
            "rd32": self._start(write=False, local=local, nbytes=4, size=2, ident=CELL_IDS["rd32"]),
            "wr": self._start(write=True, local=local, data=bytes(4), size=2, ident=CELL_IDS["wr"]),
        }
        out = {}
        for name, rec in recs.items():
            resp, lanes = await self._done(rec, f"{dom}_{cell}_{name}")
            out[name] = (resp, lanes)
            if name != "wr":
                self._log(
                    f"OBS-SEPRST-ISO-LANE: dom={dom} size={64 if name == 'rd64' else 32} "
                    f"resp={resp_name(resp)} rdata={_hex_lanes(lanes)}"
                )
        return out

    async def _isolated(self, jtag, dom: str, bit: int, local: int) -> dict:
        self._enter("ISOLATED", "S3", f"{dom}: new accesses during the drain and held")
        zero = SWRST_POR & ~(1 << bit)
        write_cyc = await self._sb_launch_full(jtag, SWRST_LOCAL, zero, f"iso_{dom}_wr0")
        self._log(
            f"OBSERVATION S3 {dom} during-drain cell issued {self.cyc - write_cyc} cycles after "
            "the system-bus 0 write's Update-DR, right after it reported complete"
        )
        cells = {"drain": await self._new_cell(dom, local, "drain")}
        await ClockCycles(self.dut.clk_smu_i, HELD_CELL_GAP)
        cells["held"] = await self._new_cell(dom, local, "held")
        if dom == "otbn":
            self.r.setdefault("cross", {})["otbn->aes"] = (
                await self._rd(DOMAIN_BY_NAME["aes"][1], "iso_otbn_aes_rd")
            )[0]
        elif dom == "aes":
            self.r.setdefault("cross", {})["aes->hmac"] = (
                await self._rd(DOMAIN_BY_NAME["hmac"][1], "iso_aes_hmac_rd")
            )[0]
        await self._sram_rw(dom, bit)
        return cells

    async def _sb_launch_full(self, jtag, addr: int, value: int, label: str) -> int:
        await self._sb_target(jtag, "w", addr)
        write_cyc = await self._sb_launch(jtag, value)
        err = await self._sb_status(jtag, await self._sb_poll(jtag, label))
        if err:
            raise AssertionError(f"system-bus write {label}: sberror={err}")
        return write_cyc

    async def _sram_rw(self, dom: str, bit: int) -> None:
        word = 0x5EB0_0000_0000_0000 | (bit << 8) | 0x11
        sram = SRAM_LOCAL + 0x100 + 8 * bit
        w = await self._wr(sram, word, f"held_{dom}_sram_wr")
        r, lanes = await self._rd(sram, f"held_{dom}_sram_rd")
        ok = lanes == _lanes(word.to_bytes(8, "little"), 8)
        self.r.setdefault("sram_rw", []).append((dom, (w, r, ok)))
        self._log(
            f"OBSERVATION SRAM under {dom} held: wr={resp_name(w)} rd={resp_name(r)} "
            f"data={_hex_lanes(lanes)} match={int(ok)}"
        )

    async def _released(self, jtag, dom: str, local: int) -> tuple[int, int]:
        self._enter("RELEASE", "S4", f"{dom}: the 1 write, fresh read and write")
        await self._swrst(jtag, SWRST_POR, f"rel_{dom}_wr1")
        rd, _ = await self._rd(local, f"rel_{dom}_rd")
        wr = await self._wr(local, 0, f"rel_{dom}_wr", nbytes=4, size=2)
        return rd, wr

    @staticmethod
    def _cell_view(cells: dict) -> dict:
        view = {}
        for cell, accesses in cells.items():
            view[(cell, "rd64")] = (accesses["rd64"][0], accesses["rd64"][1])
            view[(cell, "rd32")] = (accesses["rd32"][0], accesses["rd32"][1][:1])
            view[(cell, "wr")] = accesses["wr"][0]
        return view

    @staticmethod
    def _cell_want() -> dict:
        want = {}
        for cell in ("drain", "held"):
            want[(cell, "rd64")] = (RESP_SLVERR, (ISO_WORD, ISO_WORD))
            want[(cell, "rd32")] = (RESP_SLVERR, (ISO_WORD,))
            want[(cell, "wr")] = RESP_SLVERR
        return want

    async def _domains(self, jtag) -> None:
        cells = {}
        self._enter("DRAIN", "S2", "drain cells, five domains x two cells")
        for dom, bit, local in DOMAINS:
            cells[dom] = await self._cells(jtag, dom, bit, local)
        self.r["drain_cells"] = sum(c["cells"] for c in cells.values())
        self.steps["S2"] = True
        for dom, bit, local in DOMAINS:
            new = await self._isolated(jtag, dom, bit, local)
            rel = await self._released(jtag, dom, local)
            c = cells[dom]
            chk = f"CHK-SEPRST-{dom.upper()}-ISOLATE"
            line = (
                f"{chk}: drained={c['done']}/{c['accepted']} across the write; SW_RESET_N read "
                f"back 0x{SWRST_POR & ~(1 << bit):02X}/0x{SWRST_POR:02X} after each drain 0/1 "
                "write; new rd SLVERR 0x1501A7ED1501A7ED (drain, held); new wr SLVERR (drain, "
                "held); released rd OKAY wr OKAY"
            )
            self._verdict(
                chk,
                line,
                (
                    c["accepted"] == len(CELLS) * len(DRAIN_IDS),
                    c["done"] == c["accepted"],
                    c["swrst"],
                    self._cell_view(new),
                    rel,
                ),
                (
                    True,
                    True,
                    self._cells_swrst_want(bit),
                    self._cell_want(),
                    (RESP_OKAY, RESP_OKAY),
                ),
            )
        self.steps["S3"] = self.steps["S4"] = True

    async def _trng(self, jtag) -> None:
        self._enter("TRNG", "S5", "ESRC drain cells, ESRC/CSRNG/EDN isolated, pool, release")
        bit = SWRST_TRNG_BIT
        cells = await self._cells(jtag, "trng", bit, TRNG_PATHS[0][1])
        await self._swrst(jtag, SWRST_POR & ~(1 << bit), "trng_wr0")
        paths = {}
        for name, local in TRNG_PATHS:
            resp, lanes = await self._rd(local, f"trng_{name}_rd")
            wr = await self._wr(local, 0, f"trng_{name}_wr", nbytes=4, size=2)
            paths[name] = ((resp, lanes), wr)
            self._log(
                f"OBS-SEPRST-ISO-LANE: dom=trng/{name} size=64 resp={resp_name(resp)} "
                f"rdata={_hex_lanes(lanes)}"
            )
        pool_resp, pool_lanes = await self._rd(POOL_LOCAL, "trng_pool_rd")
        self._log(
            f"OBSERVATION S5 entropy pool while held resp={resp_name(pool_resp)} "
            f"rdata={_hex_lanes(pool_lanes)}"
        )
        await self._sram_rw("trng", bit)
        await self._swrst(jtag, SWRST_POR, "trng_wr1")
        fresh = []
        for name, local in TRNG_PATHS:
            resp, _ = await self._rd(local, f"trng_{name}_fresh")
            fresh.append(resp)
        line = (
            "CHK-SEPRST-TRNG-ISOLATE: SW_RESET_N read back "
            f"0x{SWRST_POR & ~(1 << bit):02X}/0x{SWRST_POR:02X} after each drain 0/1 write; "
            "esrc/csrng/edn rd SLVERR 0x1501A7ED x2, wr SLVERR; "
            f"pool answers (not iso); released {fresh.count(RESP_OKAY)}/3 OKAY"
        )
        self._verdict(
            "CHK-SEPRST-TRNG-ISOLATE",
            line,
            (
                cells["accepted"] == len(CELLS) * len(DRAIN_IDS),
                cells["done"] == cells["accepted"],
                cells["swrst"],
                paths,
                _iso_seen(pool_resp, pool_lanes),
                fresh,
            ),
            (
                True,
                True,
                self._cells_swrst_want(bit),
                {
                    name: ((RESP_SLVERR, (ISO_WORD, ISO_WORD)), RESP_SLVERR)
                    for name, _ in TRNG_PATHS
                },
                False,
                [RESP_OKAY] * 3,
            ),
        )
        self.r["trng_cells"] = cells["cells"]
        self.steps["S5"] = True

    # ---- S6 ------------------------------------------------------------------------------

    async def _km(self, jtag) -> None:
        self._enter("KM", "S6", "KM mailbox status word with bit 0 held, released and held")
        reads = {}
        reads["por-held"] = await self._rd(KM_STATUS_LOCAL, "km_por_rd", nbytes=4, size=2)
        sw = {}
        await self._swrst(jtag, SWRST_ALL_RELEASED, "km_wr1")
        sw["released"] = await self._swrst_rd(jtag, "km_swrst_rd")
        reads["released"] = await self._rd(KM_STATUS_LOCAL, "km_rel_rd", nbytes=4, size=2)
        await self._swrst(jtag, SWRST_POR, "km_wr0")
        sw["held"] = await self._swrst_rd(jtag, "km_swrst_rd0")
        reads["held"] = await self._rd(KM_STATUS_LOCAL, "km_held_rd", nbytes=4, size=2)
        await self._swrst(jtag, SWRST_ALL_RELEASED, "km_wr1_final")
        sw["final"] = await self._swrst_rd(jtag, "km_swrst_rd_final")
        self._log(
            f"OBSERVATION S6 mailbox@0xC (0x{KM_STATUS_LOCAL:08x}; status value logged, not "
            "compared) "
            + " ".join(f"{k}={resp_name(v[0])}/{_hex_lanes(v[1])}" for k, v in reads.items())
            + " SW_RESET_N "
            + " ".join(f"{k}=0x{v[1]:02x}/sberror={v[0]}" for k, v in sw.items())
        )
        self._verdict(
            "CHK-SEPRST-KM-MAILBOX",
            "CHK-SEPRST-KM-MAILBOX: mailbox@0xC OKAY (por-held, released, held); SW_RESET_N "
            f"read back 0x{SWRST_ALL_RELEASED:02X}/0x{SWRST_POR:02X}/0x{SWRST_ALL_RELEASED:02X} "
            "after the 1/0/1 writes (bit0 1/0/1)",
            ({k: (v[0], ISO_WORD in v[1]) for k, v in reads.items()}, sw),
            (
                {k: (RESP_OKAY, False) for k in reads},
                {
                    "released": (0, SWRST_ALL_RELEASED),
                    "held": (0, SWRST_POR),
                    "final": (0, SWRST_ALL_RELEASED),
                },
            ),
        )
        self.steps["S6"] = True

    # ---- S7 ------------------------------------------------------------------------------

    async def _cpu_load_across(
        self,
        jtag,
        load_addr: int,
        word: int,
        wr_addr: int,
        wr_val: int,
        label: str,
        on_launch=None,
    ) -> dict:
        """Resume into the stub's load with the responder holding it; the system-bus write
        prepared at wr_addr is launched in the scan after the resume request."""
        self.mem.write32(load_addr, word)
        await self._reg_write(jtag, REG_A0, load_addr)
        await self._reg_write(jtag, CSR_DPC, STUB_LOAD)
        await self._sb_target(jtag, "w", wr_addr)
        if on_launch is not None:
            on_launch()
        mark = self.cyc
        self._hold_responder()
        self._slow_op()
        self._slow_op()
        self.sba_writes += 1
        updates = await self._dmi_chain(
            jtag,
            ((DMCONTROL, DMACTIVE | RESUMEREQ, DMI_OP_WRITE), (SBDATA0_ADDR, wr_val, DMI_OP_WRITE)),
            f"{label}_resume_wr",
        )
        write_cyc = updates[1]
        ar_valid = await self._wait_egress_ar(load_addr, mark, f"{label}_egress_ar")
        ar_hs_before = [c for c, a in self.out_ar_hs if mark < c <= write_cyc and a == load_addr]
        used = self._release_responder(ar_valid, f"{label}_egress")
        sberr = await self._sb_status(jtag, await self._sb_poll(jtag, f"{label}_wr"))
        return {
            "mark": mark,
            "ar_valid": ar_valid,
            "write": write_cyc,
            "held_across": 0 <= ar_valid < write_cyc and not ar_hs_before,
            "hold_used": used,
            "sberr": sberr,
        }

    async def _all_domains(self, jtag) -> None:
        self._enter("ALL_DOMAINS", "S7", "CPU egress load held across SW_RESET_N = 0x00")
        await self._halt(jtag, "s7")
        await self._install_stub(jtag)
        word = 0x5EB0_70C1
        got = await self._cpu_load_across(
            jtag, EGRESS_ADDR, word, SWRST_LOCAL, SWRST_ALL_HELD, "s7"
        )
        stopped = await self._stopped(jtag, "s7_load")
        t0 = await self._reg_read(jtag, REG_T0)
        s7_sw = await self._swrst_rd(jtag, "s7_swrst_rd")
        self._log(
            f"OBSERVATION S7 egress load arvalid@{got['ar_valid']} SW_RESET_N=0x00 "
            f"written@{got['write']} sberror={got['sberr']} read back=0x{s7_sw[1]:02x} "
            f"(sberror={s7_sw[0]}) held_across={got['held_across']} "
            f"hold_used={got['hold_used']} ebreak={int(stopped)} t0=0x{t0:08x} "
            f"responder word=0x{word:08x}"
        )
        if not stopped:
            self.unverified.append("S7 CPU egress load: the stub's ebreak was not reached")
        # The SMC window from the CPU: route and outcome recorded, not compared.
        smc_addr = self._smc_view(SMC_CHIP_CONFIG_VERSION_LO)
        before = sample(self.dut.smc_xbar_in_ar_count_o, "smc_xbar_in_ar_count_o")
        await self._reg_write(jtag, REG_A0, smc_addr)
        await self._reg_write(jtag, CSR_DPC, STUB_LOAD)
        self._slow_op()
        await self._dmi(jtag, DMCONTROL, DMACTIVE | RESUMEREQ, DMI_OP_WRITE)
        smc_stopped = await self._stopped(jtag, "s7_smc")
        after = sample(self.dut.smc_xbar_in_ar_count_o, "smc_xbar_in_ar_count_o")
        self._log(
            f"OBS-SEPRST-SMCWIN-ROUTE: smc_xbar_in_ar=+{after - before} "
            f"resp={'OKAY' if smc_stopped else 'trap_or_stall'} addr=0x{smc_addr:x} "
            f"ebreak={int(smc_stopped)}"
        )
        km_r = await self._rd(KM_STATUS_LOCAL, "s7_km_rd", nbytes=4, size=2)
        self._log(
            f"OBSERVATION S7 KM mailbox@0xC with SW_RESET_N = 0x00 (status value logged, not "
            f"compared) resp={resp_name(km_r[0])} rdata={_hex_lanes(km_r[1])}"
        )
        km_w = await self._wr(KM_WRITE_LOCAL, 0x5EB0_0007, "s7_km_wr", nbytes=4, size=2)
        efuse = [await self._rd(a, f"s7_efuse_{a:x}", nbytes=4, size=2) for a in EFUSE_LOCALS]
        lc = await self._rd(LC_LOCAL, "s7_lc_rd", nbytes=4, size=2)
        trng_r = await self._rd(EXT_TRNG_LOCAL, "s7_ext_trng_rd")
        trng_w = await self._wr(EXT_TRNG_LOCAL, 0, "s7_ext_trng_wr", nbytes=4, size=2)
        await self._swrst(jtag, SWRST_POR, "s7_swrst_7e")
        self._log(
            f"OBSERVATION S7 never-isolated km_rd={km_r} km_wr={km_w} efuse={efuse} lc={lc} "
            f"ext_trng_rd={trng_r} ext_trng_wr={trng_w}"
        )

        def okay_no_iso(x):
            return (x[0], ISO_WORD in x[1])

        self._verdict(
            "CHK-SEPRST-NEVER-ISO",
            "CHK-SEPRST-NEVER-ISO: SW_RESET_N read back 0x00; km mailbox@0xC rd OKAY, "
            "mailbox@0x0 wr OKAY; efuse 3/3 OKAY; lc OKAY; ext_trng rd DECERR 0xBADCAB1E wr "
            "DECERR",
            (
                s7_sw,
                okay_no_iso(km_r),
                km_w,
                [okay_no_iso(e) for e in efuse],
                okay_no_iso(lc),
                trng_r,
                trng_w,
            ),
            (
                (0, SWRST_ALL_HELD),
                (RESP_OKAY, False),
                RESP_OKAY,
                [(RESP_OKAY, False)] * 3,
                (RESP_OKAY, False),
                (RESP_DECERR, (DECERR_WORD, DECERR_WORD)),
                RESP_DECERR,
            ),
        )
        sram_rw = self.r.get("sram_rw", [])
        self._verdict(
            "CHK-SEPRST-DOMAIN-INDEP",
            f"CHK-SEPRST-DOMAIN-INDEP: otbn->aes OKAY; aes->hmac OKAY; sram rw OKAY "
            f"x{len(sram_rw)}; cpu egress load OKAY data==responder across SW_RESET_N read "
            "back 0x00",
            (
                self.r.get("cross", {}),
                [rw for _, rw in sram_rw],
                (got["held_across"], got["sberr"], s7_sw),
                (stopped, t0),
            ),
            (
                {"otbn->aes": RESP_OKAY, "aes->hmac": RESP_OKAY},
                [(RESP_OKAY, RESP_OKAY, True)] * (len(DOMAINS) + 1),
                (True, 0, (0, SWRST_ALL_HELD)),
                (True, word),
            ),
        )
        self.steps["S7"] = True

    # ---- S8 ------------------------------------------------------------------------------

    async def _early(self, jtag) -> None:
        self._enter("EARLY", "S8", "0 then 1 at gaps of 0 and 8 debug-bus operations")
        completed = 0
        issued = 0
        lines = []
        iso_req = hier(smu_scope(self.dut), ISO_REQ_PATH)
        moved = []
        for dom, bit in EARLY_DOMAINS:
            local = TRNG_PATHS[0][1] if dom == "trng" else DOMAIN_BY_NAME[dom][1]
            zero = SWRST_POR & ~(1 << bit)
            for g in GAPS:
                await self._sb_target(jtag, "w", SWRST_LOCAL)
                reads = [
                    self._start(write=False, local=local, nbytes=8, ident=ident)
                    for ident in EARLY_IDS
                ]
                issued += len(reads)
                busy = []
                iso_mask = EARLY_ISO_MASK[dom]
                iso_base = sample(iso_req, ISO_REQ_PATH) & iso_mask
                iso_seen: list[int] = []

                async def iso_watch(base=iso_base, mask=iso_mask, seen_vals=iso_seen) -> None:
                    while True:
                        await RisingEdge(self.dut.clk_smu_i)
                        value = sample(iso_req, ISO_REQ_PATH) & mask
                        if value != base and value not in seen_vals:
                            seen_vals.append(value)

                iso_task = cocotb.start_soon(iso_watch())
                if g == 0:
                    self._slow_op()
                    self._slow_op()
                    self.sba_writes += 2
                    await self._dmi_chain(
                        jtag,
                        (
                            (SBDATA0_ADDR, zero, DMI_OP_WRITE),
                            (SBDATA0_ADDR, SWRST_POR, DMI_OP_WRITE),
                        ),
                        f"early_{dom}_g0",
                    )
                else:
                    await self._sb_launch(jtag, zero)
                    for _ in range(g):
                        self.spacing_ops += 1
                        busy.append(
                            int(
                                bool(await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ) & SBCS_SBBUSY)
                            )
                        )
                    await self._sb_launch(jtag, SWRST_POR)
                err = await self._sb_status(jtag, await self._sb_poll(jtag, f"early_{dom}_g{g}"))
                iso_task.cancel()
                moved.append(bool(iso_seen))
                self._log(
                    f"OBSERVATION S8 {dom} g={g} isolation request bits of {dom} (mask "
                    f"0x{iso_mask:x}) before the 0 write=0x{iso_base:x} other values in the "
                    f"pair={[hex(v) for v in iso_seen]}"
                )
                if err:
                    raise AssertionError(f"S8 {dom} g={g} system-bus sberror={err}")
                seen = False
                for rec in reads:
                    resp, lanes = await self._done(rec, f"early_{dom}_g{g}_id{rec['id']:x}")
                    seen |= _iso_seen(resp, lanes)
                    completed += int(self._hs_cycle(self.r_hs, rec["id"], rec["issue"]) > 0)
                probe = self._start(write=False, local=local, nbytes=8)
                issued += 1
                probe_resp, probe_lanes = await self._done(probe, f"early_{dom}_g{g}_probe")
                completed += int(self._hs_cycle(self.r_hs, probe["id"], probe["issue"]) > 0)
                seen |= _iso_seen(probe_resp, probe_lanes)
                lines.append((dom, g, probe_resp, seen, busy))
        _, sw = await self._sbr(jtag, SWRST_LOCAL, "early_swrst")
        for dom, g, probe_resp, seen, busy in lines:
            self._log(
                f"OBS-SEPRST-EARLY: dom={dom} g={g} probe_resp={resp_name(probe_resp)} "
                f"iso_seen={int(seen)} swrst=0x{sw:02x} (read once after the six pairs) "
                f"sbbusy_between={busy}"
            )
        self._verdict(
            "CHK-SEPRST-EARLY-RELEASE",
            f"CHK-SEPRST-EARLY-RELEASE: {len(lines)} pairs; the written domain's isolation "
            f"request bits moved in {sum(moved)}/{len(moved)} pairs; all accesses completed; "
            f"SW_RESET_N "
            f"0x{sw & SWRST_FIELD_MASK:02X}",
            (moved, completed, sw & SWRST_FIELD_MASK),
            ([True] * len(EARLY_DOMAINS) * len(GAPS), issued, SWRST_POR),
        )
        self.steps["S8"] = True

    # ---- S9 ------------------------------------------------------------------------------

    async def _jtag_override(self, jtag) -> None:
        self._enter("JTAG", "S9", "IC_RESET sep_reset_n override with traffic outstanding")
        dut = self.dut
        await self._swrst(jtag, SWRST_ALL_RELEASED, "s9_swrst_7f")
        pre_sw = await self._swrst_rd(jtag, "s9_swrst_7f_rd")
        self._log(
            f"OBSERVATION S9 SW_RESET_N before the engage=0x{pre_sw[1]:02x} sberror={pre_sw[0]}"
        )
        word = 0x5EB0_90C9
        load_addr = EGRESS_ADDR + 0x10
        self.mem.write32(load_addr, word)
        await self._reg_write(jtag, REG_A0, load_addr)
        await self._reg_write(jtag, CSR_DPC, STUB_LOAD)
        # SEP SRAM has no reset value: the in-flight and held reads target written words.
        sram = SRAM_LOCAL + 0x500
        sram_word = 0x5EB0_0000_0000_0099
        preload = 0x5EB0_0000_0000_0090
        for off in (0, 8):
            await self._wr(sram + off, preload, f"s9_sram_preload_{off}")
        self._log(
            f"CTRL-SEPRST-S9-PRELOAD: SEP SRAM 0x{sram:08x} and 0x{sram + 8:08x} hold "
            f"0x{preload:016x} before the engage"
        )
        await self._net_ir(jtag, DTP_IR_IC_RESET, "ic_reset")
        mark = self.cyc
        self._hold_responder()
        # Update 1 stages reset_control 0 and carries the resume request for the stub's load.
        await self._ic_reset(
            jtag,
            SEP_STAGED,
            "staged+resume",
            pack_dmi(DMCONTROL, DMACTIVE | RESUMEREQ, op=DMI_OP_WRITE),
        )
        ar_valid = await self._wait_egress_ar(load_addr, mark, "s9_egress_ar")
        self._r_pause(True)
        self._b_pause(True)
        outstanding = {}
        for (tgt, d), ident in S9_OUT_IDS.items():
            local = sram if tgt == "sram" else SWRST_LOCAL
            if d == "w":
                rec = self._start(
                    write=True, local=local, data=sram_word.to_bytes(8, "little"), ident=ident
                )
            else:
                rec = self._start(
                    write=False,
                    local=local,
                    nbytes=8 if tgt == "sram" else 4,
                    size=3 if tgt == "sram" else 2,
                    ident=ident,
                )
            outstanding[(tgt, d)] = rec
        captured = await self._ic_reset(jtag, SEP_HELD, "held")
        _, _, resume_status = unpack_dmi(captured)
        edge = await self._wait_pin(
            "reset_level",
            "sep_reset_n_fall",
            dut.sep_reset_n_o,
            "sep_reset_n_o",
            0,
            RESET_LEVEL_BOUND,
        )
        window: list[int] = []

        async def held_window() -> None:
            while True:
                await RisingEdge(dut.clk_smu_i)
                window.append((self.cyc, sample(dut.sep_reset_n_o, "sep_reset_n_o")))

        sampler = cocotb.start_soon(held_window())
        released = self.cyc
        self._release_responder(ar_valid, "s9_egress")
        self._r_pause(False)
        self._b_pause(False)
        for (tgt, d), rec in outstanding.items():
            done, resp, lanes = await self._observe(
                rec, "OBS-SEPRST-JTAG-INFLIGHT", f"s9_out_{tgt}_{d}"
            )
            end = rec["end"] if done else self.cyc
            self._log(
                f"OBS-SEPRST-JTAG-INFLIGHT: tgt={tgt} dir={d} done={done} "
                f"resp={resp_name(resp) if done else '-'} rdata={_hex_lanes(lanes)} "
                f"before_release={int(end <= released)} cyc_from_edge={end - edge} "
                "(outstanding across the engage)"
            )
        aperture = (
            sample(dut.sep_global_base_o, "sep_global_base_o"),
            sample(dut.sep_region_size_o, "sep_region_size_o"),
        )
        held = {}
        for (tgt, d), ident in S9_HELD_IDS.items():
            local = {"sram": sram + 8, "swrst": SWRST_LOCAL, "lc": LC_LOCAL}[tgt]
            if d == "w":
                rec = self._start(
                    write=True, local=local, data=sram_word.to_bytes(8, "little"), ident=ident
                )
            else:
                rec = self._start(
                    write=False,
                    local=local,
                    nbytes=8 if tgt == "sram" else 4,
                    size=3 if tgt == "sram" else 2,
                    ident=ident,
                )
            held[(tgt, d)] = rec
        for (tgt, d), rec in held.items():
            done, resp, lanes = await self._observe(
                rec, "OBS-SEPRST-JTAG-INFLIGHT", f"s9_held_{tgt}_{d}"
            )
            end = rec["end"] if done else self.cyc
            self._log(
                f"OBS-SEPRST-JTAG-INFLIGHT: tgt={tgt} dir={d} done={done} "
                f"resp={resp_name(resp) if done else '-'} rdata={_hex_lanes(lanes)} "
                f"before_release=1 cyc_from_edge={end - edge} (issued while held)"
            )
        orphan_beats = len([c for c in self.out_r_hs if c > mark])
        self._log(
            f"OBSERVATION S9 while held: sep_global_base_o=0x{aperture[0]:x} "
            f"sep_region_size_o=0x{aperture[1]:x}; resume request status={resume_status}; "
            f"release order TDR bit {SEP_ENABLE_BIT} (reset_enable) then bit {SEP_CONTROL_BIT} "
            "(reset_control)"
        )
        boot: dict = {}

        async def restart() -> None:
            boot["rise"] = await self._wait_pin(
                "reset_level",
                "sep_reset_n_rise",
                dut.sep_reset_n_o,
                "sep_reset_n_o",
                1,
                RESET_LEVEL_BOUND,
            )
            sampler.cancel()
            boot["pc"] = await self._first_retire("s9_first_retire")

        watcher = cocotb.start_soon(restart())
        await self._ic_reset(jtag, SEP_STAGED, "release_enable")
        release_return = self.last_update
        # The return stamp lags the release scan's Update-DR by up to one TCK, so the held
        # window ends two TCKs (plus one clk_smu cycle) before it and covers the whole shift.
        margin = math.ceil(2 * self.cfg.jtag_period_ns / self.period) + 1
        window_end = release_return - margin
        await self._ic_reset(jtag, ALL_ONES, "release_control")
        await watcher
        pc = boot["pc"]
        held_levels = [v for c, v in window if c < window_end]
        first_one = next((c for c, v in window if v), -1)
        rise_at = boot["rise"]
        await self._net_ir(jtag, DTP_IR_TAP_3DCR, "dmi_after_ic_reset")
        self.sb_mode = None
        self.sb_addr = None
        await self._first_sba(jtag, "s9")
        await self._program_window_and_filter(jtag)
        sw_err, sw = await self._sbr(jtag, SWRST_LOCAL, "s9_swrst_rd", strict=False)
        egress_word = 0x5EB0_9E5A
        werr = await self._sbw(jtag, EGRESS_ADDR + 0x40, egress_word, "s9_egress_wr", strict=False)
        rerr, rb = await self._sbr(jtag, EGRESS_ADDR + 0x40, "s9_egress_rd", strict=False)
        held_word = self.mem.read_int(EGRESS_ADDR + 0x40, 4)
        s9_at_edge = int(not any(mark < c <= edge for c in self.out_r_hs))
        self._log(
            f"OBS-SEPRST-CPU-ORPHAN: src=jtag outstanding_at_edge={s9_at_edge} "
            f"resp_absorbed={int(orphan_beats > 0)} responder_beats={orphan_beats} "
            f"wedged={int(bool(werr or rerr))} pending_nmi=none"
        )
        self._log(
            f"OBSERVATION S9 held window samples={len(held_levels)} ones={sum(held_levels)} "
            f"release scan return@{release_return} margin={margin} window_end@{window_end} "
            f"rise_at@{rise_at} first 1 sample@{first_one} pc=0x{pc:08x} "
            f"SW_RESET_N=0x{sw:x} sberror={sw_err} egress w/r sberror={werr}/{rerr} "
            f"readback=0x{rb:08x} responder=0x{held_word:08x}"
        )
        self._verdict(
            "CHK-SEPRST-JTAG-INFLIGHT",
            f"CHK-SEPRST-JTAG-INFLIGHT: held window ok; aperture while held "
            f"base=0x{aperture[0]:x} size=0x{aperture[1]:x}; cpu restart pc=0x{pc:08x}; "
            f"SW_RESET_N 0x{pre_sw[1]:02X}->0x{sw & SWRST_FIELD_MASK:02X}; egress rw ok",
            (
                len(held_levels) > 0 and sum(held_levels) == 0 and rise_at >= window_end,
                aperture,
                BOOT_ROM_LOCAL <= pc < BOOT_ROM_END,
                pre_sw,
                (sw_err, sw & SWRST_FIELD_MASK),
                (werr, rerr, rb, held_word),
            ),
            (
                True,
                APERTURE_RESET,
                True,
                (0, SWRST_ALL_RELEASED),
                (0, SWRST_POR),
                (0, 0, egress_word, egress_word),
            ),
        )
        self.steps["S9"] = True

    # ---- S10 -----------------------------------------------------------------------------

    async def _bite(self, jtag) -> None:
        self._enter("BITE", "S10", "bus-fault status, watchdog bite with traffic outstanding")
        dut = self.dut
        req = hier(smu_scope(dut), "sep_wdt_timer_rst_req")
        wdt_rst = hier(smu_scope(dut), "rst_wdt_n")
        await self._halt(jtag, "s10")
        await self._install_stub(jtag)
        for name, value in (
            ("ENABLED_MEMORY_RANGE_LIMIT", DMA_RANGE_ALL),
            ("RANGE_VALID", 1),
            ("SRC_ADDR_LO", DMA_RESERVED_SRC),
            ("DST_ADDR_LO", DMA_DST),
            ("TOTAL_DATA_SIZE", DMA_WORD),
            ("CHUNK_DATA_SIZE", DMA_WORD),
            ("CONTROL", DMA_GO),
        ):
            await self._sbw(jtag, DMA_REGS[name], value, f"s10_dma_{name.lower()}")
        await self._reg_write(jtag, REG_A0, DOMAIN_BY_NAME["aes"][1])
        await self._reg_write(jtag, REG_A1, STORE_BYTE)
        await self._reg_write(jtag, CSR_DPC, STUB_STORE)
        self._slow_op()
        await self._dmi(jtag, DMCONTROL, DMACTIVE | RESUMEREQ, DMI_OP_WRITE)
        store_stopped = await self._stopped(jtag, "s10_store")
        await self._reg_write(jtag, CSR_DPC, STUB_LOAD_DONE)
        self._slow_op()
        await self._dmi(jtag, DMCONTROL, DMACTIVE | RESUMEREQ, DMI_OP_WRITE)
        drained = await self._stopped(jtag, "s10_nmi_drain")
        nmi_dpc = await self._reg_read(jtag, CSR_DPC)
        if nmi_dpc == NMI_VECTOR:
            pending_nmi = "cleared"
        elif nmi_dpc == STUB_LOAD_DONE:
            pending_nmi = "none"
        else:
            pending_nmi = f"unknown(dpc=0x{nmi_dpc:08x})"
        self._log(
            f"OBSERVATION S10 resume at the ebreak after the store: ebreak={int(drained)} "
            f"dpc=0x{nmi_dpc:08x} (0x{NMI_VECTOR:08x} is the NMI handler, so a pending NMI was "
            f"taken; 0x{STUB_LOAD_DONE:08x} means none was pending)"
        )
        _, dma_pre = await self._sbr(jtag, DMA_ERR_STATUS, "s10_dma_err_pre")
        _, periph_pre = await self._sbr(jtag, PERIPH_ERR_STATUS, "s10_periph_err_pre")
        self._log(
            f"OBSERVATION S10 byte store ebreak={int(store_stopped)}; "
            f"DMA_BUS_ERR_STATUS=0x{dma_pre:x} PERIPH_BUS_ERR_STATUS=0x{periph_pre:x} "
            f"(aes={int(bool(periph_pre & PERIPH_AES_BM))}) before the bite"
        )
        ws_word = 0x5EB0_0000_0000_00A1
        sram = SRAM_LOCAL + 0x600
        sram_word = 0x5EB0_0000_0000_00A2
        await self._wr(WSCRATCH_LOCAL, ws_word, "s10_wscratch_wr")
        await self._wr(sram, sram_word, "s10_sram_wr")
        await self._sbw(jtag, WDOG["BITE_THOLD"], WDOG_BITE_TICKS, "s10_bite_thold")
        await self._sbw(jtag, WDOG["COUNT"], 0, "s10_wdog_count")
        bite: dict = {}

        async def watch() -> None:
            bite["mark"] = self.cyc
            # RREADY stays low from here to the fall, so the SRAM read is answered only after
            # the watchdog reset.
            self._r_pause(True)
            bite["outstanding"] = {
                "sram": self._start(write=False, local=sram, nbytes=8, ident=S10_IDS["sram"]),
            }
            bite["rise"] = await self._wait_pin(
                "bite_req", "rise", req, "sep_wdt_timer_rst_req", 1, BITE_RISE_BOUND
            )
            bite["sba_at_rise"] = self.sba_writes
            reset_edge = cocotb.start_soon(
                self._wait_pin(
                    "reset_level", "s10_wdt_rst", wdt_rst, "rst_wdt_n", 0, BITE_FALL_BOUND
                )
            )
            bite["outstanding"]["wscratch"] = self._start(
                write=False, local=WSCRATCH_LOCAL, nbytes=8, ident=S10_IDS["wscratch"]
            )
            await ClockCycles(dut.clk_smu_i, BITE_DURING_GAP)
            bite["during_req"] = sample(req, "sep_wdt_timer_rst_req")
            bite["during"] = self._start(
                write=False, local=WSCRATCH_LOCAL, nbytes=8, ident=S10_IDS["during"]
            )
            bite["fall"] = await self._wait_pin(
                "bite_req", "fall", req, "sep_wdt_timer_rst_req", 0, BITE_FALL_BOUND
            )
            bite["sba_at_fall"] = self.sba_writes
            bite["reset"] = await reset_edge
            self._r_pause(False)
            bite["pc"] = await self._first_retire("s10_first_retire")

        load_addr = EGRESS_ADDR + 0x20
        word = 0x5EB0_A0CA
        tasks = []
        got = await self._cpu_load_across(
            jtag,
            load_addr,
            word,
            WDOG["CTRL"],
            WDOG_ENABLE,
            "s10",
            on_launch=lambda: tasks.append(cocotb.start_soon(watch())),
        )
        await tasks[0]
        self.soft = True
        self._slow_op()
        dmstatus = await self._dmi(jtag, DMSTATUS, 0, DMI_OP_READ)
        self._log(f"OBSERVATION S10 dmstatus after the bite=0x{dmstatus:08x}")
        await self._first_sba(jtag, "s10")
        sram_at = await self._done(bite["outstanding"]["sram"], "s10_bite_sram")
        wsx = "OBS-SEPRST-WSCRATCH"
        ws = {
            "outstanding": await self._observe(bite["outstanding"]["wscratch"], wsx, "s10_ws_out"),
            "during": await self._observe(bite["during"], wsx, "s10_ws_during"),
            "after": await self._observe(
                self._start(write=False, local=WSCRATCH_LOCAL, nbytes=8, ident=S10_IDS["after"]),
                wsx,
                "s10_ws_after",
            ),
        }
        for when, (done, resp, lanes) in ws.items():
            self._log(
                f"OBS-SEPRST-WSCRATCH: when={when} done={done} "
                f"resp={resp_name(resp) if done else '-'} rdata={_hex_lanes(lanes)} "
                f"bound={EXT_IN_BOUND} expired={int(not done)}"
            )
        orphan = {}

        async def orphan_leg(leg: str, addr: int, *, write: bool = False, data: int = 0) -> None:
            got_leg = await self._sb_window(
                jtag, "OBS-SEPRST-BITE-ORPHAN", f"s10_{leg}", addr, write=write, data=data
            )
            orphan[leg] = got_leg
            done, err, value, sbcs, used = got_leg
            self._log(
                f"OBS-SEPRST-BITE-ORPHAN: leg={leg} done={done} sbcs=0x{sbcs:08x} "
                f"value={'-' if value is None else f'0x{value:08x}'} bound={SBA_POLLS} "
                f"used={used} ruling=#3341 expired={int(not done)} sberror={err}"
            )

        await orphan_leg("status_dma", DMA_ERR_STATUS)
        await orphan_leg("status_periph", PERIPH_ERR_STATUS)
        wdog = {}
        for name, addr in WDOG.items():
            _, _, value, _, _ = await self._sb_window(
                jtag, "OBS-SEPRST-WDOG-POST", f"s10_wdog_{name.lower()}", addr
            )
            wdog[name] = "-" if value is None else f"0x{value:x}"
        self._log(
            f"OBS-SEPRST-WDOG-POST: ctrl={wdog['CTRL']} bite_thold={wdog['BITE_THOLD']} "
            f"count={wdog['COUNT']} regwen={wdog['REGWEN']}"
        )
        fresh_word = 0x5EB0_0000_0000_00A3
        fw = await self._wr(sram + 8, fresh_word, "s10_fresh_sram_wr")
        fr, flanes = await self._rd(sram + 8, "s10_fresh_sram_rd")
        egress_word = 0x5EB0_AE5B
        await orphan_leg("egress_wr", EGRESS_ADDR + 0x80, write=True, data=egress_word)
        await orphan_leg("egress_rd", EGRESS_ADDR + 0x80)
        held_word = self.mem.read_int(EGRESS_ADDR + 0x80, 4)
        werr, rerr = orphan["egress_wr"][1], orphan["egress_rd"][1]
        orphan_beats = len([c for c in self.out_r_hs if c > got["mark"]])
        s10_at_edge = int(not any(got["mark"] < c <= bite["rise"] for c in self.out_r_hs))
        self._log(
            f"OBS-SEPRST-CPU-ORPHAN: src=bite outstanding_at_edge={s10_at_edge} "
            f"resp_absorbed={int(orphan_beats > 0)} responder_beats={orphan_beats} "
            f"wedged={int(bool(werr or rerr))} pending_nmi={pending_nmi}"
        )
        self._log(
            f"OBSERVATION S10 enable sberror={got['sberr']} load held_across_enable="
            f"{got['held_across']} rise@{bite['rise']} fall@{bite['fall']} "
            f"req during={bite['during_req']} pc=0x{bite['pc']:08x} DMA before=0x{dma_pre:x} "
            f"PERIPH before=0x{periph_pre:x} sram-at-bite="
            f"({resp_name(sram_at[0])}, {_hex_lanes(sram_at[1])}) fresh=({resp_name(fw)}, "
            f"{resp_name(fr)}) egress responder=0x{held_word:08x} written=0x{egress_word:08x}"
        )
        sram_id = S10_IDS["sram"]
        sram_ar = self._hs_cycle(self.ar_hs, sram_id, bite["mark"])
        sram_r = self._hs_cycle(self.r_hs, sram_id, sram_ar) if sram_ar > 0 else -1
        sram_held = 0 < sram_ar < bite["reset"] < sram_r
        self._log(
            f"CTRL-SEPRST-BITE-SRAM-OUTSTANDING: arid=0x{sram_id:x} ar_hs@{sram_ar} "
            f"rst_wdt_n_low@{bite['reset']} r_hs@{sram_r} (req rise@{bite['rise']} "
            f"fall@{bite['fall']}) ar_before_reset={int(0 < sram_ar < bite['reset'])} (the DUT's "
            f"AR accept) r_after_reset={int(sram_r > bite['reset'])} (set by the bench: RREADY "
            f"held until after the reset edge)"
        )
        sram_lanes = _lanes(sram_word.to_bytes(8, "little"), 8)
        fresh_lanes = _lanes(fresh_word.to_bytes(8, "little"), 8)
        self.soft = False
        self._verdict(
            "CHK-SEPRST-BITE-INFLIGHT",
            "CHK-SEPRST-BITE-INFLIGHT: req self-cleared; cpu restart; sram read accepted (AR) "
            "before rst_wdt_n low and OKAY with the written word on the R the bench held until "
            "after it; fresh sram rw OKAY; status/egress OBS (doc/trm/src/reset.adoc)",
            (
                bite["sba_at_rise"] == bite["sba_at_fall"],
                BOOT_ROM_LOCAL <= bite["pc"] < BOOT_ROM_END,
                (sram_held, sram_at[0], sram_at[1] == sram_lanes),
                (fw, fr, flanes == fresh_lanes),
            ),
            (
                True,
                True,
                (True, RESP_OKAY, True),
                (RESP_OKAY, RESP_OKAY, True),
            ),
        )
        self.steps["S10"] = True

    # ---- S11 and the fence ---------------------------------------------------------------

    async def _finish(self) -> None:
        self.step = "S11"
        for rec in self.sites:
            self._log(
                f"TIMEOUT-PATH {rec['step']} {rec['kind']} {rec['label']}: bound={rec['bound']} "
                f"used={rec['used']} {'EXPIRED' if rec['expired'] else 'ok'} last={rec['last']}"
            )
        for win in self.windows:
            self._log(
                f"OBS-WINDOW: obs={win['obs']} step={win['step']} label={win['label']} "
                f"bound={win['bound']} used={win['used']} done={win['done']} "
                f"expired={win['expired']} last={win['last']}"
            )
        kinds = Counter(rec["kind"] for rec in self.sites)
        expired = sum(rec["expired"] for rec in self.sites)
        plan = _site_plan()
        observed = {
            step: Counter(r["kind"] for r in self.sites if r["step"] == step and r["kind"] != "dmi")
            for step in plan
        }
        mismatched = {
            step: (dict(observed[step]), dict(plan[step]))
            for step in plan
            if observed[step] != plan[step]
        }
        windows = Counter(win["obs"] for win in self.windows)
        windows_expired = sum(win["expired"] for win in self.windows)
        self._log(
            f"OBSERVATION S11 wait sites per kind={dict(kinds)} dmi_ops={self.dmi_ops} "
            f"fallback halts={dict(self.fallbacks)} per-step mismatches={mismatched} "
            f"observation windows={dict(windows)} expired={windows_expired}"
        )
        self._log(
            f"OBSERVATION slow operations per step={dict(self.slow)} "
            f"total={sum(self.slow.values())} "
            f"spacing DMI reads (S8 g=8)={self.spacing_ops}"
        )
        self._verdict(
            "CHK-TIMEOUT-PATHS",
            f"CHK-TIMEOUT-PATHS: {len(self.sites)} waits in {len(kinds)} kinds, none expired "
            f"(bound, used, last state per site); {len(self.windows)} observation windows listed "
            f"(expired=<0|1> each; {windows_expired} expired=1)",
            (expired, mismatched, dict(windows)),
            (0, {}, dict(WINDOW_PLAN)),
        )
        await ClockCycles(self.dut.clk_smu_i, FENCE_GAP)
        stamps = [(t, self.terms.get(t, [None, 0])) for t in FENCE]
        pass_ns = self._now()
        fence = " < ".join(
            f"{t}@{v[0]:.1f}ns(n={v[1]})" if v[0] is not None else f"{t}@missing" for t, v in stamps
        )
        self._log(
            f"OBSERVATION CHK-NONVAC fence {fence} < PASS@{pass_ns:.1f}ns "
            f"drain_cells={self.r.get('drain_cells')}"
        )
        times = [v[0] for _, v in stamps]
        ordered = all(t is not None for t in times) and all(
            b > a for a, b in zip(times, times[1:] + [pass_ns])
        )
        counts = [v[1] for _, v in stamps]
        self._verdict(
            "CHK-NONVAC",
            "CHK-NONVAC: SETUP < DRAIN < ISOLATED < RELEASE < TRNG < KM < ALL_DOMAINS < EARLY < "
            "JTAG < BITE < PASS (sim time and count per term)",
            (
                ordered,
                all(n > 0 for n in counts),
                self.r.get("drain_cells"),
                all(self.steps.get(f"S{i}", False) for i in range(1, 11)),
            ),
            (True, True, len(CELLS) * len(DOMAINS), True),
        )
        if self.unverified:
            self._log(f"OBSERVATION unverified legs: {self.unverified}")
        if self.failures:
            raise AssertionError(f"{len(self.failures)} checker compare(s) failed: {self.failures}")
        self.done = True

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        assert self.s1_ok and self.s2_ok and self.s3_ok, "SEP debug bring-up incomplete"
        jtag = self.jtag
        tap = cocotb.start_soon(self._tap())
        try:
            await self._s1_setup(jtag)
            await self._domains(jtag)
            await self._trng(jtag)
            await self._km(jtag)
            await self._all_domains(jtag)
            await self._early(jtag)
            await self._jtag_override(jtag)
            await self._bite(jtag)
            await self._finish()
        finally:
            tap.cancel()
