# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMU_SEP_SCN_012 ANCHOR: smu_smc_reset_inflight_test
# DV-TESTCASE-CONTRACT-REVISION: 8 RECORD-SHA256: da58600cd645a978704a315eb895c0e44227293a161e2eceaf7590757fa8023b
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_SEP_SCN_VPLAN_DETAIL_RESET.md @ artifact_revision 10 ENV: cocotb
"""SMC-side resets with crossbar traffic in flight, on the SEP=1 wrapper.

Bring-up is ``smu_dtp_sep_dm_dmi_test`` (TEST_DEV posture, SEP STAP, dmactive). With the SEP STAP
selected every PTAP scan is composed over the STAP network (``smu_dtp_sep_ic_reset_effect_test``),
so the SMC_AXI_SINGLE_OP (JTAG2AXI) scans carry a DMI NOP in the SEP segment.

Expected values come from ``hw/sys/smc/doc/clk_rst.adoc`` (the reset equations; the CPU control
registers, ``SS_CONFIG`` and ``SS_COLD_RESET_N`` on the primary reset and kept across warm; the
isolation registers and FLR counters on the stable cold reset; a core reset does not clear its
watchdog, the uncore reset does) and the register reset values of ``cpu_ctrl.adoc``,
``reset_unit.adoc``, ``wdt.adoc`` and ``smc_base_config.adoc`` through the generated C headers.

The SMU boundary links are reset by the SMC primary reset (the bench's AXI protocol checkers
take it as aresetn), so the bench master on ``ext_in`` takes that reset too: at a cool or FLR
fall it drops VALID and flushes what it holds (AMBA AXI A3.1.2), and nothing is issued on
``ext_in`` while the reset is held. The bench responder on ``ext_out`` is on the stable cold
reset, so an AR it held across the primary reset would be answered into a link in reset; the
JTAG2AXI reads of the cool trials therefore complete before the pin is driven. The crossbar, the
DTP and the SEP system logic are on the SMC primary reset, so after every cool and FLR reset the
leaf returns the TAP to Test-Logic-Reset, selects the SEP STAP again, sets dmactive, programs the
SEP aperture and egress filter and reopens SMC inbound filter entry 0 and outbound filter entry 0
over JTAG2AXI before any ext_in access into the SMC.

S1  SETUP: SEP aperture and egress filter, SMC inbound/outbound filter entry 0 over JTAG2AXI.
S2  IMAGES: CPU control, reset-unit and base-configuration images over ext_in; base 0x6000_0000.
S3  WARM: CORE0 second timeout and SEP bite with ext_in SS_CONFIG reads held across the fall;
    the system-bus read completes as close before the fall as the debug bus allows. The bite's
    warm fall is an observation window (OBS-SMCRST-BITE-NO-WARM): without a fall inside it the
    bite-source cells are recorded and only the watchdog-source cells are compared.
S4  WARM_POST: SCRATCH[0] over ext_in, JTAG2AXI reads of the egress page and of SEP SRAM.
S5  COOL: two pin trials with an ext_in read held across the fall; system-bus accesses only
    during the hold, and the inbound link's AWVALID / ARVALID counted while it is in reset.
    Before trial 1 the S2 images are read again, so the pre-image of the cool reset is the
    state after both warm resets; before trial 2 SS_CONFIG and RESET_VECTOR[0] are written to
    their patterns and read back (CTRL-SMCRST-REWRITE). A trial without a SEP debug path issues
    no system-bus access and its during-hold term reads not run.
S6  COOL_POST: re-attach, then the reset-value reads at 0x4000_0000.
S7  FLR: the S5 rewrite and read-back, then an FLR-timed cool reset with an ext_in read held
    across the fall; the latched isolation
    leg, with ISOLATE_REQ_SMC_REG read by 8-byte framed JTAG2AXI accesses (1 at issue, 0 after
    the clear; OBS-SMCRST-ISO-LATCH is the measured record).
S8  SW_CORE: per-core hold/release against the per-core watchdog count; core reset pulses,
    with core_resets_done[0] counted low at the tap every clk_smc (CTRL-SMCRST-PULSE-LOW).
S9  SW_UNCORE, every access over ext_in: the idle uncore reset, then one held trial (mode 0,
    timeout 0x100): the uncore request goes on the write channels while a train of 24 reads is
    held by RREADY low, with the smc_in R handshakes counted every clk_smu_i and logged at the
    request and before the release (CTRL-SMCRST-UNDRAINED); no read is issued while held. After
    RREADY is released the train's answers are OBS-SMCRST-UNCORE-TRAIN windows; then every
    wait is graded: reset_applied must read 1, and the release write must read back with
    reset_applied 0; an expiry fails the checker and the leaf goes on to S10.
S10 TIMEOUT: every proof-path wait is bounded and logged with its bound, the cycles used and its
    last state, the wait sites per step and kind match the literal plan of the step list, and
    every observation window is listed by OBS name with its bound, cycles used and expired flag.

JTAG2AXI accesses are AXSIZE 8 at 8-byte aligned addresses; ISOLATE_REQ_SMC_REG shares its
8-byte beat with ISOLATE_REQ_SMCEN_REG, so its clearing write strobes byte 0 only. After a
failed SEP re-attach the PTAP's STAP select holds through Test-Logic-Reset and the SIB flops
stay TDO-side of the PTAP; an IDCODE probe (CTRL-SMCRST-CHAIN) sets the pad every later PTAP
scan carries.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_reset_inflight_test --target compile_smu_chiplet
"""

from __future__ import annotations

import contextlib
from collections import Counter
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_OKAY, resp_name, worst_resp
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    c_header_u32,
    reset_unit_u32,
    smc_addr,
    smc_indexed_addr,
    wdt_u32,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_axi_in_sep_aperture_test_seq import (
    SMC_LOCAL_BASE,
    SRAM_LOCAL,
    WIN_BASE,
    WIN_SIZE,
    smu_axi_in_sep_aperture_test_seq,
)
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMCONTROL_ADDR,
    DMCONTROL_DMACTIVE,
    DMI_DR_WIDTH,
    DMI_OP_NOP,
    DMI_OP_READ,
    DMI_OP_WRITE,
    DMI_STATUS_OK,
    DMSTATUS_ADDR,
    DMSTATUS_VERSION_SPEC_0_13,
    IDCODE_DR_WIDTH,
    SEP_TAP_IR_DMI,
    SIBS_BEFORE_SEP,
    SIBS_FROM_SEP,
    network_ir_scan,
    network_scan,
    pack_dmi,
    ptap_dr_from_capture,
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
from seq_lib.smu_filter_helpers import PASS_ALL_END, PASS_RW_CONFIG
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SINGLE_OP,
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SINGLE_OP_LEN,
    WDT_KEY_MAGIC,
    dtp_ir_opcode,
    pack_single_op,
    require_jtag_tdo_resolved,
    unpack_single_op,
)
from seq_lib.smu_tb_pins import smc_primary_reset, smu_scope

_REPO = Path(__file__).resolve().parents[6]
_CPU_CTRL_H = _REPO / "hw/sys/smc/regs/gen/c/blocks/cpu_ctrl.h"
_SEP_ADDR_H = _REPO / "hw/sys/sep/regs/gen/c/sep_addr.h"
_AON_H = _REPO / "vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/gen/c/aon_timer.h"


def _cpu(symbol: str) -> int:
    return c_header_u32(_CPU_CTRL_H, symbol)


def _fields(prefix: str, names: tuple[str, ...], suffix: str) -> int:
    return sum(_cpu(f"{prefix}__{n}_{suffix}") for n in names)


def _reset_of(prefix: str, names: tuple[str, ...]) -> int:
    return sum(_cpu(f"{prefix}__{n}_reset") << _cpu(f"{prefix}__{n}_bp") for n in names)


# ---- SMC registers (local addresses; ext_in uses GLOBAL_BASE + offset) --------------------
SS_CONFIG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")
SS_COLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR")
ISO_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
ISO_SMC = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
ISO_SMCEN = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR")
FLR_COUNTER = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
RV = tuple(smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", i) for i in range(4))
RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
PULSE = smc_addr("SMC_TOP_SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
WDT_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR")
SCRATCH = tuple(smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", i) for i in range(4))
GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
WDT = {
    core: {
        reg: smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_{reg}_BASE_ADDR")
        for reg in ("CTRL", "COUNT", "KEY", "CMP")
    }
    for core in range(4)
}

# ---- reset values and field masks (RDL through the generated headers) ---------------------
_RC = "CPU_CTRL__RESET_CTRL"
_RC_FIELDS = tuple(f"CORE{i}_RESET_N_N0_SCAN" for i in range(4)) + tuple(
    f"CORE{i}_RESET_PULSE_START_N0_SCAN" for i in range(4)
)
_RC_FIELDS += ("UNCORE_RESET_N_N0_SCAN", "DEBUG_RESET_N_N0_SCAN")
RC_MASK = _fields(_RC, _RC_FIELDS, "bm")
RC_RESET = _reset_of(_RC, _RC_FIELDS)
CORE_BM = tuple(_cpu(f"{_RC}__CORE{i}_RESET_N_N0_SCAN_bm") for i in range(4))
PULSE0_BM = _cpu(f"{_RC}__CORE0_RESET_PULSE_START_N0_SCAN_bm")
UNCORE_BM = _cpu(f"{_RC}__UNCORE_RESET_N_N0_SCAN_bm")
RV_MASK = _cpu("CPU_CTRL__RESET_VECTOR__VECTOR_bm")
RV_RESET = _cpu("CPU_CTRL__RESET_VECTOR__VECTOR_reset")
WDT_TIMEOUT_MASK = _cpu("CPU_CTRL__WDT_TIMEOUT__DATA_bm")
WDT_TIMEOUT_RESET = _cpu("CPU_CTRL__WDT_TIMEOUT__DATA_reset")
_RT = "CPU_CTRL__RESET_TIMEOUT"
_RT_FIELDS = ("TIMEOUT_VALUE", "TIMEOUT_MODE", "RESET_APPLIED", "RESET_TIMEOUT")
RT_MASK = _fields(_RT, _RT_FIELDS, "bm")
RT_RESET = _reset_of(_RT, _RT_FIELDS)
RT_MODE_BP = _cpu(f"{_RT}__TIMEOUT_MODE_bp")
# The software-written fields; RESET_APPLIED and RESET_TIMEOUT are status.
RT_CFG_MASK = _fields(_RT, ("TIMEOUT_VALUE", "TIMEOUT_MODE"), "bm")
RT_APPLIED_BP = _cpu(f"{_RT}__RESET_APPLIED_bp")
RT_TIMEOUT_BP = _cpu(f"{_RT}__RESET_TIMEOUT_bp")
_PC = "CPU_CTRL__CORE_RESET_PULSE_COUNT"
DONE_BP = _cpu(f"{_PC}__CORE_RESETS_DONE_bp")
DONE_MASK = _cpu(f"{_PC}__CORE_RESETS_DONE_bm") >> DONE_BP
DONE_RESET = _cpu(f"{_PC}__CORE_RESETS_DONE_reset")
PRE_BP = _cpu(f"{_PC}__PRE_RESET_COUNT_bp")
POST_BP = _cpu(f"{_PC}__POST_RESET_COUNT_bp")
GB_MASK = smc_base_config_u32("SMC_BASE_CONFIG__GLOBAL_BASE__BASE_bm")
GB_RESET = smc_base_config_u32("SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset")
RS_MASK = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_bm")
RS_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")
SS_MASK = reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_bm")
SS_RESET = reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_reset")
SS_COLD_MASK = reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_bm")
SS_COLD_RESET = reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_reset")
ISO_MASK = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_REG__ISOLATE_REQ_REG_bm")
ISO_SMC_BM = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")
ISO_SMC_BP = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bp")
# ISOLATE_REQ_SMCEN_REG follows ISOLATE_REQ_SMC_REG inside the same 8-byte beat, so the clearing
# write strobes only the byte that holds the field.
ISO_SMC_REG_MASK = (1 << (8 * (ISO_SMCEN - ISO_SMC))) - 1
ISO_SMC_CLEAR_WSTRB = 1 << (ISO_SMC % 8 + ISO_SMC_BP // 8)
WDT_COREAWAKE = wdt_u32("WDT__CTRL__WDOGCOREAWAKE_bm")
WDT_RSTEN = wdt_u32("WDT__CTRL__WDOGRSTEN_bm")
WDT_ALWAYS = wdt_u32("WDT__CTRL__WDOGENALWAYS_bm")
WDT_ZEROCMP = wdt_u32("WDT__CTRL__WDOGZEROCMP_bm")
WDT_COUNT_MASK = wdt_u32("WDT__COUNT__WDOGCOUNT_bm")
WDT_CMP_MASK = wdt_u32("WDT__CMP__WDOGCMP0_bm")
WDT_CMP_RESET = wdt_u32("WDT__CMP__WDOGCMP0_reset")
_WDT_CTRL_FIELDS = (
    "WDOGSCALE",
    "WDOGRSTEN",
    "WDOGZEROCMP",
    "WDOGENALWAYS",
    "WDOGCOREAWAKE",
    "WDOGIP0",
)
WDT_CTRL_MASK = sum(wdt_u32(f"WDT__CTRL__{f}_bm") for f in _WDT_CTRL_FIELDS)
# The configuration bits; WDOGIP0 is status that sets once the count passes CMP.
WDT_CFG_MASK = WDT_CTRL_MASK & ~wdt_u32("WDT__CTRL__WDOGIP0_bm")
WDT_CTRL_RESET = sum(
    wdt_u32(f"WDT__CTRL__{f}_reset") << wdt_u32(f"WDT__CTRL__{f}_bp") for f in _WDT_CTRL_FIELDS
)

# ---- contract images (S2) ----------------------------------------------------------------
SS_CONFIG_PAT = 0x5A5A_5A5A
SS_COLD_PAT = 0xA5A5_A5A5
# Vectors away from the 0xC0040000 reset value, each distinct.
RV_PAT = tuple(0x0000_3000 + 0x100 * i for i in range(4))
WDT_TIMEOUT_PAT = 0x2000
RT_PAT = 0x0001_0100
RC_PAT = 0x0100_010D
ISO_PAT = 0xA5A5_A5A5
RS_PAT = 0x0200_0000
GB_PAT = 0x6000_0000
WDT_CMP_ARMED = 0x10
WDT_CMP_KEPT = 0x0800
SCRATCH_WORD = 0x5C5C_0012
FLR_COUNTER_PAT = 16
FLR_HOLD_PAT = 512
PULSE_PRE = 0x0100
PULSE_POST = 0x0400
RT_MODE0 = 0x0000_0100
RT_MODE1 = (1 << RT_MODE_BP) | 0x0100
RT_TIMEOUT0 = 0x0

# ---- SEP side ----------------------------------------------------------------------------
WDOG_CTRL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR")
WDOG_BITE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR")
WDOG_COUNT = c_header_u32(_SEP_ADDR_H, "SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR")
WDOG_ENABLE = c_header_u32(_AON_H, "AON_TIMER__WDOG_CTRL__ENABLE_bm")
WDOG_BITE_TICKS = 0x20
SRAM_GLOBAL = WIN_BASE + SRAM_LOCAL
EGRESS_WORDS = {
    "warm_post": (EGRESS_ADDR + 0x100, 0x5EB0_0C12_0000_0A01),
    "trial1": (EGRESS_ADDR + 0x200, 0x5EB0_0C12_0000_0B01),
    "iso": (EGRESS_ADDR + 0x300, 0x5EB0_0C12_0000_0C01),
}
SRAM_WORDS = {
    "warm_post": (SRAM_GLOBAL + 0x2000, 0x5EB0_5A12_0000_0A02),
    "trial2": (SRAM_GLOBAL + 0x2008, 0x5EB0_5A12_0000_0B02),
}

# ---- bounds, in clk_smu_i cycles unless named otherwise ------------------------------------
EXT_IN_BOUND = 4000
HS_BOUND = 400
WARM_FALL_BOUND = 200_000
RESET_LEVEL_BOUND = 20_000
J2A_POLLS = 16
REG_POLLS = 32
# A programmed pulse of 0x0100 + 0x0400 clk_smc against an ext_in read of about 25 clk_smu.
PULSE_POLLS = 128
COUNT_GAP_SMC = 512
TRAIN = 24
SMC_IN_SVA = "u_xbar_smc_in_axi_sva"
TLR_TCKS = 5
# The STAP network's SIB flops: with the PTAP's STAP select held and the SEP TAP not spliced
# they sit TDO-side of every PTAP register.
SIB_PAD = SIBS_BEFORE_SEP + SIBS_FROM_SEP
J2A_FULL_WSTRB = 0xFF
FENCE = (
    "SETUP",
    "IMAGES",
    "WARM",
    "WARM_POST",
    "COOL",
    "COOL_POST",
    "FLR",
    "SW_CORE",
    "SW_UNCORE",
)
FENCE_GAP = 2
MISC_ID = 0x05
FIRST_UID = 0x80
NO_SEP_PATH = "not run: no SEP debug path at the trial"
WARM_RESET_PATH = "u_smc.rst_warm_smc_clk_n"
# The per-core pulse-done vector that CORE_RESET_PULSE_COUNT.core_resets_done reads.
PULSE_DONE_PATH = "u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.core_reset_pulse_done"
PULSE_DEFAULT_LOW = (
    _cpu(f"{_PC}__PRE_RESET_COUNT_reset") + 1 + _cpu(f"{_PC}__POST_RESET_COUNT_reset") + 1
)

NOP_REQUEST = pack_dmi(0, 0, op=DMI_OP_NOP)


def _value(data, nbytes: int) -> int:
    return int.from_bytes(bytes(data)[:nbytes].ljust(nbytes, b"\0"), "little")


class smu_smc_reset_inflight_test_seq(smu_axi_in_sep_aperture_test_seq):
    """SMC warm, cool, FLR, core and uncore resets with ext_in, smc_out and SEP traffic."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.mem = test.cfg.axi_out_mem
        self.period = float(self.cfg.smu_clk_period_ns)
        self.smu = smu_scope(self.dut)
        self.warm_net = hier(self.smu, WARM_RESET_PATH)
        self.pulse_done = hier(self.smu, PULSE_DONE_PATH)
        self.pulse_low: int | None = None
        self.primary = smc_primary_reset(self.dut)
        self.smc_in = getattr(self.dut, SMC_IN_SVA)
        self.master = None
        self.cyc = 0
        self.smc_cyc = 0
        self.ar_hs: list[tuple[int, int]] = []
        self.aw_hs: list[tuple[int, int]] = []
        self.trial: int | str | None = None
        self.trial_stats: dict[int | str, list[int]] = {}
        self.sites: list[dict] = []
        self.windows: list[dict] = []
        self.j2a_sizes: list[tuple[int, int]] = []
        self.step = "S0"
        self.ctx: str | None = None
        self.ir_key: int | None = None
        self.selected = True
        self.pad = 0
        self.sep_attached: list[tuple[str, int]] = []
        self.uid = FIRST_UID
        self.smc_base = GB_RESET
        self.term = "SETUP"
        self.terms: dict[str, list] = {}
        self.failures: list[str] = []
        self.steps: dict[str, bool] = {}
        self.r: dict[str, object] = {}
        self.warm_sources = 0
        self.cool_trials = 0
        self.bite_fell: bool | None = None
        self.soft = False
        self.smc_in_r = 0
        self.ext_in_r = 0
        self.r_xz = 0
        self.train: dict | None = None
        self.undrained_lines = 0
        self.obs_train_lines = 0
        self.probed: list[str] = []
        self.done = False

    # ---- bookkeeping ---------------------------------------------------------------------

    def _now(self) -> float:
        return float(get_sim_time(unit="ns"))

    def _enter(self, term: str, step: str, text: str) -> None:
        self.term = term
        self.step = step
        if term not in self.terms:
            self.terms[term] = [self._now(), 0]
        self.log.info("STEP %s @%.1fns term=%s: %s", step, self._now(), term, text)

    def _count(self) -> None:
        self.terms.setdefault(self.term, [self._now(), 0])[1] += 1

    @contextlib.contextmanager
    def _within(self, ctx: str | None):
        """Book the bounded waits inside the block under ``ctx`` (an OBS name or poll_access)."""
        outer, self.ctx = self.ctx, ctx
        try:
            yield
        finally:
            self.ctx = outer

    def _obs_ctx(self) -> bool:
        return self.ctx is not None and self.ctx.startswith("OBS-")

    def _site(self, kind: str, label: str, bound: int, used: int, last: str, expired: bool):
        """Record one bounded wait. Inside an OBS context it is that observation's window;
        inside a counted poll it is one access of the poll; otherwise a proof-path wait that
        fails the leaf when it expires."""
        if self._obs_ctx():
            self._obs_window(self.ctx, f"{kind}:{label}", bound, used, not expired, last)
            return
        if self.ctx == "poll_access":
            kind, label = "poll_access", f"{kind}:{label}"
        self.sites.append(
            {
                "step": self.step,
                "kind": kind,
                "label": label,
                "bound": bound,
                "used": used,
                "last": last,
                "expired": int(expired),
                "graded": int(self.soft),
            }
        )
        if expired and not self.soft:
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
        """One checker compare; its evidence line is printed by the scoreboard only on a pass."""
        self.log.info("INFO-COMPARE %s observed=%s expected=%s", chk, got, want)
        try:
            self.sb.expect_eq(line, got, want, evidence=chk)
        except AssertionError as exc:
            self.failures.append(str(exc))

    def _next_uid(self) -> int:
        uid = self.uid
        self.uid += 1
        if self.uid > 0xFF:
            raise AssertionError("ext_in AXI ID space exhausted")
        return uid

    def _g(self, local: int) -> int:
        """ext_in address of an SMC register at the current GLOBAL_BASE."""
        return self.smc_base + (local - SMC_LOCAL_BASE)

    def _p(self) -> int:
        return sample(self.primary, "rst_primary_smc_clk_n_o")

    def _w(self) -> int:
        return sample(self.warm_net, WARM_RESET_PATH)

    async def _tap(self) -> None:
        """ext_in handshakes and the trial reset probes, every clk_smu_i."""
        dut = self.dut
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
            self._count_r()
            if self.trial is not None:
                stats = self.trial_stats.setdefault(self.trial, [0, 0, 0, 0, 0])
                p, w = self._p(), self._w()
                stats[0] += int(p == 0)
                stats[1] += int(p == 0 and w != 0)
                stats[2] += int(w == 0)
                if p == 0:
                    stats[3] += sample(dut.ext_in_awvalid, "ext_in_awvalid")
                    stats[4] += sample(dut.ext_in_arvalid, "ext_in_arvalid")

    def _count_r(self) -> None:
        """R handshakes at ext_in and at the crossbar smc_in port (the inputs of the smc_in
        AXI checker), read passively; an unresolved level counts as no handshake and is tallied
        while a train is held."""
        levels = []
        for handle, name in (
            (self.dut.ext_in_rvalid, "ext_in_rvalid"),
            (self.dut.ext_in_rready, "ext_in_rready"),
            (self.smc_in.rvalid, f"{SMC_IN_SVA}.rvalid"),
            (self.smc_in.rready, f"{SMC_IN_SVA}.rready"),
        ):
            value = handle.value
            resolvable = getattr(value, "is_resolvable", True)
            if not resolvable and self.train is not None:
                self.r_xz += 1
            levels.append(sample(handle, name, allow_xz=True))
        self.ext_in_r += int(levels[0] == 1 and levels[1] == 1)
        self.smc_in_r += int(levels[2] == 1 and levels[3] == 1)

    async def _smc_clock(self) -> None:
        clk = self.dut.obs_smc_clk_o
        while True:
            await RisingEdge(clk)
            self.smc_cyc += 1
            if self.pulse_low is not None:
                self.pulse_low += 1 - (sample(self.pulse_done, PULSE_DONE_PATH) & 1)

    # ---- ext_in --------------------------------------------------------------------------

    def _start(
        self,
        *,
        write: bool,
        addr: int,
        value: int = 0,
        nbytes: int = 4,
        ident: int = MISC_ID,
    ) -> dict:
        size = 3 if nbytes == 8 else 2
        if write:
            data = (value & ((1 << (8 * nbytes)) - 1)).to_bytes(nbytes, "little")
            event = self.master.init_write(addr, data, size=size, id=ident)
        else:
            event = self.master.init_read(addr, nbytes, size=size, id=ident)
        self._count()
        return {
            "event": event,
            "write": write,
            "addr": addr,
            "id": ident,
            "nbytes": nbytes,
            "issue": self.cyc,
            "primary": self._p(),
            "warm": self._w(),
        }

    async def _done(self, rec: dict, label: str, *, obs: str | None = None) -> tuple:
        """Wait for one ext_in response, bounded; inside an OBS window a missing response is
        recorded as done=0 instead of failing."""
        start = self.cyc
        with self._within(obs or self.ctx):
            try:
                await with_timeout(rec["event"].wait(), round(EXT_IN_BOUND * self.period), "ns")
            except Exception:  # noqa: BLE001 -- the expiry is recorded with its last state
                rec["done"], rec["resp"], rec["value"], rec["end"] = 0, None, None, self.cyc
                self._site(
                    "ext_in",
                    label,
                    EXT_IN_BOUND,
                    self.cyc - start,
                    f"addr=0x{rec['addr']:x} id=0x{rec['id']:x} no response",
                    True,
                )
                return None, None
            raw = rec["event"].data
            if raw is None:
                # The master flushed it at its link reset; nothing reached the bench.
                rec["done"], rec["resp"], rec["value"], rec["end"] = 0, None, None, self.cyc
                self._site(
                    "ext_in",
                    label,
                    EXT_IN_BOUND,
                    self.cyc - start,
                    f"addr=0x{rec['addr']:x} id=0x{rec['id']:x} flushed at the link reset",
                    True,
                )
                return None, None
            resp = worst_resp(getattr(raw, "resp", None))
            value = None if rec["write"] else _value(getattr(raw, "data", b""), rec["nbytes"])
            rec["done"], rec["resp"], rec["value"], rec["end"] = 1, resp, value, self.cyc
            self._site(
                "ext_in",
                label,
                EXT_IN_BOUND,
                self.cyc - start,
                f"resp={resp_name(resp)} value={value if value is None else hex(value)}",
                False,
            )
        return resp, value

    async def _rd(self, local: int, label: str, nbytes: int = 4) -> tuple:
        return await self._done(self._start(write=False, addr=self._g(local), nbytes=nbytes), label)

    async def _wr(self, local: int, value: int, label: str, nbytes: int = 4):
        rec = self._start(write=True, addr=self._g(local), value=value, nbytes=nbytes)
        resp, _ = await self._done(rec, label)
        return resp

    async def _wr_ok(self, local: int, value: int, label: str, nbytes: int = 4) -> None:
        resp = await self._wr(local, value, label, nbytes)
        if resp != RESP_OKAY:
            raise AssertionError(f"ext_in write {label} 0x{local:x} answered {resp_name(resp)}")

    async def _rd_val(self, local: int, label: str, nbytes: int = 4) -> int:
        resp, value = await self._rd(local, label, nbytes)
        if resp != RESP_OKAY:
            raise AssertionError(f"ext_in read {label} 0x{local:x} answered {resp_name(resp)}")
        return value

    async def _wdt_write(self, core: int, reg: str, value: int, label: str) -> None:
        await self._wr_ok(WDT[core]["KEY"], WDT_KEY_MAGIC, f"{label}_key")
        await self._wr_ok(WDT[core][reg], value, label)

    def _r_pause(self, held: bool) -> None:
        self.master.driver.channels["r_ready_delay"].pause = held

    async def _wait_hs(self, chan: str, idents: list[int], after: int, label: str) -> dict:
        hs = self.ar_hs if chan == "ar" else self.aw_hs
        used = 0
        while True:
            got = {i: c for c, i in hs if c > after and i in idents}
            if len(got) == len(idents) or used >= HS_BOUND:
                break
            used += 1
            await RisingEdge(self.dut.clk_smu_i)
        self._site(
            "handshake",
            label,
            HS_BOUND,
            used,
            f"{chan} seen={len(got)}",
            len(got) != len(idents),
        )
        return got

    async def _wait_level(
        self, label: str, handle, name: str, want: int, bound: int
    ) -> tuple[int, bool, int]:
        """Wait for a reset level, bounded; returns (cycle, reached, cycles used)."""
        used = 0
        while True:
            level = sample(handle, name)
            if level == want or used >= bound:
                break
            used += 1
            await RisingEdge(self.dut.clk_smu_i)
        self._site("reset_level", label, bound, used, f"{name}={level}", level != want)
        return self.cyc, level == want, used

    async def _poll(self, label: str, read, pred, bound: int = REG_POLLS) -> tuple:
        """Read until ``pred`` holds, bounded; returns the last value and every value read."""
        seen = []
        used = 0
        while True:
            with self._within(self.ctx or "poll_access"):
                value = await read()
            seen.append(value)
            used += 1
            if pred(value) or used >= bound:
                break
        self._site("reg_poll", label, bound, used, f"value={value}", not pred(value))
        return value, seen

    # ---- composed JTAG scans -------------------------------------------------------------

    def _scan(self, value: int, width: int) -> tuple[int, int]:
        """A PTAP register scan, composed over the STAP network while the SEP STAP is selected,
        or followed by ``pad`` SIB bits when only the SIBs are in the chain."""
        if self.selected:
            return network_scan(value, width, NOP_REQUEST, DMI_DR_WIDTH)
        return network_scan(value, width, 0, 0) if self.pad else (value, width)

    def _ptap(self, raw: int, width: int) -> int:
        if self.selected:
            return ptap_dr_from_capture(raw, width, DMI_DR_WIDTH)
        return (int(raw) >> self.pad) & ((1 << width) - 1)

    async def _ir(self, opcode: int) -> None:
        if self.ir_key == opcode:
            return
        if self.selected:
            value, width = network_ir_scan(opcode, SEP_TAP_IR_DMI)
        else:
            value, width = self._scan(opcode, DTP_IR_WIDTH)
        await self.jtag.shift_ir(value, width=width, back_to_rti=True)
        require_jtag_tdo_resolved(f"IR 0x{opcode:x}")
        self.ir_key = opcode

    async def _dmi_scan(self, jtag, req: int) -> int:
        await self._ir(DTP_IR_TAP_3DCR)
        return await super()._dmi_scan(jtag, req)

    async def _dmi(self, jtag, addr: int, data: int, op: int) -> int:
        """One DMI op collected with NOP scans; its retry loop is a bounded, recorded wait."""
        self._count()
        await self._dmi_scan(jtag, pack_dmi(addr, data, op=op))
        status = DMI_STATUS_BUSY
        value = 0
        used = 0
        while used < DMI_RETRIES:
            captured = await self._dmi_scan(jtag, pack_dmi(addr, 0, op=DMI_OP_NOP))
            used += 1
            _, value, status = unpack_dmi(captured)
            if status != DMI_STATUS_BUSY:
                break
        self._site(
            "dmi_retry",
            f"op{op}@0x{addr:02x}",
            DMI_RETRIES,
            used,
            f"status={status}",
            status == DMI_STATUS_BUSY,
        )
        if status != DMI_STATUS_OK:
            raise AssertionError(f"DMI op={op} addr=0x{addr:02x} status={status}")
        return value

    async def _sba_poll(self, jtag, label: str) -> int:
        used = 0
        sbcs = SBCS_SBBUSY
        while used < SBA_POLLS:
            with self._within(self.ctx or "poll_access"):
                sbcs = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            used += 1
            if not sbcs & SBCS_SBBUSY:
                break
        self._site(
            "sba_busy", label, SBA_POLLS, used, f"sbcs=0x{sbcs:08x}", bool(sbcs & SBCS_SBBUSY)
        )
        return sbcs

    async def _sba_wait(self, jtag, what: str) -> None:
        sbcs = await self._sba_poll(jtag, what)
        sberror = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        if sberror or (sbcs & SBCS_SBBUSYERROR):
            raise AssertionError(f"system-bus {what}: sbcs=0x{sbcs:08x} sberror={sberror}")

    async def _sb(self, addr: int, data: int | None, label: str) -> tuple[int, int]:
        """A 32-bit system-bus access returning (sberror, read data); sberror is cleared."""
        jtag = self.jtag
        if data is None:
            await self._dmi(
                jtag,
                SBCS_ADDR,
                SBCS_SBACCESS_32 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
                DMI_OP_WRITE,
            )
            await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
        else:
            await self._dmi(jtag, SBCS_ADDR, SBCS_SBACCESS_32 | SBCS_SBERROR_W1C, DMI_OP_WRITE)
            await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
            await self._dmi(jtag, SBDATA0_ADDR, data, DMI_OP_WRITE)
        sbcs = await self._sba_poll(jtag, label)
        err = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        value = await self._dmi(jtag, SBDATA0_ADDR, 0, DMI_OP_READ) if data is None else 0
        if err:
            await self._dmi(jtag, SBCS_ADDR, SBCS_SBERROR_W1C, DMI_OP_WRITE)
        return err, value

    async def _sb_try(self, addr: int, data: int | None, label: str, obs: str) -> dict:
        """An OBS system-bus access: primary level before and after, outcome or the failure."""
        before = self._p()
        if not self.selected:
            self.log.info(
                "INFO-SBA %s (%s) not issued: no SEP debug path after the reset", label, obs
            )
            return {"ok": 0, "sberror": None, "data": None, "issued": 0, "primary": ()}
        with self._within(obs):
            try:
                err, value = await self._sb(addr, data, label)
                out = {"ok": 1, "sberror": err, "data": value, "issued": 1}
            except Exception as exc:  # noqa: BLE001 -- an OBS leg records its failure
                out = {"ok": 0, "sberror": None, "data": None, "issued": 1}
                self.log.info("INFO-SBA %s (%s) system-bus access failed: %s", label, obs, exc)
        out["primary"] = (before, self._p())
        return out

    async def _j2a_issue(self, op: int, addr: int, data: int, wstrb: int) -> None:
        """One SINGLE_OP issue; every access is AXSIZE 8 at an 8-byte aligned address."""
        if addr & 0x7:
            raise AssertionError(f"JTAG2AXI address 0x{addr:x} is not 8-byte aligned")
        await self._ir(DTP_IR_SMC_AXI_SINGLE_OP)
        word, total = self._scan(
            pack_single_op(op, addr, data, wstrb=wstrb, size=SMC_DBG_AXSIZE_8B),
            SMC_DBG_SINGLE_OP_LEN,
        )
        await self.jtag.shift_dr(word, total, back_to_rti=True)
        require_jtag_tdo_resolved(f"J2A issue @0x{addr:x}")
        self.j2a_sizes.append((addr, SMC_DBG_AXSIZE_8B))
        self._count()

    async def _j2a_capture(self, label: str, *, obs: str | None = None) -> tuple:
        """Capture SINGLE_OP until it leaves BUSY, bounded."""
        await self._ir(DTP_IR_SMC_AXI_SINGLE_OP)
        word, total = self._scan(0, SMC_DBG_SINGLE_OP_LEN)
        used = 0
        status, rdata = J2A_STATUS_BUSY, 0
        while used < J2A_POLLS:
            raw = await self.jtag.shift_dr(word, total, back_to_rti=True)
            require_jtag_tdo_resolved(f"J2A capture {label}")
            used += 1
            status, rdata = unpack_single_op(self._ptap(raw, SMC_DBG_SINGLE_OP_LEN))
            if status != J2A_STATUS_BUSY:
                break
        with self._within(obs or self.ctx):
            self._site(
                "j2a_capture",
                label,
                J2A_POLLS,
                used,
                f"status={status} rdata=0x{rdata:x}",
                status == J2A_STATUS_BUSY,
            )
        return status, rdata

    async def _j2a_rd(self, addr: int, label: str, *, obs: str | None = None) -> tuple:
        await self._j2a_issue(J2A_OP_READ, addr, 0, 0)
        return await self._j2a_capture(label, obs=obs)

    async def _j2a_wr(
        self, addr: int, value: int, label: str, *, wstrb: int = J2A_FULL_WSTRB
    ) -> int:
        await self._j2a_issue(J2A_OP_WRITE, addr, value, wstrb)
        status, _ = await self._j2a_capture(label)
        return status

    async def _j2a_wr_ok(self, addr: int, value: int, label: str) -> None:
        status = await self._j2a_wr(addr, value, label)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"JTAG2AXI write {label} @0x{addr:x} status={status}")

    async def _port_settles(self, name: str, want: int) -> int:
        """The aperture port reaching its programmed value, bounded and recorded."""
        handle = getattr(self.dut, name)
        observed = sample(handle, name)
        used = 0
        while observed != want and used < PORT_POLL_CYCLES:
            await RisingEdge(self.dut.clk_smu_i)
            used += 1
            observed = sample(handle, name)
        self._site(
            "port_settle", name, PORT_POLL_CYCLES, used, f"{name}=0x{observed:x}", observed != want
        )
        return observed

    # ---- setup and re-attach -------------------------------------------------------------

    async def _sep_setup(self) -> None:
        jtag = self.jtag
        await self._window(jtag, WIN_BASE, WIN_SIZE)
        await self._sba_write(jtag, OUTBOUND_START_ADDR, EGRESS_ADDR)
        await self._sba_write(jtag, OUTBOUND_END_ADDR, EGRESS_PAGE_END)
        await self._sba_write(jtag, OUTBOUND_FILTER_CONFIG, OUTBOUND_CFG_OPEN)

    async def _smc_filters(self, label: str) -> None:
        for addr, value, name in (
            (INBOUND0_START, 0, "in_start"),
            (INBOUND0_END, PASS_ALL_END, "in_end"),
            (INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "in_cfg"),
            (OUTBOUND0_START, 0, "out_start"),
            (OUTBOUND0_END, PASS_ALL_END, "out_end"),
            (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "out_cfg"),
        ):
            await self._j2a_wr_ok(addr, value, f"{label}_{name}")

    async def _reattach(self, label: str) -> None:
        """TAP reset, SEP STAP, dmactive, SEP aperture and egress filter, SMC filters."""
        jtag = self.jtag
        await self._tlr()
        self.log.info(
            "INFO-%s SEP aperture before re-programming base=0x%x size=0x%x",
            label,
            sample(self.dut.sep_global_base_o, "sep_global_base_o"),
            sample(self.dut.sep_region_size_o, "sep_region_size_o"),
        )
        # The SEP debug path after an SMC primary reset is itself unstated (SF-029): its
        # bounded waits are OBS-SMCRST-NONSMC-PATHS windows and a failure leaves the SEP legs
        # of the rest of the leaf unissued rather than failing the SMC legs.
        with self._within("OBS-SMCRST-NONSMC-PATHS"):
            try:
                await self._select_sep_stap(jtag)
                self.selected = True
                self.ir_key = None
                await self._dmi(jtag, DMCONTROL_ADDR, DMCONTROL_DMACTIVE, DMI_OP_WRITE)
                version = await self._dmi(jtag, DMSTATUS_ADDR, 0, DMI_OP_READ) & 0xF
                if version != DMSTATUS_VERSION_SPEC_0_13:
                    raise AssertionError(f"dmstatus.version={version} after the SEP STAP select")
                await self._sep_setup()
                self.sep_attached.append((label, 1))
            except Exception as exc:  # noqa: BLE001 -- recorded; the SMC legs go on
                self.log.info("INFO-%s SEP debug path not re-established: %s", label, exc)
                self.sep_attached.append((label, 0))
                await self._tlr()
        self.log.info("INFO-%s SEP debug path re-established=%d", label, self.sep_attached[-1][1])
        if not self.selected:
            await self._probe_chain(label)
        await self._smc_filters(label)

    async def _probe_chain(self, label: str) -> None:
        """Find the PTAP framing without the SEP TAP: the STAP select set by the attempt holds
        through Test-Logic-Reset, so the SIB flops may follow the PTAP. One IDCODE scan, wide
        enough for either chain, decides the pad the SMC legs' scans carry."""
        await self.jtag.shift_ir(dtp_ir_opcode("IDCODE"), width=DTP_IR_WIDTH, back_to_rti=True)
        require_jtag_tdo_resolved(f"IR IDCODE {label}")
        raw = await self.jtag.shift_dr(0, IDCODE_DR_WIDTH + SIB_PAD, back_to_rti=True)
        require_jtag_tdo_resolved(f"DR IDCODE {label}")
        self.ir_key = None
        mask = (1 << IDCODE_DR_WIDTH) - 1
        fits = [pad for pad in (0, SIB_PAD) if (int(raw) >> pad) & mask == DTP_DEFAULT_IDCODE]
        self.log.info(
            "CTRL-SMCRST-CHAIN: %s idcode scan raw=0x%x pads matching 0x%x=%s",
            label,
            raw,
            DTP_DEFAULT_IDCODE,
            fits,
        )
        if len(fits) != 1:
            raise AssertionError(f"PTAP framing after {label} unknown: raw=0x{raw:x}")
        self.pad = fits[0]
        self.probed.append(label)

    async def _tlr(self) -> None:
        for _ in range(TLR_TCKS):
            await self.jtag.step_tms(1)
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        self.selected = False
        self.ir_key = None

    # ---- S1 / S2 -------------------------------------------------------------------------

    async def _s1_setup(self) -> None:
        self._enter("SETUP", "S1", "SEP aperture, egress filter, SMC filters over JTAG2AXI")
        self.ir_key = DTP_IR_TAP_3DCR
        await self._sep_setup()
        self.master = await make_smu_axi_master(cocotb.top, self.dut.clk_smu_i, self.primary)
        await self._smc_filters("s1")
        self.log.info(
            "INFO-S1 ext_in master on the SMC primary reset; responder on rst_cold_n_o; "
            "SMC aperture 0x%x/0x%x",
            sample(self.dut.smc_global_base_o, "smc_global_base_o"),
            sample(self.dut.smc_region_size_o, "smc_region_size_o"),
        )
        self.steps["S1"] = True

    def _images(self) -> tuple:
        rows = (
            ("SS_CONFIG", SS_CONFIG, SS_CONFIG_PAT, 4, SS_MASK),
            ("SS_COLD_RESET_N", SS_COLD, SS_COLD_PAT, 4, SS_COLD_MASK),
        )
        rows += tuple((f"RESET_VECTOR{i}", RV[i], RV_PAT[i], 8, RV_MASK) for i in range(4))
        rows += (
            ("WDT_TIMEOUT", WDT_TIMEOUT, WDT_TIMEOUT_PAT, 4, WDT_TIMEOUT_MASK),
            ("RESET_TIMEOUT", RESET_TIMEOUT, RT_PAT, 8, RT_MASK),
            ("RESET_CTRL", RESET_CTRL, RC_PAT, 8, RC_MASK),
            ("ISOLATE_REQ_REG", ISO_REG, ISO_PAT, 4, ISO_MASK),
            ("REGION_SIZE", REGION_SIZE, RS_PAT, 8, RS_MASK),
        )
        return rows

    async def _s2_images(self) -> None:
        self._enter("IMAGES", "S2", "images over ext_in, then GLOBAL_BASE 0x6000_0000")
        rows = self._images()
        for name, local, value, nbytes, _ in rows:
            await self._wr_ok(local, value, f"s2_wr_{name}", nbytes)
        got = {}
        for name, local, _, nbytes, mask in rows:
            resp, value = await self._rd(local, f"s2_rd_{name}", nbytes)
            got[name] = (resp, None if value is None else value & mask)
        await self._wr_ok(GLOBAL_BASE, GB_PAT, "s2_wr_GLOBAL_BASE", 8)
        self.smc_base = GB_PAT
        resp, value = await self._rd(GLOBAL_BASE, "s2_rd_GLOBAL_BASE", 8)
        got["GLOBAL_BASE"] = (resp, None if value is None else value & GB_MASK)
        want = {name: (RESP_OKAY, value) for name, _, value, _, _ in rows}
        want["GLOBAL_BASE"] = (RESP_OKAY, GB_PAT)
        self.log.info("INFO-S2 images read back %s", got)
        self.r["images"] = (got, want)
        self.steps["S2"] = True

    # ---- S3 / S4 warm --------------------------------------------------------------------

    async def _core_counts(self, label: str) -> dict:
        """CORE0 and CORE1 watchdogs on wdogcoreawake, COUNT read twice 512 clk_smc apart."""
        for core in (0, 1):
            await self._wdt_write(core, "CTRL", WDT_COREAWAKE, f"{label}_core{core}_ctrl")
        counts = {}
        for core in (0, 1):
            first = await self._rd_val(WDT[core]["COUNT"], f"{label}_core{core}_count1")
            await ClockCycles(self.dut.obs_smc_clk_o, COUNT_GAP_SMC)
            second = await self._rd_val(WDT[core]["COUNT"], f"{label}_core{core}_count2")
            counts[core] = (first & WDT_COUNT_MASK, second & WDT_COUNT_MASK)
        return counts

    async def _warm(self, src: str) -> None:
        self._enter("WARM", "S3", f"warm reset from {src} with ext_in reads held across the fall")
        # The debug bus completes each access, so the system-bus read is issued as late as the
        # source allows: after the CORE0 arming, or between the bite programming and the
        # enable write that starts it.
        if src == "wdt2":
            await self._wdt_write(0, "CMP", WDT_CMP_ARMED, "s3_wdt2_cmp")
            await self._wdt_write(0, "CTRL", WDT_RSTEN | WDT_ALWAYS | WDT_ZEROCMP, "s3_wdt2_ctrl")
            sep = await self._sb_try(
                self._g(SS_CONFIG), None, f"s3_{src}_sep2smc", "OBS-SMCRST-WARM-INFLIGHT"
            )
            sep_cyc = self.cyc
        else:
            await self._sba_write(self.jtag, WDOG_BITE, WDOG_BITE_TICKS)
            await self._sba_write(self.jtag, WDOG_COUNT, 0)
            sep = await self._sb_try(
                self._g(SS_CONFIG), None, f"s3_{src}_sep2smc", "OBS-SMCRST-WARM-INFLIGHT"
            )
            sep_cyc = self.cyc
            await self._dmi(self.jtag, SBCS_ADDR, SBCS_SBACCESS_32 | SBCS_SBERROR_W1C, DMI_OP_WRITE)
            await self._dmi(self.jtag, SBADDRESS0_ADDR, WDOG_CTRL, DMI_OP_WRITE)
        mark = self.cyc
        self._r_pause(True)
        held = [
            self._start(write=False, addr=self._g(SS_CONFIG), ident=self._next_uid())
            for _ in range(2)
        ]
        ar = await self._wait_hs("ar", [h["id"] for h in held], mark, f"s3_{src}_ar")
        if src == "bite":
            await self._dmi(self.jtag, SBDATA0_ADDR, WDOG_ENABLE, DMI_OP_WRITE)
        # The bite's warm fall is seed-dependent (SF-006): its wait is an observation window.
        with self._within("OBS-SMCRST-BITE-NO-WARM" if src == "bite" else None):
            fall, fell, used = await self._wait_level(
                f"s3_{src}_warm_fall", self.warm_net, WARM_RESET_PATH, 0, WARM_FALL_BOUND
            )
        if src == "bite":
            self.bite_fell = fell
            self.log.info(
                "OBS-SMCRST-BITE-NO-WARM: seed=%d bound=%d used=%d warm_fell=%d",
                cocotb.RANDOM_SEED,
                WARM_FALL_BOUND,
                used,
                int(fell),
            )
        during = self._start(write=False, addr=self._g(RESET_CTRL), ident=self._next_uid())
        self._r_pause(False)
        rise = -1
        if fell:
            rise, _, _ = await self._wait_level(
                f"s3_{src}_warm_rise", self.warm_net, WARM_RESET_PATH, 1, RESET_LEVEL_BOUND
            )
        primary_in_warm = self._p()
        if src == "bite":
            await self._sba_wait(self.jtag, "s3_bite_enable")
        results = []
        for i, rec in enumerate(held):
            results.append(await self._done(rec, f"s3_{src}_held{i}"))
        during_res = await self._done(during, f"s3_{src}_during")
        during_ar = next((c for c, i in self.ar_hs if i == during["id"] and c >= fall), -1)
        sep_data = sep["data"]
        self.log.info(
            "OBS-SMCRST-WARM-INFLIGHT: src=%s port=sep2smc done=%d resp=%s data=%s "
            "off_before_edge=%d",
            src,
            sep["ok"],
            "-" if sep["sberror"] is None else f"sberror{sep['sberror']}",
            "-" if sep_data is None else f"0x{sep_data:08x}",
            fall - sep_cyc,
        )
        self.log.info(
            "OBS-SMCRST-SEP2SMC: reset=warm sberror=%s data=%s",
            "-" if sep["sberror"] is None else sep["sberror"],
            "-" if sep_data is None else f"0x{sep_data:08x}",
        )
        for rec, (resp, value) in zip(held, results):
            self.log.info(
                "OBS-SMCRST-WARM-INFLIGHT: src=%s port=smc_in done=%d resp=%s data=%s "
                "off_before_edge=%d",
                src,
                rec["done"],
                resp_name(resp) if resp is not None else "-",
                "-" if value is None else f"0x{value:08x}",
                fall - ar[rec["id"]],
            )
        self.log.info(
            "INFO-S3 %s warm fall@%d rise@%d ar=%s during_ar@%d primary=%d",
            src,
            fall,
            rise,
            ar,
            during_ar,
            primary_in_warm,
        )
        post = {}
        for name, local, nbytes, mask in (
            ("RESET_CTRL", RESET_CTRL, 8, RC_MASK),
            ("RESET_VECTOR0", RV[0], 8, RV_MASK),
            ("WDT_TIMEOUT", WDT_TIMEOUT, 4, WDT_TIMEOUT_MASK),
            ("GLOBAL_BASE", GLOBAL_BASE, 8, GB_MASK),
            ("REGION_SIZE", REGION_SIZE, 8, RS_MASK),
        ):
            resp, value = await self._rd(local, f"s3_{src}_post_{name}", nbytes)
            post[name] = (resp, None if value is None else value & mask)
        counts = await self._core_counts(f"s3_{src}")
        self.log.info("INFO-S3 %s post=%s counts=%s", src, post, counts)
        self.r.setdefault("warm", {})[src] = {
            "fell": fell,
            "held": [(all(c < fall for c in ar.values()), resp, value) for resp, value in results],
            "during": (fall <= during_ar < rise, during_res[0], during_res[1]),
            "post": post,
            "counts": counts,
        }
        self.warm_sources += 1

    async def _warm_post(self) -> None:
        self._enter("WARM_POST", "S4", "fresh ext_in SCRATCH[0], JTAG2AXI egress and SEP SRAM")
        await self._wr_ok(SCRATCH[0], 0, "s4_scratch_clear")
        w = await self._wr(SCRATCH[0], SCRATCH_WORD, "s4_scratch_wr")
        r, value = await self._rd(SCRATCH[0], "s4_scratch_rd")
        e_addr, e_word = EGRESS_WORDS["warm_post"]
        self.mem.write_int(e_addr, e_word, 8)
        s_addr, s_word = SRAM_WORDS["warm_post"]
        sram_w = await self._done(
            self._start(write=True, addr=s_addr, value=s_word, nbytes=8), "s4_sram_wr"
        )
        e = await self._j2a_rd(e_addr, "s4_j2a_egress")
        s = await self._j2a_rd(s_addr, "s4_j2a_sram")
        self.log.info(
            "INFO-S4 scratch w=%s r=%s/%s egress=%s sram_wr=%s sram=%s",
            resp_name(w),
            resp_name(r),
            value,
            e,
            sram_w,
            s,
        )
        self.r["warm_post"] = (
            (w, r, value),
            (e[0], e[1]),
            (sram_w[0], s[0], s[1]),
            (SCRATCH_WORD, e_word, s_word),
        )
        self.steps["S3"] = self.steps["S4"] = True

    def _graded_sources(self) -> tuple[str, ...]:
        """The watchdog source is always compared; the bite source only when its warm fall
        happened inside the OBS-SMCRST-BITE-NO-WARM window."""
        warm = self.r["warm"]
        graded = tuple(src for src in ("wdt2", "bite") if src == "wdt2" or warm[src]["fell"])
        for src in ("wdt2", "bite"):
            if src not in graded:
                self.log.info(
                    "INFO-S3 %s cells recorded, not compared (OBS-SMCRST-BITE-NO-WARM "
                    "warm_fell=0): %s",
                    src,
                    warm[src],
                )
        return graded

    def _warm_checks(self) -> None:
        warm = self.r["warm"]
        wp = self.r["warm_post"]
        scratch_word, e_word, s_word = wp[3]
        graded = self._graded_sources()
        note = "" if "bite" in graded else " (bite recorded: OBS-SMCRST-BITE-NO-WARM warm_fell=0)"
        got = (
            {src: (warm[src]["held"], warm[src]["during"]) for src in graded},
            wp[0],
            wp[1],
            wp[2],
        )
        want = (
            {
                src: (
                    [(True, RESP_OKAY, SS_CONFIG_PAT)] * 2,
                    (True, RESP_OKAY, RC_PAT),
                )
                for src in graded
            },
            (RESP_OKAY, RESP_OKAY, scratch_word),
            (J2A_STATUS_SUCCESS, e_word),
            (RESP_OKAY, J2A_STATUS_SUCCESS, s_word),
        )
        self._verdict(
            "CHK-SMC-WARM-TRAFFIC",
            "CHK-SMC-WARM-TRAFFIC: wdt2/bite: ss_config inflight OKAY==pat; reset_ctrl during "
            f"OKAY==0x0100010D; post ext_in rw ok; smc_out->ext ok; smc_out->sep ok{note}",
            got,
            want,
        )
        got = {}
        for src in graded:
            c = warm[src]["counts"]
            got[src] = (warm[src]["post"], c[0][1] > c[0][0], c[1][1] == c[1][0])
        want_post = {
            "RESET_CTRL": (RESP_OKAY, RC_PAT),
            "RESET_VECTOR0": (RESP_OKAY, RV_PAT[0]),
            "WDT_TIMEOUT": (RESP_OKAY, WDT_TIMEOUT_PAT),
            "GLOBAL_BASE": (RESP_OKAY, GB_PAT),
            "REGION_SIZE": (RESP_OKAY, RS_PAT),
        }
        self._verdict(
            "CHK-SMC-WARM-RETAIN",
            "CHK-SMC-WARM-RETAIN: RC=0x0100010D RV0,WDT kept; GB/RS kept; core0 counts, core1 "
            f"frozen{note}",
            (self.r["images"][0], got),
            (self.r["images"][1], {src: (want_post, True, True) for src in graded}),
        )

    # ---- S5 / S6 cool --------------------------------------------------------------------

    async def _post_reads(self, label: str) -> dict:
        out = {}
        rows = tuple((f"RESET_VECTOR{i}", RV[i], 8, RV_MASK) for i in range(4))
        rows += (
            ("RESET_CTRL", RESET_CTRL, 8, RC_MASK),
            ("WDT_TIMEOUT", WDT_TIMEOUT, 4, WDT_TIMEOUT_MASK),
            ("RESET_TIMEOUT", RESET_TIMEOUT, 8, RT_MASK),
            ("SS_CONFIG", SS_CONFIG, 4, SS_MASK),
            ("SS_COLD_RESET_N", SS_COLD, 4, SS_COLD_MASK),
            ("GLOBAL_BASE", GLOBAL_BASE, 8, GB_MASK),
            ("REGION_SIZE", REGION_SIZE, 8, RS_MASK),
            ("ISOLATE_REQ_REG", ISO_REG, 4, ISO_MASK),
        )
        for name, local, nbytes, mask in rows:
            resp, value = await self._rd(local, f"{label}_{name}", nbytes)
            out[name] = (resp, None if value is None else value & mask)
        self.log.info("INFO-%s reads at 0x%x: %s", label, self.smc_base, out)
        return out

    async def _pre_cool_images(self) -> None:
        """The S2 images read again after both warm resets: the pre-image of the pin reset."""
        got = {}
        for name, local, _, nbytes, mask in self._images():
            if local == RESET_TIMEOUT:
                mask = RT_CFG_MASK
            resp, value = await self._rd(local, f"s5_pre_{name}", nbytes)
            got[name] = (resp, None if value is None else value & mask)
        resp, value = await self._rd(GLOBAL_BASE, "s5_pre_GLOBAL_BASE", 8)
        got["GLOBAL_BASE"] = (resp, None if value is None else value & GB_MASK)
        self.log.info("CTRL-SMCRST-PRE-COOL: images before the pin reset %s", got)
        self.r["images_pre_cool"] = got

    async def _hold_across(self, label: str) -> dict:
        """System-bus read through the SEP window, then an ext_in read held with RREADY low."""
        sep = await self._sb_try(
            self._g(SS_CONFIG), None, f"{label}_sep2smc", "OBS-SMCRST-COOL-INFLIGHT"
        )
        sep_cyc = self.cyc
        self._r_pause(True)
        mark = self.cyc
        rec = self._start(write=False, addr=self._g(SS_CONFIG), ident=self._next_uid())
        ar = await self._wait_hs("ar", [rec["id"]], mark, f"{label}_held_ar")
        return {"sep": sep, "sep_cyc": sep_cyc, "rec": rec, "ar": ar[rec["id"]]}

    async def _held_outcome(self, held: dict, src: str, label: str, edge: int, release: int):
        """Release RREADY, log the held ext_in read and the system-bus read; AR before the fall."""
        self._r_pause(False)
        rec = held["rec"]
        resp, value = await self._done(rec, f"{label}_held_r", obs="OBS-SMCRST-COOL-INFLIGHT")
        self.log.info(
            "OBS-SMCRST-COOL-INFLIGHT: src=%s port=smc_in dir=r done=%d resp=%s lane0=%s "
            "lane1=- cyc_from_edge=%d before_release=%d",
            src,
            rec["done"],
            resp_name(resp) if resp is not None else "-",
            "-" if value is None else f"0x{value:08x}",
            rec["end"] - edge,
            int(rec["end"] < release),
        )
        sep = held["sep"]
        self.log.info(
            "OBS-SMCRST-COOL-INFLIGHT: src=%s port=sep2smc dir=r done=%d resp=%s lane0=%s "
            "lane1=- cyc_from_edge=%d before_release=1",
            src,
            sep["ok"],
            "-" if sep["sberror"] is None else f"sberror{sep['sberror']}",
            "-" if sep["data"] is None else f"0x{sep['data']:08x}",
            held["sep_cyc"] - edge,
        )
        self.log.info(
            "OBS-SMCRST-SEP2SMC: reset=cool sberror=%s data=%s",
            "-" if sep["sberror"] is None else sep["sberror"],
            "-" if sep["data"] is None else f"0x{sep['data']:08x}",
        )
        if not sep["issued"]:
            self.log.info("OBS-SMCRST-NONSMC-PATHS: path=sba resp=unavailable")
        self.log.info(
            "INFO-%s held ext_in AR@%d primary fall@%d release@%d",
            label,
            held["ar"],
            edge,
            release,
        )
        return held["ar"] < edge

    def _link_line(self, key) -> None:
        stats = self.trial_stats.get(key, [0, 0, 0, 0, 0])
        self.log.info(
            "OBS-SMCRST-LINK-IN-RESET: awvalid_high=%d arvalid_high=%d cycles=%d",
            stats[3],
            stats[4],
            stats[0],
        )

    async def _rewrite(self, tag: str) -> tuple:
        """SS_CONFIG and RESET_VECTOR[0] written to their patterns and read back."""
        await self._wr_ok(SS_CONFIG, SS_CONFIG_PAT, f"{tag}_ss_config")
        await self._wr_ok(RV[0], RV_PAT[0], f"{tag}_rv0", 8)
        ss = await self._rd(SS_CONFIG, f"{tag}_ss_config_readback")
        rv = await self._rd(RV[0], f"{tag}_rv0_readback", 8)
        got = tuple(
            (resp, None if value is None else value & mask)
            for (resp, value), mask in ((ss, SS_MASK), (rv, RV_MASK))
        )
        self.log.info("CTRL-SMCRST-REWRITE: %s SS_CONFIG=%s RESET_VECTOR0=%s", tag, *got)
        return got

    async def _cool_trial(self, k: int) -> None:
        self._enter("COOL", "S5", f"pin trial {k}: held ext_in read, system-bus accesses in hold")
        dut = self.dut
        if k == 1:
            await self._pre_cool_images()
        if k == 2:
            self.r.setdefault("rewrite", {})[2] = await self._rewrite("s5_t2")
        if k == 1:
            j_addr, j_word = EGRESS_WORDS["trial1"]
            self.mem.write_int(j_addr, j_word, 8)
        else:
            j_addr, j_word = SRAM_WORDS["trial2"]
            await self._done(
                self._start(write=True, addr=j_addr, value=j_word, nbytes=8), "s5_t2_sram_seed"
            )
        status, rdata = await self._j2a_rd(
            j_addr, f"s5_t{k}_j2a_smc_out", obs="OBS-SMCRST-SMCOUT-ORPHAN"
        )
        self.log.info(
            "OBS-SMCRST-SMCOUT-ORPHAN: dst=%s done=%d resp=j2a%d wedged=0",
            "ext_out" if k == 1 else "sep_in",
            int(status != J2A_STATUS_BUSY),
            status,
        )
        self.log.info(
            "INFO-S5 trial %d JTAG2AXI read of 0x%x completed before the fall data=0x%x "
            "word=0x%x (an smc_out read held across the primary reset is not issuable here: the "
            "bench responder is on rst_cold_n_o)",
            k,
            j_addr,
            rdata,
            j_word,
        )
        held = await self._hold_across(f"s5_t{k}")
        self.trial = k
        dut.tb_cool_reset_pin.value = 1
        edge, _, _ = await self._wait_level(
            f"s5_t{k}_primary_fall", self.primary, "rst_primary_smc_clk_n_o", 0, RESET_LEVEL_BOUND
        )
        # During the hold only system-bus accesses; nothing is issued on ext_in while its link
        # is in reset. A lost SEP debug path (SF-029) stops the remaining accesses.
        sep_path = self.selected
        hold = []
        for name, addr, data, obs in (
            ("sep2smc_new", self._g(SCRATCH[3]), None, "OBS-SMCRST-COOL-NEW"),
            ("ext_w", EGRESS_ADDR + 0x400 + 4 * k, 0x5EB0_0400 | k, "OBS-SMCRST-NONSMC-PATHS"),
            ("ext_r", EGRESS_ADDR + 0x400 + 4 * k, None, "OBS-SMCRST-NONSMC-PATHS"),
        ):
            issue = self.cyc
            res = await self._sb_try(addr, data, f"s5_t{k}_{name}", obs)
            res["cyc"] = issue - edge
            hold.append((name, res))
            if not res["ok"]:
                break
        issue_levels = [res["primary"][0] for _, res in hold if res["issued"]]
        sba_lost = any(not res["ok"] for _, res in hold)
        dut.tb_cool_reset_pin.value = 0
        release, _, _ = await self._wait_level(
            f"s5_t{k}_primary_rise", self.primary, "rst_primary_smc_clk_n_o", 1, RESET_LEVEL_BOUND
        )
        # Warm follows the fuse reset, which releases only once fuse sensing ends again.
        await self._wait_level(
            f"s5_t{k}_warm_rise", self.warm_net, WARM_RESET_PATH, 1, WARM_FALL_BOUND
        )
        self.trial = None
        self.smc_base = GB_RESET
        ar_before = await self._held_outcome(held, "pin", f"s5_t{k}", edge, release)
        self._link_line(k)
        res = dict(hold).get("sep2smc_new")
        if res is None or not res["ok"]:
            self.log.info(
                "OBS-SMCRST-COOL-NEW: port=sep2smc resp=unavailable cyc=%s",
                "-" if res is None else res["cyc"],
            )
        else:
            self.log.info(
                "OBS-SMCRST-COOL-NEW: port=sep2smc resp=sberror%d cyc=%d",
                res["sberror"],
                res["cyc"],
            )
        if sba_lost or not hold:
            self.log.info("OBS-SMCRST-NONSMC-PATHS: path=sba resp=unavailable")
        for name, res in hold:
            if name != "sep2smc_new" and res["ok"]:
                self.log.info(
                    "OBS-SMCRST-NONSMC-PATHS: path=sep_out->ext resp=sberror%d", res["sberror"]
                )
        self.log.info(
            "INFO-S5 trial %d during-hold accesses: ext_in=0 system-bus=%d primary at issue=%s",
            k,
            len(issue_levels),
            issue_levels,
        )
        self._enter("COOL_POST", "S6", f"trial {k}: re-attach and reset-value reads")
        await self._reattach(f"s6_t{k}")
        post = await self._post_reads(f"s6_t{k}")
        inside = (
            bool(issue_levels) and all(level == 0 for level in issue_levels)
            if sep_path
            else NO_SEP_PATH
        )
        self.r.setdefault("cool", {})[k] = {
            "inside": (ar_before, inside),
            "sep_path": sep_path,
            "post": post,
        }
        self.cool_trials += 1
        self.steps["S5"] = self.steps["S6"] = True

    # ---- S7 FLR --------------------------------------------------------------------------

    async def _flr(self) -> None:
        self._enter("FLR", "S7", "FLR-timed cool reset with an ext_in read held across it")
        dut = self.dut
        self.r.setdefault("rewrite", {})["flr"] = await self._rewrite("s7")
        await self._wr_ok(FLR_COUNTER, FLR_COUNTER_PAT, "s7_flr_counter")
        await self._wr_ok(FLR_HOLD, FLR_HOLD_PAT, "s7_flr_hold")
        dut.tb_cfg_flr_pf_active.value = 0
        held = await self._hold_across("s7")
        self.trial = "flr"
        dut.tb_cfg_flr_pf_active.value = 1
        edge, _, _ = await self._wait_level(
            "s7_primary_fall", self.primary, "rst_primary_smc_clk_n_o", 0, RESET_LEVEL_BOUND
        )
        release, _, _ = await self._wait_level(
            "s7_primary_rise", self.primary, "rst_primary_smc_clk_n_o", 1, RESET_LEVEL_BOUND
        )
        await self._wait_level("s7_warm_rise", self.warm_net, WARM_RESET_PATH, 1, WARM_FALL_BOUND)
        self.trial = None
        dut.tb_cfg_flr_pf_active.value = 0
        self.smc_base = GB_RESET
        self.log.info(
            "INFO-S7 FLR primary fall@%d rise@%d (%d clk_smu)", edge, release, release - edge
        )
        self.r["flr_inside"] = (await self._held_outcome(held, "flr", "s7", edge, release),)
        self._link_line("flr")
        await self._reattach("s7")
        self.r["flr_post"] = await self._post_reads("s7_post")
        # The latched isolation leg: the latch over 8-byte JTAG2AXI around two new accesses.
        e_addr, e_word = EGRESS_WORDS["iso"]
        self.mem.write_int(e_addr, e_word, 8)
        self.log.info("INFO-LIFECYCLE ISO-LATCH set: FLR edge @%d", edge)
        latch_issue = await self._latch_read("issue")
        rec = self._start(write=False, addr=self._g(SS_CONFIG), ident=self._next_uid())
        resp, _ = await self._done(rec, "s7_iso_ext_in", obs="OBS-SMCRST-ISO-ACCESS")
        self.log.info(
            "OBS-SMCRST-ISO-ACCESS: port=ext_in resp=%s done=%d",
            resp_name(resp) if resp is not None else "-",
            rec["done"],
        )
        st_e, rd_e = await self._j2a_rd(e_addr, "s7_iso_smc_out", obs="OBS-SMCRST-ISO-ACCESS")
        self.log.info(
            "OBS-SMCRST-ISO-ACCESS: port=smc_out resp=j2a%d done=%d",
            st_e,
            int(st_e != J2A_STATUS_BUSY),
        )
        self.log.info("INFO-S7 isolated egress read data=0x%x word=0x%x", rd_e, e_word)
        st_clear = await self._j2a_wr(
            ISO_SMC, ISO_SMC_BM, "s7_latch_clear", wstrb=ISO_SMC_CLEAR_WSTRB
        )
        self.log.info(
            "INFO-LIFECYCLE ISO-LATCH cleared: write 1 to bit 0, wstrb=0x%02x, status=%d",
            ISO_SMC_CLEAR_WSTRB,
            st_clear,
        )
        latch_clear = await self._latch_read("clear")
        sizes = [size for addr, size in self.j2a_sizes if addr == ISO_SMC]
        self.log.info(
            "CTRL-SMCRST-ISO-PRE: flr_edge=@%d flr_counter=%d accesses_issued=2 clear_status=%d "
            "latch_axsizes=%s",
            edge,
            FLR_COUNTER_PAT,
            st_clear,
            sizes,
        )
        self.r["iso"] = {
            "edge": edge > 0,
            "framed": bool(self.selected or "s7" in self.probed),
            "accesses": (rec["issue"] > release, any(a == e_addr for a, _ in self.j2a_sizes)),
            "clear": st_clear,
            "sizes": sizes,
            "latch": (latch_issue, latch_clear),
        }
        self.steps["S7"] = True

    async def _latch_read(self, when: str) -> int | None:
        """ISOLATE_REQ_SMC_REG over an 8-byte framed JTAG2AXI read; OBS-SMCRST-ISO-LATCH is the
        measured record and CHK-SMC-ISO-LATCH-ACCESS grades it."""
        status, rdata = await self._j2a_rd(ISO_SMC, f"s7_latch_{when}", obs="OBS-SMCRST-ISO-LATCH")
        value = rdata & ISO_SMC_REG_MASK if status == J2A_STATUS_SUCCESS else None
        self.log.info(
            "OBS-SMCRST-ISO-LATCH: when=%s path=j2a8 value=%s",
            when,
            "-" if value is None else f"0x{value:x}",
        )
        self.log.info("INFO-S7 latch %s capture status=%d beat=0x%016x", when, status, rdata)
        return value

    def _cool_checks(self) -> None:
        cool = self.r["cool"]
        flr = self.r["flr_post"]

        def key3(post):
            return (post["RESET_VECTOR0"], post["SS_CONFIG"], post["ISOLATE_REQ_REG"])

        rewrite = self.r["rewrite"]
        got = (
            {k: cool[k]["inside"] for k in (1, 2)},
            self.r["flr_inside"],
            {k: rewrite[k] for k in (2, "flr")},
            {k: key3(cool[k]["post"]) for k in (1, 2)},
            key3(flr),
        )
        want3 = ((RESP_OKAY, RV_RESET), (RESP_OKAY, SS_RESET), (RESP_OKAY, ISO_PAT))
        want_rw = ((RESP_OKAY, SS_CONFIG_PAT & SS_MASK), (RESP_OKAY, RV_PAT[0] & RV_MASK))
        # Trial 1 always runs its accesses; trial 2 grades them only with a SEP debug path.
        want_inside = {1: (True, True), 2: (True, True if cool[2]["sep_path"] else NO_SEP_PATH)}
        want = (
            want_inside,
            (True,),
            {k: want_rw for k in (2, "flr")},
            {k: want3 for k in (1, 2)},
            want3,
        )
        self._verdict(
            "CHK-SMC-COOL-TRAFFIC",
            "CHK-SMC-COOL-TRAFFIC: at least one during-hold sba access per trial with a SEP debug "
            "path, each inside reset; held ext_in rd logged; trial-2 and FLR rewrites read back; "
            "pin post RV0=0xC0040000 SS_CONFIG=0x0 ISO=pat; flr post same",
            got,
            want,
        )
        post = cool[1]["post"]
        names = (
            ("SS_CONFIG", SS_RESET),
            ("SS_COLD_RESET_N", SS_COLD_RESET),
            *((f"RESET_VECTOR{i}", RV_RESET) for i in range(4)),
            ("RESET_CTRL", RC_RESET),
            ("WDT_TIMEOUT", WDT_TIMEOUT_RESET),
            ("RESET_TIMEOUT", RT_RESET),
            ("GLOBAL_BASE", GB_RESET),
            ("REGION_SIZE", RS_RESET),
        )
        images_got, images_want = self.r["images"]
        self._verdict(
            "CHK-SMC-PRIMARY-RETAIN",
            "CHK-SMC-PRIMARY-RETAIN: SS 0x0/0x0; RV 4x0xC0040000; RC 0x10F; WDT 0x4000; RT 0x0; "
            "GB 0x40000000; RS 0x1000000",
            (images_got, self.r["images_pre_cool"], {n: post[n] for n, _ in names}),
            (images_want, images_want, {n: (RESP_OKAY, v) for n, v in names}),
        )
        trials = (1, 2, "flr")
        stats = {k: tuple(self.trial_stats.get(k, [0, 0, 0, 0, 0])[:3]) for k in trials}
        samples = sum(s[0] for s in stats.values())
        self.log.info("INFO-S5 trial probe stats (primary0, primary0&warm1, warm0)=%s", stats)
        self._verdict(
            "CHK-SMC-PRIMARY-WARM-EQ",
            f"CHK-SMC-PRIMARY-WARM-EQ: primary0 => warm0 on {samples} samples; 2 pin trials and "
            "the FLR trial",
            {k: (s[0] > 0, s[1], s[2] > 0) for k, s in stats.items()},
            {k: (True, 0, True) for k in trials},
        )
        iso = self.r["iso"]
        latch_issue, latch_clear = iso["latch"]
        self._verdict(
            "CHK-SMC-ISO-LATCH-ACCESS",
            "CHK-SMC-ISO-LATCH-ACCESS: latch=1 at issue; accesses logged; latch=0 after clear "
            "(8-byte, framed)",
            (
                iso["edge"],
                iso["framed"],
                iso["accesses"],
                iso["clear"],
                iso["sizes"],
                (latch_issue, latch_clear),
            ),
            (
                True,
                True,
                (True, True),
                J2A_STATUS_SUCCESS,
                [SMC_DBG_AXSIZE_8B] * 3,
                (ISO_SMC_BM, 0),
            ),
        )

    # ---- S8 SW core ----------------------------------------------------------------------

    async def _sw_core(self) -> None:
        self._enter("SW_CORE", "S8", "per-core hold/release, core reset pulses")
        base = RC_RESET
        for core in range(4):
            await self._wdt_write(core, "CTRL", WDT_COREAWAKE, f"s8_core{core}_ctrl")
        await self._wdt_write(0, "CMP", WDT_CMP_KEPT, "s8_core0_cmp")
        wdt0_before = (
            await self._rd_val(WDT[0]["CTRL"], "s8_core0_ctrl_before") & WDT_CFG_MASK,
            await self._rd_val(WDT[0]["CMP"], "s8_core0_cmp_before") & WDT_CMP_MASK,
            await self._rd_val(WDT[0]["COUNT"], "s8_core0_count_before") & WDT_COUNT_MASK,
        )
        holds = {}
        for core in range(4):
            await self._wr_ok(RESET_CTRL, base & ~CORE_BM[core], f"s8_core{core}_hold", 8)
            h1 = await self._rd_val(WDT[core]["COUNT"], f"s8_core{core}_held1")
            await ClockCycles(self.dut.obs_smc_clk_o, COUNT_GAP_SMC)
            h2 = await self._rd_val(WDT[core]["COUNT"], f"s8_core{core}_held2")
            await self._wr_ok(RESET_CTRL, base, f"s8_core{core}_release", 8)
            r1 = await self._rd_val(WDT[core]["COUNT"], f"s8_core{core}_run1")
            await ClockCycles(self.dut.obs_smc_clk_o, COUNT_GAP_SMC)
            r2 = await self._rd_val(WDT[core]["COUNT"], f"s8_core{core}_run2")
            holds[core] = tuple(v & WDT_COUNT_MASK for v in (h1, h2, r1, r2))
        wdt0_after = (
            await self._rd_val(WDT[0]["CTRL"], "s8_core0_ctrl_after") & WDT_CFG_MASK,
            await self._rd_val(WDT[0]["CMP"], "s8_core0_cmp_after") & WDT_CMP_MASK,
            await self._rd_val(WDT[0]["COUNT"], "s8_core0_count_after") & WDT_COUNT_MASK,
        )
        self.log.info("INFO-S8 counts (held1, held2, run1, run2)=%s", holds)
        self.log.info("INFO-S8 CORE0 wdt before=%s after=%s", wdt0_before, wdt0_after)

        async def done_bits() -> int:
            return (await self._rd_val(PULSE, "s8_pulse_poll", 8) >> DONE_BP) & DONE_MASK

        at_reset = await done_bits()
        self.pulse_low = 0
        await self._wr_ok(RESET_CTRL, base | PULSE0_BM, "s8_pulse_default", 8)
        default_done, _ = await self._poll(
            "s8_pulse_default", done_bits, lambda v: v == DONE_MASK, PULSE_POLLS
        )
        default_low, self.pulse_low = self.pulse_low, None
        await self._wr_ok(RESET_CTRL, base, "s8_pulse_default_clear", 8)
        await self._wr_ok(
            PULSE, (PULSE_POST << POST_BP) | (PULSE_PRE << PRE_BP), "s8_pulse_program", 8
        )
        self.pulse_low = 0
        await self._wr_ok(RESET_CTRL, base | PULSE0_BM, "s8_pulse_programmed", 8)
        prog_done, seen = await self._poll(
            "s8_pulse_programmed", done_bits, lambda v: v == DONE_MASK, PULSE_POLLS
        )
        prog_low, self.pulse_low = self.pulse_low, None
        await self._wr_ok(RESET_CTRL, base, "s8_pulse_programmed_clear", 8)
        low_seen = any(not v & 1 for v in seen)
        self.log.info(
            "INFO-S8 core_resets_done at reset=0x%x default=0x%x programmed polls=%s",
            at_reset,
            default_done,
            [hex(v) for v in seen],
        )
        self.log.info(
            "CTRL-SMCRST-PULSE-LOW: core_resets_done[0] low at the tap for default=%d clk_smc "
            "(RDL counts give %d) programmed=%d clk_smc (programmed counts give %d)",
            default_low,
            PULSE_DEFAULT_LOW,
            prog_low,
            PULSE_PRE + 1 + PULSE_POST + 1,
        )
        self._verdict(
            "CHK-SMC-SW-CORE",
            "CHK-SMC-SW-CORE: 4/4 cores hold/release; resets_done 0xF, low seen (programmed); "
            "default pulse low at the tap; core0 wdt kept",
            (
                {c: (h[1] == h[0], h[3] > h[2]) for c, h in holds.items()},
                (at_reset, default_done, prog_done, low_seen, default_low > 0),
                (
                    wdt0_before[:2],
                    wdt0_after[:2],
                    holds[0][0] >= wdt0_before[2] > 0,
                    holds[0][2] >= holds[0][1],
                ),
            ),
            (
                {c: (True, True) for c in range(4)},
                (DONE_RESET, DONE_MASK, DONE_MASK, True, True),
                ((WDT_COREAWAKE, WDT_CMP_KEPT), (WDT_COREAWAKE, WDT_CMP_KEPT), True, True),
            ),
        )
        self.steps["S8"] = True

    # ---- S9 SW uncore --------------------------------------------------------------------

    async def _rt_ext(self, label: str) -> tuple[int, int]:
        value = await self._rd_val(RESET_TIMEOUT, label, 8)
        return (value >> RT_TIMEOUT_BP) & 1, (value >> RT_APPLIED_BP) & 1

    async def _rt_ext_graded(self, label: str) -> tuple[int, int]:
        """RESET_TIMEOUT over ext_in inside a graded wait: a missing or failed response returns
        (-1, -1) and the poll goes on to its bound."""
        resp, value = await self._rd(RESET_TIMEOUT, label, 8)
        if resp != RESP_OKAY or value is None:
            return -1, -1
        return (value >> RT_TIMEOUT_BP) & 1, (value >> RT_APPLIED_BP) & 1

    @contextlib.contextmanager
    def _graded(self):
        """Waits inside the block are graded: an expiry is recorded and fails the checker that
        reads the result, it never aborts the leaf."""
        outer, self.soft = self.soft, True
        try:
            yield
        finally:
            self.soft = outer

    def _log_undrained(self, when: str) -> int:
        """CTRL-SMCRST-UNDRAINED from the smc_in R handshakes since the train was issued."""
        t = self.train
        smc_r = self.smc_in_r - t["smc_mark"]
        ext_r = self.ext_in_r - t["ext_mark"]
        undrained = int(smc_r < TRAIN)
        self.log.info(
            "CTRL-SMCRST-UNDRAINED: mode=0 issued=%d smc_in_r=%d ext_in_r=%d undrained=%d (%s)",
            TRAIN,
            smc_r,
            ext_r,
            undrained,
            when,
        )
        self.undrained_lines += 1
        t[when] = (smc_r, undrained)
        return undrained

    async def _held_trial(self, base: int, held: int) -> dict:
        """Mode 0, timeout 0x100, every access over ext_in. The uncore request goes on the write
        channels while the 24-read train is held by RREADY low; no read is issued while held."""
        await self._wr_ok(RESET_TIMEOUT, RT_MODE0, "s9_m0_cfg", 8)
        self._r_pause(True)
        mark = self.cyc
        self.train = {"smc_mark": self.smc_in_r, "ext_mark": self.ext_in_r}
        self.r_xz = 0
        recs = [
            self._start(write=False, addr=self._g(WDT[0]["COUNT"]), ident=self._next_uid())
            for _ in range(TRAIN)
        ]
        with self._within("OBS-SMCRST-UNCORE-TRAIN"):
            got = await self._wait_hs("ar", [rec["id"] for rec in recs], mark, "s9_m0_train_ar")
        with self._graded():
            req = await self._wr(RESET_CTRL, held, "s9_m0_req", 8)
        undrained = self._log_undrained("request")
        self._log_undrained("release")
        self._r_pause(False)
        with self._within("OBS-SMCRST-UNCORE-TRAIN"):
            for i, rec in enumerate(recs):
                await self._done(rec, f"s9_m0_train{i}")
        answered = sum(rec["done"] for rec in recs)
        lost = [f"0x{rec['id']:x}" for rec in recs if not rec["done"]]
        with self._graded():
            applied, seen = await self._poll(
                "s9_m0_applied", lambda: self._rt_ext_graded("s9_m0_rt"), lambda v: v[1] == 1
            )
            rel = await self._wr(RESET_CTRL, base, "s9_m0_rel", 8)
            resp, rc = await self._rd(RESET_CTRL, "s9_m0_rel_readback", 8)
            released, rel_seen = await self._poll(
                "s9_m0_released",
                lambda: self._rt_ext_graded("s9_m0_rt_rel"),
                lambda v: v[1] == 0,
            )
        applied_txt = "pending" if applied[1] < 0 else str(applied[1])
        rc_value = rc & RC_MASK if resp == RESP_OKAY and rc is not None else None
        self.log.info(
            "OBS-SMCRST-UNCORE-TRAIN: mode=0 to=256 issued=%d smc_in_r=%d undrained=%d "
            "rt_held=unobservable answered_after_release=%d/%d unanswered_ids=%s "
            "applied_after_release=%s applied_used=%d",
            TRAIN,
            self.train["request"][0],
            undrained,
            answered,
            TRAIN,
            "[" + ",".join(lost) + "]",
            applied_txt,
            len(seen),
        )
        self.obs_train_lines += 1
        self.log.info(
            "INFO-S9 held trial ar_accepted=%d request=%s release write=%s read-back resp=%s "
            "value=%s released=%s polls=%d unresolved R samples=%d",
            len(got),
            resp_name(req) if req is not None else "none",
            resp_name(rel) if rel is not None else "none",
            resp_name(resp) if resp is not None else "none",
            "-" if rc_value is None else f"0x{rc_value:x}",
            released,
            len(rel_seen),
            self.r_xz,
        )
        self.train = None
        return {
            "r_xz": self.r_xz,
            "ar_accepted": len(got),
            "request": req,
            "undrained": undrained,
            "answered": answered,
            "applied": applied_txt,
            "release": (rel, rc_value, released[1]),
        }

    async def _sw_uncore(self) -> None:
        self._enter("SW_UNCORE", "S9", "idle uncore reset, then one held mode-0 trial over ext_in")
        base = RC_RESET
        held = base & ~UNCORE_BM
        await self._wdt_write(0, "CMP", WDT_CMP_KEPT, "s9_core0_cmp")
        wdt_before = (
            await self._rd_val(WDT[0]["CTRL"], "s9_core0_ctrl_before") & WDT_CFG_MASK,
            await self._rd_val(WDT[0]["CMP"], "s9_core0_cmp_before") & WDT_CMP_MASK,
            await self._rd_val(WDT[0]["COUNT"], "s9_core0_count_before") & WDT_COUNT_MASK,
        )
        # Idle, over ext_in (8-byte).
        await self._wr_ok(RESET_CTRL, held, "s9_idle_req", 8)
        idle_on, _ = await self._poll(
            "s9_idle_applied", lambda: self._rt_ext("s9_idle_rt"), lambda v: v[1] == 1
        )
        await self._wr_ok(RESET_CTRL, base, "s9_idle_rel", 8)
        idle_off, _ = await self._poll(
            "s9_idle_released", lambda: self._rt_ext("s9_idle_rt"), lambda v: v[1] == 0
        )
        wdt_after = (
            await self._rd_val(WDT[0]["CTRL"], "s9_core0_ctrl_after") & WDT_CTRL_MASK,
            await self._rd_val(WDT[0]["CMP"], "s9_core0_cmp_after") & WDT_CMP_MASK,
            await self._rd_val(WDT[0]["COUNT"], "s9_core0_count_after") & WDT_COUNT_MASK,
        )
        self.log.info("INFO-S9 CORE0 wdt before=%s after uncore=%s", wdt_before, wdt_after)
        # The mode-1 and timeout-0 held trials are out of this milestone (SF-009).
        trial = await self._held_trial(base, held)
        rc_value, rel_applied = trial["release"][1], trial["release"][2]
        self.log.info("INFO-S9 idle=%s held trial=%s", (idle_on[1], idle_off[1]), trial)
        self._verdict(
            "CHK-SMC-SW-UNCORE",
            f"CHK-SMC-SW-UNCORE: idle applied 1->0; held mode0 ar_accepted="
            f"{trial['ar_accepted']}/{TRAIN} undrained={trial['undrained']} "
            f"(value OBS SF-009); unresolved R samples={trial['r_xz']}; train answered "
            f"{trial['answered']}/{TRAIN} (OBS SF-009); applied={trial['applied']}; release rc="
            f"{'-' if rc_value is None else hex(rc_value)} applied={rel_applied}; wdt cleared",
            (
                (idle_on[1], idle_off[1]),
                trial["ar_accepted"],
                trial["request"],
                trial["undrained"],
                trial["r_xz"],
                trial["applied"],
                (trial["release"][0], rc_value, rel_applied),
                wdt_before[0] == WDT_COREAWAKE and wdt_before[2] > 0,
                wdt_after,
                (self.obs_train_lines, self.undrained_lines),
            ),
            (
                (1, 0),
                TRAIN,
                RESP_OKAY,
                1,
                0,
                "1",
                (RESP_OKAY, base & RC_MASK, 0),
                True,
                (WDT_CTRL_RESET, WDT_CMP_RESET, 0),
                (1, 2),
            ),
        )
        self.steps["S9"] = True

    # ---- S10 and the fence ---------------------------------------------------------------

    def _site_plan(self) -> dict[str, Counter]:
        """Proof-path wait sites per step and kind, from the step list (S10). A counted poll
        is one site; the accesses inside it are poll_access and are not counted. Waits in an
        OBS context are observation windows and are not in this plan."""
        bite_rise = 1 if self.bite_fell else 0
        return {
            # SEP aperture (two 64-bit writes, 4 DMI ops each, two port settles) and the
            # three egress-filter writes (3 DMI ops each); six SMC filter writes over JTAG2AXI.
            "S1": Counter(dmi_retry=17, sba_busy=5, port_settle=2, j2a_capture=6),
            # Eleven images written and read, GLOBAL_BASE written and read.
            "S2": Counter(ext_in=24),
            # wdt2: CMP and CTRL with their keys, two held reads, the read in warm, five post
            # reads, two coreawake writes with keys and four COUNT reads; bite: the same less
            # the arming, the bite and count writes, the CTRL address and the enable write.
            "S3": Counter(
                ext_in=20 + 16,
                handshake=2,
                reset_level=2 + bite_rise,
                dmi_retry=9,
                sba_busy=3,
            ),
            "S4": Counter(ext_in=4, j2a_capture=2),
            # Trial 1: twelve pre-cool image reads; trial 2: two re-writes, their read-backs and
            # the SRAM seed. Per trial: the held AR, the primary fall and rise and the warm rise.
            "S5": Counter(ext_in=12 + 5, handshake=2, reset_level=6),
            # Per trial: six SMC filter writes and twelve reset-value reads.
            "S6": Counter(ext_in=24, j2a_capture=12),
            # Four writes, two read-backs and twelve reads; the held AR; the fall, rise and warm
            # rise; six filter writes and the clearing write of ISOLATE_REQ_SMC_REG.
            "S7": Counter(ext_in=18, handshake=1, reset_level=3, j2a_capture=7),
            # Four coreawake writes and the CMP write with keys, three reads before and after,
            # six accesses per core, the pulse reads and writes; two pulse polls.
            "S8": Counter(ext_in=46, reg_poll=2),
            # CMP with key, three reads before and after, idle request and release; two idle
            # polls; the held trial: RESET_TIMEOUT write, uncore request, release write and
            # RESET_CTRL read-back, the reset_applied 1 and 0 polls. The 24 train reads are
            # OBS-SMCRST-UNCORE-TRAIN windows.
            "S9": Counter(ext_in=10 + 2 + 2, reg_poll=2 + 2),
        }

    async def _finish(self) -> None:
        self._warm_checks()
        self._cool_checks()
        self.step = "S10"
        for rec in self.sites:
            self.log.info(
                "INFO-TIMEOUT-PATH %s %s %s: bound=%d used=%d %s%s last=%s",
                rec["step"],
                rec["kind"],
                rec["label"],
                rec["bound"],
                rec["used"],
                "EXPIRED" if rec["expired"] else "ok",
                " graded" if rec["graded"] else "",
                rec["last"],
            )
        for win in self.windows:
            self.log.info(
                "INFO-OBS-WINDOW obs=%s step=%s label=%s bound=%d used=%d done=%d expired=%d "
                "last=%s",
                win["obs"],
                win["step"],
                win["label"],
                win["bound"],
                win["used"],
                win["done"],
                win["expired"],
                win["last"],
            )
        plan = self._site_plan()
        observed = {
            step: Counter(
                r["kind"] for r in self.sites if r["step"] == step and r["kind"] != "poll_access"
            )
            for step in plan
        }
        mismatched = {
            step: (dict(observed[step]), dict(plan[step]))
            for step in plan
            if observed[step] != plan[step]
        }
        kinds = Counter(r["kind"] for r in self.sites)
        # An expired graded wait of S9 fails CHK-SMC-SW-UNCORE, not this checker.
        expired = sum(r["expired"] for r in self.sites if not r["graded"])
        graded = [r for r in self.sites if r["graded"]]
        graded_expired = sum(r["expired"] for r in graded)
        unbounded = [
            r["label"]
            for r in self.sites
            if not (
                isinstance(r["bound"], int)
                and 0 < r["bound"]
                and (r["graded"] or r["used"] <= r["bound"])
            )
        ]
        unbounded += [
            w["label"] for w in self.windows if not (isinstance(w["bound"], int) and w["bound"] > 0)
        ]
        misbooked = [w["label"] for w in self.windows if w["expired"] != 1 - w["done"]]
        win_names = Counter(w["obs"] for w in self.windows)
        win_expired = Counter(w["obs"] for w in self.windows if w["expired"])
        self.log.info(
            "INFO-SEP debug path re-established after each primary reset: %s",
            self.sep_attached,
        )
        self.log.info(
            "INFO-S10 proof-path wait sites per kind=%s per-step mismatches=%s; observation "
            "windows per OBS=%s expired=%s",
            dict(kinds),
            mismatched,
            dict(win_names),
            dict(win_expired),
        )
        required = sorted(
            (
                "OBS-SMCRST-COOL-INFLIGHT",
                "OBS-SMCRST-UNCORE-TRAIN",
                "OBS-SMCRST-BITE-NO-WARM",
            )
        )
        n_kinds = len([k for k in kinds if k != "poll_access"])
        self._verdict(
            "CHK-TIMEOUT-PATHS",
            f"CHK-TIMEOUT-PATHS: {len(self.sites)} waits in {n_kinds} kinds, none expired "
            f"(bound, used, last state per site); per-step site counts equal the step-list "
            f"plan; every site bounded; {len(self.windows)} observation windows listed "
            f"({sum(win_expired.values())} expired=1); {len(graded)} graded S9 waits listed "
            f"({graded_expired} expired, graded by CHK-SMC-SW-UNCORE)",
            (
                expired,
                mismatched,
                unbounded,
                misbooked,
                sorted(n for n in required if win_names[n]),
                win_names["OBS-SMCRST-BITE-NO-WARM"],
                sorted({r["step"] for r in graded}),
            ),
            (0, {}, [], [], required, 1, ["S9"]),
        )
        await ClockCycles(self.dut.clk_smu_i, FENCE_GAP)
        stamps = [(t, self.terms.get(t, [None, 0])) for t in FENCE]
        pass_ns = self._now()
        fence = " < ".join(
            f"{t}@{v[0]:.1f}ns(n={v[1]})" if v[0] is not None else f"{t}@missing" for t, v in stamps
        )
        self.log.info(
            "INFO-CHK-NONVAC fence %s < PASS@%.1fns warm_sources=%d cool_trials=%d",
            fence,
            pass_ns,
            self.warm_sources,
            self.cool_trials,
        )
        times = [v[0] for _, v in stamps]
        ordered = all(t is not None for t in times) and all(
            b > a for a, b in zip(times, times[1:] + [pass_ns])
        )
        self._verdict(
            "CHK-NONVAC",
            "CHK-NONVAC: SETUP < IMAGES < WARM < WARM_POST < COOL < COOL_POST < FLR < SW_CORE < "
            "SW_UNCORE < PASS (sim time and count per term)",
            (
                ordered,
                all(v[1] > 0 for _, v in stamps),
                (self.warm_sources, self.cool_trials),
                all(self.steps.get(f"S{i}", False) for i in range(1, 10)),
            ),
            (True, True, (2, 2), True),
        )
        if self.failures:
            raise AssertionError(f"{len(self.failures)} checker compare(s) failed: {self.failures}")
        self.done = True

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        assert self.s1_ok and self.s2_ok and self.s3_ok, "SEP debug bring-up incomplete"
        tap = cocotb.start_soon(self._tap())
        smc_clock = cocotb.start_soon(self._smc_clock())
        try:
            await self._s1_setup()
            await self._s2_images()
            await self._warm("wdt2")
            await self._warm("bite")
            await self._warm_post()
            await self._cool_trial(1)
            await self._cool_trial(2)
            await self._flr()
            await self._sw_core()
            await self._sw_uncore()
            self.steps["S10"] = True
            await self._finish()
        finally:
            tap.cancel()
            smc_clock.cancel()
