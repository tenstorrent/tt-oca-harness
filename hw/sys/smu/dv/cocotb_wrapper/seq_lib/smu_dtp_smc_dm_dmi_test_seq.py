# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC debug module through the SMC STAP: reset release, capability read-backs, system bus.

The primary TAP selects the SMC STAP through TAP_3DCR. The SMC cluster's debug transport module
(RISC-V External Debug Support 0.13) answers on its 5-bit instruction register: dtmcs gives abits,
which sizes every dmi scan. CPU_CTRL RESET_CTRL holds the debug module in reset (bit 24, active
low); the dmi answers while it is held are measured and logged only. The fabric SINGLE_OP write of
the RESET_CTRL word with bit 24 set releases it, after which dmcontrol.dmactive, the dmstatus and
sbcs capability fields and a debug system-bus write and read of CPU_CTRL SCRATCH[15] are compared.
A fabric write of SCRATCH[14] before the system-bus sequence is read back over the system bus, and
the DTP-to-SMC launch counters stay flat across the system-bus traffic.

Sources: hw/sys/smc/doc/cpu.adoc (Debug Module Configuration, SMC Debug Module capability
readbacks), hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (RESET_CTRL, SCRATCH),
hw/sys/smc/regs/gen/c/smc_addr.h, hw/ip/jtag/jtag_stap/doc/architecture.adoc,
hw/ip/jtag/jtag_ptap/doc/architecture.adoc, hw/sys/dtp/doc/jtag.adoc and
doc/integrator/src/smu-composition.adoc.
"""

from __future__ import annotations

from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_boundary_regs import (
    SMU_SEP_STAP_ORDER,
    ptap_prefixed,
    stap_3dcr_scan_word,
    stap_sib_pattern,
)
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMCONTROL_ADDR,
    DMCONTROL_DMACTIVE,
    DMI_IDLE_TCKS,
    DMI_OP_NOP,
    DMI_OP_READ,
    DMI_OP_WRITE,
    DMI_STATUS_OK,
    DMSTATUS_ADDR,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    DMI_STATUS_BUSY,
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
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_IDCODE,
    DTP_IR_SMC_AXI_SINGLE_OP,
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    PTAP_3DCR_WIDTH,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SINGLE_OP_LEN,
    make_smu_jtag_tap,
    pack_single_op,
    ptap_3dcr_value,
    require_jtag_tdo_resolved,
    unpack_single_op,
)

# hw/sys/smc/regs/gen/c/smc_addr.h: CPU_CTRL RESET_CTRL (0xC0039020) and the 8-byte SCRATCH
# stride from 0xC0039080; SCRATCH[14] is 0xC00390F0 and SCRATCH[15] is 0xC00390F8.
RESET_CTRL_ADDR = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
_SCRATCH = "SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR"
SCRATCH_Y_ADDR = smc_indexed_addr(_SCRATCH, 14)
SCRATCH_X_ADDR = smc_indexed_addr(_SCRATCH, 15)
# Non-zero words for the two SCRATCH registers (reset 0 in
# hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl).
SCRATCH_X = 0x5BA0_F15E
SCRATCH_Y = 0x0ECC_A114
SCRATCH_WORD_MASK = 0xFFFF_FFFF
# hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl, RESET_CTRL: core reset_n bits 3:0 reset 0x1 each,
# uncore_reset_n bit 8 reset 1, debug_reset_n bit 24 reset 0 (active low, 1 releases).
RESET_CORES_MASK = 0xF
RESET_UNCORE_BIT = 8
RESET_DEBUG_BIT = 24
RESET_DEBUG_HELD = 0
RESET_DEBUG_RELEASED = 1
RESET_LOW_BITS_MASK = (1 << (RESET_UNCORE_BIT + 1)) - 1
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SINGLE_OP wstrb: eight lanes for a 64-bit
# beat, four for a 32-bit word on the low lane.
WSTRB_FULL = 0xFF
WSTRB_WORD = 0x0F
FABRIC_OP_OKAY = J2A_STATUS_SUCCESS

# hw/sys/smc/doc/cpu.adoc, Debug Module Configuration: RISC-V External Debug Support 0.13. The
# debug transport module has a 5-bit instruction register, dtmcs 0x10 and dmi 0x11; dtmcs carries
# version[3:0], abits[9:4], dmistat[11:10] and idle[14:12], and dmireset at bit 16; a dmi scan is
# abits + 34 data and op bits long, address above the data.
SMC_TAP_IR_WIDTH = 5
SMC_TAP_IR_DTMCS = 0x10
SMC_TAP_IR_DMI = 0x11
DTMCS_WIDTH = 32
DTMCS_ABITS_LSB = 4
DTMCS_ABITS_MASK = 0x3F
DTMCS_IDLE_LSB = 12
DTMCS_IDLE_MASK = 0x7
DTMCS_DMIRESET = 1 << 16
DMI_DATA_OP_BITS = 34
DMI_ADDR_SHIFT = 34
SBADDRESS1_ADDR = 0x3A
# RISC-V External Debug Support 0.13, dmstatus: version[3:0], confstrptrvalid bit 4,
# hasresethaltreq bit 5, authenticated bit 7, impebreak bit 22; the values are the table
# "SMC Debug Module capability readbacks" of hw/sys/smc/doc/cpu.adoc.
DMSTATUS_VERSION_MASK = 0xF
DMSTATUS_CONFSTRPTRVALID_BIT = 4
DMSTATUS_HASRESETHALTREQ_BIT = 5
DMSTATUS_AUTHENTICATED_BIT = 7
DMSTATUS_IMPEBREAK_BIT = 22
DMSTATUS_VERSION_SPEC_0_13 = 2
DMSTATUS_CONFSTRPTRVALID = 0
DMSTATUS_HASRESETHALTREQ = 1
DMSTATUS_AUTHENTICATED = 1
DMSTATUS_IMPEBREAK = 1
# sbcs: sbversion[31:29], sbasize[11:5], sbaccess128 bit 4 down to sbaccess8 bit 0.
SBCS_SBVERSION_LSB = 29
SBCS_SBVERSION_MASK = 0x7
SBCS_SBASIZE_LSB = 5
SBCS_SBASIZE_MASK = 0x7F
SBCS_SBACCESS8_BIT = 0
SBCS_SBACCESS16_BIT = 1
SBCS_SBACCESS32_BIT = 2
SBCS_SBACCESS64_BIT = 3
SBCS_SBACCESS128_BIT = 4
SBCS_SBVERSION = 1
SBCS_SBASIZE = 56
SBCS_SBACCESS_SUPPORTED = 1
SBCS_SBACCESS128 = 0
SBCS_SBACCESS_BITS = (
    SBCS_SBACCESS8_BIT,
    SBCS_SBACCESS16_BIT,
    SBCS_SBACCESS32_BIT,
    SBCS_SBACCESS64_BIT,
)

# hw/ip/jtag/jtag_stap/doc/architecture.adoc and doc/integrator/src/smu-composition.adoc: the
# chain carries one SIB flop per STAP in the order io, smc, sep, extra0; a selected STAP splices
# its host TAP's register TDI-side of its own SIB.
SMC_STAP_NAME = "smc"
SIBS_BEFORE_SMC = SMU_SEP_STAP_ORDER.index(SMC_STAP_NAME)
SIBS_FROM_SMC = len(SMU_SEP_STAP_ORDER) - SIBS_BEFORE_SMC
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, 3DCR: config hold 0 lets Test-Logic-Reset clear
# the select bit.
CONFIG_HOLD_CLEAR = 0
PTAP_3DCR_SELECT = 1

# Bounds and windows.
GATE_POLL_LIMIT = 400
GATE_POLL_CLK = 50
CAPTURE_POLL_LIMIT = 8
CAPTURE_POLL_CLK = 16
DMI_RETRY_LIMIT = 16
SBA_POLL_LIMIT = 16

# Wait sites per kind: the gate wait; the five fabric SINGLE_OP capture polls (RESET_CTRL read,
# release write and read-back, SCRATCH[14] write, SCRATCH[15] read); sixteen dmi access retry loops
# (held three, dmactive two, capability two, system-bus write four, system-bus reads five); three
# sbbusy polls (write one, reads two).
EXPECTED_SITE_KINDS = {"gate": 1, "op_capture": 5, "dmi_retry": 16, "sba_busy": 3}
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
SCANNED_STEPS = STEPS[:-1]
FENCE_CYCLES = 2
CHECK_ORDER = (
    "CHK-DBG-SMC-DM-SETUP",
    "CHK-DBG-SMC-DM-RESET-HELD",
    "CHK-DBG-SMC-DM-RELEASE",
    "CHK-DBG-SMC-DM-DMACTIVE",
    "CHK-DBG-SMC-DM-DMSTATUS",
    "CHK-DBG-SMC-DM-SBCS",
    "CHK-DBG-SMC-DM-SBA-WRITE",
    "CHK-DBG-SMC-DM-SBA-READ",
    "CHK-DBG-SMC-DM-SBA-PATH",
)
SMC_STAP_TMS = "tb_stap_smc_tms"
SMC_STAP_TCK = "tb_stap_smc_tck"
SMC_STAP_TDO_OEN = "tb_stap_smc_tdo_oen"
PTAP_TMS = "jtag_tms"


def _lane_word(rdata: int, addr: int) -> int:
    """The 32-bit word a size-2 read returns on the lane its address selects."""
    return ((rdata >> 32) if addr & 0x4 else rdata) & SCRATCH_WORD_MASK


def _bit(word: int, bit: int) -> int:
    return (word >> bit) & 1


def _field(word: int, lsb: int, mask: int) -> int:
    return (word >> lsb) & mask


class smu_dtp_smc_dm_dmi_test_seq:
    """SMC debug module reset release, capability read-backs and system-bus access."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.selected = False
        self.ir_key: tuple[bool, int, int] | None = None
        self.scans = 0
        self.polls = 0
        self.abits = 0
        self.idle = DMI_IDLE_TCKS
        self.step_ns: dict[str, float] = {}
        self.step_scans: dict[str, int] = {}
        self.sites: list[dict] = []
        self.checks: dict[str, tuple[str, list[tuple[str, object, object]]]] = {}
        self.r: dict[str, object] = {}
        self.monitor_stop = False
        self.done = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _now(self) -> float:
        return float(get_sim_time(unit="ns"))

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.dut.clk_smu_i)
        self.step_ns[step] = self._now()
        self.step_scans[step] = self.scans
        self._log(f"STEP {step} @{self.step_ns[step]:.3f}ns scans={self.scans}: {text}")

    def _site(
        self, kind: str, label: str, bound: int, unit: str, used: int, last: str, expired: bool
    ) -> None:
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "unit": unit,
                "used": used,
                "last": last,
                "expired": int(expired),
            }
        )
        if expired:
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={bound} {unit} used={used} last_state={last}"
            )

    def _check(self, chk: str, proof: str, legs: list[tuple[str, object, object]]) -> None:
        """Queue the compares of one checker; the proof line and the compares run in step order."""
        self.checks[chk] = (proof, legs)

    def _pin(self, name: str) -> int:
        return sample(getattr(self.dut, name), name)

    def _counts(self) -> tuple[int, int, int]:
        return (
            self._pin("dtp_smc_dbg_aw_count_o"),
            self._pin("dtp_smc_dbg_ar_count_o"),
            self._pin("dtp_smc_dbg_b_count_o"),
        )

    @staticmethod
    def _delta(now: tuple[int, int, int], base: tuple[int, int, int]) -> tuple[int, int, int]:
        return tuple((n - b) & 0xFFFF_FFFF for n, b in zip(now, base))

    # ---- network scans -----------------------------------------------------------------------

    def _network_scan(
        self, ptap_reg: int, ptap_width: int, smc_reg: int, smc_width: int
    ) -> tuple[int, int]:
        """A scan with the SMC STAP selected and every SIB closed, TDI-nearest segment first."""
        width = ptap_width + SIBS_BEFORE_SMC + smc_width + SIBS_FROM_SMC
        value = int(ptap_reg) << (SIBS_BEFORE_SMC + smc_width + SIBS_FROM_SMC)
        value |= int(smc_reg) << SIBS_FROM_SMC
        return value, width

    def _dmi_request(self, addr: int, data: int, op: int) -> int:
        return (
            ((int(addr) & ((1 << self.abits) - 1)) << DMI_ADDR_SHIFT)
            | ((int(data) & 0xFFFF_FFFF) << 2)
            | (int(op) & 0x3)
        )

    def _unpack_dmi(self, raw: int) -> tuple[int, int]:
        return (int(raw) >> 2) & 0xFFFF_FFFF, int(raw) & 0x3

    def _smc_width(self, smc_ir: int) -> int:
        return DTMCS_WIDTH if smc_ir == SMC_TAP_IR_DTMCS else self.abits + DMI_DATA_OP_BITS

    async def _ir(self, opcode: int, smc_ir: int, label: str) -> None:
        key = (self.selected, opcode, smc_ir if self.selected else 0)
        if self.ir_key == key:
            return
        if self.selected:
            value, width = self._network_scan(opcode, DTP_IR_WIDTH, smc_ir, SMC_TAP_IR_WIDTH)
        else:
            value, width = opcode, DTP_IR_WIDTH
        captured = await self.jtag.shift_ir(value, width=width, back_to_rti=True)
        require_jtag_tdo_resolved(f"IR {label}")
        self.ir_key = key
        self._log(f"SCAN IR {label} w={width} in=0x{value:x} out=0x{captured:x}")

    async def _dr(
        self,
        opcode: int,
        value: int,
        width: int,
        label: str,
        *,
        counted: bool = True,
        smc_ir: int = SMC_TAP_IR_DMI,
        smc_reg: int = 0,
        idle: int = 0,
    ) -> tuple[int, int]:
        """Scan one PTAP register; returns (its capture, the SMC TAP register capture or 0)."""
        await self._ir(opcode, smc_ir, label)
        if self.selected:
            smc_width = self._smc_width(smc_ir)
            word, total = self._network_scan(value, width, smc_reg, smc_width)
            raw = await self.jtag.shift_dr(word, total, back_to_rti=True)
            shift = SIBS_BEFORE_SMC + smc_width + SIBS_FROM_SMC
            captured = (raw >> shift) & ((1 << width) - 1)
            smc = (raw >> SIBS_FROM_SMC) & ((1 << smc_width) - 1)
        else:
            total = width
            raw = await self.jtag.shift_dr(value, width, back_to_rti=True)
            captured, smc = raw, 0
        require_jtag_tdo_resolved(f"DR {label}")
        for _ in range(idle):
            await self.jtag.step_tms(0)
        if counted:
            self.scans += 1
            tag = f"SCAN {self.scans}"
        else:
            self.polls += 1
            tag = f"POLL {self.polls}"
        self._log(
            f"{tag} DR {label} w={total} in=0x{value:x} out=0x{captured:x} "
            f"smc_in=0x{smc_reg:x} smc_out=0x{smc:x}"
        )
        return captured, smc

    async def _select_smc_stap(self) -> None:
        jtag = self.jtag
        await jtag.shift_ir(DTP_IR_TAP_3DCR, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(
            ptap_3dcr_value(config_hold=CONFIG_HOLD_CLEAR, select=PTAP_3DCR_SELECT),
            PTAP_3DCR_WIDTH,
            back_to_rti=True,
        )
        await jtag.step_tms(0)
        await jtag.step_tms(0)
        sib = stap_sib_pattern(SMC_STAP_NAME, 1)
        sib_word, sib_width = ptap_prefixed(
            sib, len(SMU_SEP_STAP_ORDER), config_hold=CONFIG_HOLD_CLEAR
        )
        await jtag.shift_dr(sib_word, sib_width, back_to_rti=True)
        stap_word, stap_width = stap_3dcr_scan_word(
            SMC_STAP_NAME, config_hold=CONFIG_HOLD_CLEAR, stap_sel=1, tms_hold=1, sib_en=0
        )
        value, width = ptap_prefixed(stap_word, stap_width, config_hold=CONFIG_HOLD_CLEAR)
        await jtag.shift_dr(value, width, back_to_rti=True)
        await jtag.step_tms(0)
        await jtag.step_tms(0)
        self.selected = True
        self.ir_key = None
        self.scans += 3
        self._log(
            f"SCAN SMC STAP selected through TAP_3DCR sib=0x{sib:x} 3dcr=0x{stap_word:x} "
            f"order={SMU_SEP_STAP_ORDER}"
        )

    # ---- TMS observation ---------------------------------------------------------------------

    def _start_monitor(self):
        self.monitor_stop = False
        return cocotb.start_soon(self._observe_tms())

    async def _stop_monitor(self, task) -> dict[str, int]:
        self.monitor_stop = True
        return await task

    async def _observe_tms(self) -> dict[str, int]:
        """TMS edges of the primary TAP and the SMC STAP, TMS mismatches and tdo_oen TCKs."""
        prev_tck = self._pin(SMC_STAP_TCK)
        prev_ptap = self._pin(PTAP_TMS)
        prev_smc = self._pin(SMC_STAP_TMS)
        out = {"ptap_edges": 0, "smc_edges": 0, "mismatch": 0, "oen_tcks": 0}
        while not self.monitor_stop:
            await RisingEdge(self.dut.clk_ref_i)
            tck = self._pin(SMC_STAP_TCK)
            ptap = self._pin(PTAP_TMS)
            smc = self._pin(SMC_STAP_TMS)
            out["ptap_edges"] += ptap != prev_ptap
            out["smc_edges"] += smc != prev_smc
            if tck == 1 and prev_tck == 0:
                out["mismatch"] += smc != ptap
                out["oen_tcks"] += self._pin(SMC_STAP_TDO_OEN)
            prev_tck, prev_ptap, prev_smc = tck, ptap, smc
        return out

    # ---- fabric access -----------------------------------------------------------------------

    async def _fabric(
        self, op: int, addr: int, data: int, size: int, label: str
    ) -> tuple[int, int, tuple[int, int, int]]:
        """SMC fabric SINGLE_OP; captures until op leaves busy, bounded; one wait site."""
        wstrb = (
            (WSTRB_FULL if size == SMC_DBG_AXSIZE_8B else WSTRB_WORD) if op == J2A_OP_WRITE else 0
        )
        base = self._counts()
        raw = pack_single_op(op, addr, data, wstrb=wstrb, size=size)
        await self._dr(DTP_IR_SMC_AXI_SINGLE_OP, raw, SMC_DBG_SINGLE_OP_LEN, f"{label}_issue")
        used = 0
        while True:
            captured, _ = await self._dr(
                DTP_IR_SMC_AXI_SINGLE_OP,
                0,
                SMC_DBG_SINGLE_OP_LEN,
                f"{label}_c{used}",
                counted=used == 0,
            )
            status, rdata = unpack_single_op(captured)
            used += 1
            if status != J2A_STATUS_BUSY:
                break
            if used >= CAPTURE_POLL_LIMIT:
                self._site(
                    "op_capture",
                    label,
                    CAPTURE_POLL_LIMIT,
                    "captures",
                    used,
                    f"op={status}",
                    True,
                )
            await ClockCycles(self.dut.clk_smu_i, CAPTURE_POLL_CLK)
        self._site("op_capture", label, CAPTURE_POLL_LIMIT, "captures", used, f"op={status}", False)
        deltas = self._delta(self._counts(), base)
        self._log(f"CELL {label} op={status} data=0x{rdata:016x} aw/ar/b delta={deltas}")
        return status, rdata, deltas

    # ---- debug transport module --------------------------------------------------------------

    async def _dmireset(self, label: str) -> int:
        """Clear a sticky dmi status through dtmcs.dmireset; returns the dtmcs capture."""
        _, dtmcs = await self._dr(
            DTP_IR_TAP_3DCR,
            ptap_3dcr_value(config_hold=CONFIG_HOLD_CLEAR, select=PTAP_3DCR_SELECT),
            PTAP_3DCR_WIDTH,
            f"dmireset_{label}",
            smc_ir=SMC_TAP_IR_DTMCS,
            smc_reg=DTMCS_DMIRESET,
        )
        return dtmcs

    async def _dmi_op(
        self, addr: int, data: int, op: int, label: str, *, record: bool = True, measure=False
    ) -> tuple[int, int]:
        """One dmi access; busy status clears with dmireset and more idle TCKs, then retries."""
        ptap = ptap_3dcr_value(config_hold=CONFIG_HOLD_CLEAR, select=PTAP_3DCR_SELECT)
        extra = 0
        used = 0
        while True:
            await self._dr(
                DTP_IR_TAP_3DCR,
                ptap,
                PTAP_3DCR_WIDTH,
                f"dmi_{label}_req{used}",
                smc_reg=self._dmi_request(addr, data, op),
                idle=self.idle + extra,
            )
            _, captured = await self._dr(
                DTP_IR_TAP_3DCR,
                ptap,
                PTAP_3DCR_WIDTH,
                f"dmi_{label}_c{used}",
                counted=False,
                smc_reg=self._dmi_request(addr, 0, DMI_OP_NOP),
                idle=self.idle + extra,
            )
            used += 1
            value, status = self._unpack_dmi(captured)
            if status != DMI_STATUS_BUSY:
                break
            if used >= DMI_RETRY_LIMIT:
                self._site(
                    "dmi_retry", label, DMI_RETRY_LIMIT, "retries", used, f"status={status}", True
                )
            await self._dmireset(f"{label}_busy{used}")
            extra += DMI_IDLE_TCKS
        self._log(f"CELL dmi {label} status={status} data=0x{value:08x} retries={used - 1}")
        if status != DMI_STATUS_OK:
            if not measure:
                raise AssertionError(f"dmi {label} addr=0x{addr:02x} status={status}")
            await self._dmireset(f"{label}_status{status}")
        if record:
            self._site(
                "dmi_retry", label, DMI_RETRY_LIMIT, "retries", used, f"status={status}", False
            )
        return value, status

    async def _dmi(self, addr: int, data: int, op: int, label: str, **kw) -> int:
        value, _ = await self._dmi_op(addr, data, op, label, **kw)
        return value

    async def _sba_wait(self, label: str) -> int:
        """Poll sbcs until sbbusy reads 0, bounded; returns the final sbcs."""
        used = 0
        while True:
            sbcs = await self._dmi(SBCS_ADDR, 0, DMI_OP_READ, f"{label}_sbcs{used}", record=False)
            used += 1
            if used == 1:
                self._log(
                    f"OBSERVATION {label} sbbusy on the first poll measured={_bit(sbcs, 21)} "
                    "measured and logged only"
                )
            if not sbcs & SBCS_SBBUSY:
                break
            if used >= SBA_POLL_LIMIT:
                self._site(
                    "sba_busy", label, SBA_POLL_LIMIT, "polls", used, f"sbcs=0x{sbcs:08x}", True
                )
        self._site("sba_busy", label, SBA_POLL_LIMIT, "polls", used, f"sbcs=0x{sbcs:08x}", False)
        return sbcs

    @staticmethod
    def _sba_status(sbcs: int) -> tuple[int, int, int]:
        """(sbbusy, sberror, sbbusyerror) of an sbcs word."""
        return (
            _bit(sbcs, 21),
            (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK,
            1 if sbcs & SBCS_SBBUSYERROR else 0,
        )

    async def _sba_write(self, addr: int, data: int, label: str) -> int:
        await self._dmi(
            SBCS_ADDR, SBCS_SBACCESS_32 | SBCS_SBERROR_W1C, DMI_OP_WRITE, f"{label}_sbcs"
        )
        await self._dmi(SBADDRESS1_ADDR, addr >> 32, DMI_OP_WRITE, f"{label}_addr1")
        await self._dmi(SBADDRESS0_ADDR, addr & 0xFFFF_FFFF, DMI_OP_WRITE, f"{label}_addr0")
        await self._dmi(SBDATA0_ADDR, data, DMI_OP_WRITE, f"{label}_data")
        return await self._sba_wait(label)

    # ---- run ---------------------------------------------------------------------------------

    async def run(self) -> None:
        await self._setup()
        await self._reset_held_bit()
        await self._select()
        await self._dtm_control()
        await self._dmi_while_held()
        await self._release()
        await self._dmactive()
        await self._capabilities()
        await self._system_bus_write()
        await self._system_bus_read()
        await self._finish()

    async def _setup(self) -> None:
        await self._mark("S1", "TAP reset, IDCODE, gate, launch counter baselines")
        self.jtag = jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        self._log(f"OBSERVATION jtag_period_ns={self.cfg.jtag_period_ns} measured and logged only")
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        self.scans += 1
        id0 = await jtag.read_idcode()
        require_jtag_tdo_resolved("IDCODE")
        self._log(f"SCAN {self.scans} DR IDCODE out=0x{id0:08x}")
        gate = self.dut.tb_smc_jtag2axi_security_disable
        used = 0
        while True:
            val = gate.value
            if val.is_resolvable and int(val) == 0:
                break
            if used >= GATE_POLL_LIMIT:
                self._site(
                    "gate", "security_disable", GATE_POLL_LIMIT, "polls", used, f"{val}", True
                )
            used += 1
            await ClockCycles(self.dut.clk_smu_i, GATE_POLL_CLK)
        self._site("gate", "security_disable", GATE_POLL_LIMIT, "polls", used, str(val), False)
        base = self._counts()
        self.r["id0"] = id0
        self.r["gate"] = (int(gate.value), used)
        self.r["base"] = base
        self._log(f"OBSERVATION launch counter baselines aw/ar/b={base} measured and logged only")

    async def _reset_held_bit(self) -> None:
        await self._mark("S2", "RESET_CTRL read at its reset value")
        task = self._start_monitor()
        status, rdata, deltas = await self._fabric(
            J2A_OP_READ, RESET_CTRL_ADDR, 0, SMC_DBG_AXSIZE_8B, "reset_ctrl_rd0"
        )
        self.r["unsel"] = await self._stop_monitor(task)
        self.r["d0"] = rdata
        self.r["held_read"] = (status, deltas)

    async def _select(self) -> None:
        await self._mark("S3", "SMC STAP selected through TAP_3DCR")
        await self._select_smc_stap()

    async def _dtm_control(self) -> None:
        await self._mark("S4", "dtmcs scan, abits and idle")
        task = self._start_monitor()
        _, dtmcs = await self._dr(
            DTP_IR_TAP_3DCR,
            ptap_3dcr_value(config_hold=CONFIG_HOLD_CLEAR, select=PTAP_3DCR_SELECT),
            PTAP_3DCR_WIDTH,
            "dtmcs",
            smc_ir=SMC_TAP_IR_DTMCS,
        )
        self.r["sel"] = await self._stop_monitor(task)
        self.abits = _field(dtmcs, DTMCS_ABITS_LSB, DTMCS_ABITS_MASK)
        dtm_idle = _field(dtmcs, DTMCS_IDLE_LSB, DTMCS_IDLE_MASK)
        self.idle = DMI_IDLE_TCKS + dtm_idle
        self.r["dtmcs"] = dtmcs
        sel = self.r["sel"]
        self._log(
            f"OBSERVATION dtmcs=0x{dtmcs:08x} version={dtmcs & 0xF} abits={self.abits} "
            f"idle={dtm_idle}; SMC STAP tdo_oen TCKs selected={sel['oen_tcks']} unselected="
            f"{self.r['unsel']['oen_tcks']} measured and logged only"
        )
        if not self.abits:
            raise AssertionError(f"dtmcs=0x{dtmcs:08x} reports abits 0; no dmi scan can be sized")

    async def _dmi_while_held(self) -> None:
        await self._mark("S5", "dmi accesses with the debug module held, IDCODE after")
        held = []
        _, st = await self._dmi_op(
            DMCONTROL_ADDR, DMCONTROL_DMACTIVE, DMI_OP_WRITE, "held_dmactive_wr", measure=True
        )
        held.append(("dmcontrol write", st, 0))
        for name, addr in (("dmcontrol read", DMCONTROL_ADDR), ("dmstatus read", DMSTATUS_ADDR)):
            value, st = await self._dmi_op(
                addr, 0, DMI_OP_READ, f"held_{name.split()[0]}_rd", measure=True
            )
            held.append((name, st, value))
        for name, st, value in held:
            self._log(
                f"OBSERVATION debug module held, {name} status measured={st} "
                f"data measured=0x{value:08x} measured and logged only"
            )
        idcode, _ = await self._dr(DTP_IR_IDCODE, 0, 32, "idcode_after_held", smc_ir=SMC_TAP_IR_DMI)
        self.r["held"] = held
        self.r["id_after"] = idcode

    async def _release(self) -> None:
        await self._mark("S6", "RESET_CTRL release write and read-back")
        d0 = self.r["d0"]
        word = d0 | (1 << RESET_DEBUG_BIT)
        status, _, deltas = await self._fabric(
            J2A_OP_WRITE, RESET_CTRL_ADDR, word, SMC_DBG_AXSIZE_8B, "reset_ctrl_wr"
        )
        rd_status, rdata, _ = await self._fabric(
            J2A_OP_READ, RESET_CTRL_ADDR, 0, SMC_DBG_AXSIZE_8B, "reset_ctrl_rd1"
        )
        self.r["release"] = (status, deltas, rd_status, rdata)

    async def _dmactive(self) -> None:
        await self._mark("S7", "dmactive after the release")
        await self._dmireset("release")
        await self._dmi(DMCONTROL_ADDR, DMCONTROL_DMACTIVE, DMI_OP_WRITE, "dmactive_wr")
        self.r["dmcontrol"] = await self._dmi(DMCONTROL_ADDR, 0, DMI_OP_READ, "dmactive_rd")

    async def _capabilities(self) -> None:
        await self._mark("S8", "dmstatus and sbcs capability read-backs")
        self.r["dmstatus"] = await self._dmi(DMSTATUS_ADDR, 0, DMI_OP_READ, "dmstatus_rd")
        self.r["sbcs"] = await self._dmi(SBCS_ADDR, 0, DMI_OP_READ, "sbcs_rd")

    async def _system_bus_write(self) -> None:
        await self._mark("S9", "fabric write of Y, system-bus write of X")
        y_op, _, y_deltas = await self._fabric(
            J2A_OP_WRITE, SCRATCH_Y_ADDR, SCRATCH_Y, SMC_DBG_AXSIZE_4B, "scratch14_wr"
        )
        base = self._counts()
        sbcs = await self._sba_write(SCRATCH_X_ADDR, SCRATCH_X, "sba_wr")
        self.r["sba_write"] = (y_op, y_deltas, self._delta(self._counts(), base), sbcs)

    async def _system_bus_read(self) -> None:
        await self._mark("S10", "fabric read of X, system-bus reads of Y then X")
        x_op, x_rdata, x_deltas = await self._fabric(
            J2A_OP_READ, SCRATCH_X_ADDR, 0, SMC_DBG_AXSIZE_4B, "scratch15_rd"
        )
        base = self._counts()
        await self._dmi(
            SBCS_ADDR,
            SBCS_SBACCESS_32 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
            DMI_OP_WRITE,
            "sba_rd_sbcs",
        )
        reads = []
        for name, addr in (("y", SCRATCH_Y_ADDR), ("x", SCRATCH_X_ADDR)):
            await self._dmi(
                SBADDRESS0_ADDR, addr & 0xFFFF_FFFF, DMI_OP_WRITE, f"sba_rd_{name}_addr"
            )
            sbcs = await self._sba_wait(f"sba_rd_{name}")
            data = await self._dmi(SBDATA0_ADDR, 0, DMI_OP_READ, f"sba_rd_{name}_data")
            reads.append((sbcs, data))
        self.r["sba_read"] = (
            x_op,
            _lane_word(x_rdata, SCRATCH_X_ADDR),
            x_deltas,
            reads,
            self._delta(self._counts(), base),
        )

    # ---- checkers ----------------------------------------------------------------------------

    def _queue_checks(self) -> None:
        r = self.r
        id0, (gate, gate_polls), base = r["id0"], r["gate"], r["base"]
        unsel, sel = r["unsel"], r["sel"]
        d0 = r["d0"]
        held_status, held_deltas = r["held_read"]
        rel_status, rel_deltas, rd_status, rd_word = r["release"]
        dmstatus, sbcs, dtmcs = r["dmstatus"], r["sbcs"], r["dtmcs"]
        y_op, y_deltas, wr_deltas, wr_sbcs = r["sba_write"]
        x_op, x_word, x_deltas, reads, rd_deltas = r["sba_read"]
        (y_sbcs, y_sba), (x_sbcs, x_sba) = reads
        id_after = r["id_after"]
        sbversion = _field(sbcs, SBCS_SBVERSION_LSB, SBCS_SBVERSION_MASK)
        sbaccess = [_bit(sbcs, b) for b in SBCS_SBACCESS_BITS]
        held_text = "; ".join(f"{n} status {s} data 0x{v:08x}" for n, s, v in r["held"])

        self._check(
            "CHK-DBG-SMC-DM-SETUP",
            f"gate tap read {gate} after {gate_polls} polls, IDCODE ID0 0x{id0:08x}, launch "
            f"counter baselines aw/ar/b {base}; with the SMC STAP unselected tb_stap_smc_tms "
            f"toggled {unsel['smc_edges']} times against {unsel['ptap_edges']} on jtag_tms and "
            f"after TAP_3DCR {sel['smc_edges']} against {sel['ptap_edges']} with "
            f"{sel['mismatch']} TCK mismatches (want ID0 0x{DTP_DEFAULT_IDCODE:08x}, 0 "
            f"unselected edges, equal edge counts, 0 mismatches; the gate tap and the jtag_tms "
            f"edge counts are logged)",
            [
                ("ID0", id0, DTP_DEFAULT_IDCODE),
                ("unselected parked", unsel["smc_edges"], 0),
                ("selected follows", sel["smc_edges"], sel["ptap_edges"]),
                ("selected mismatches", sel["mismatch"], 0),
            ],
        )
        self._check(
            "CHK-DBG-SMC-DM-RESET-HELD",
            f"RESET_CTRL read op {held_status} word 0x{d0:016x}: bit {RESET_DEBUG_BIT} "
            f"{_bit(d0, RESET_DEBUG_BIT)}; bits 3:0 0x{d0 & RESET_CORES_MASK:x} and bit "
            f"{RESET_UNCORE_BIT} {_bit(d0, RESET_UNCORE_BIT)} logged; dmi while held completed "
            f"within the bound ({held_text}; measured and logged only); IDCODE after "
            f"0x{id_after:08x} (want op {FABRIC_OP_OKAY}, bit {RESET_DEBUG_BIT} "
            f"{RESET_DEBUG_HELD}, ID0 0x{id0:08x})",
            [
                ("op", held_status, FABRIC_OP_OKAY),
                ("debug_reset_n", _bit(d0, RESET_DEBUG_BIT), RESET_DEBUG_HELD),
                ("IDCODE after", r["id_after"], id0),
            ],
        )
        self._check(
            "CHK-DBG-SMC-DM-RELEASE",
            f"RESET_CTRL write of 0x{d0 | (1 << RESET_DEBUG_BIT):016x} captured op {rel_status} "
            f"with AW delta {rel_deltas[0]} and B delta {rel_deltas[2]}; the read back op "
            f"{rd_status} word 0x{rd_word:016x} has bit {RESET_DEBUG_BIT} "
            f"{_bit(rd_word, RESET_DEBUG_BIT)} and bits 8:0 0x{rd_word & RESET_LOW_BITS_MASK:03x} "
            f"(want op {FABRIC_OP_OKAY}, AW 1, B 1, op {FABRIC_OP_OKAY}, bit {RESET_DEBUG_BIT} "
            f"{RESET_DEBUG_RELEASED}, bits 8:0 0x{d0 & RESET_LOW_BITS_MASK:03x}, read after "
            f"the 0 of the hold read)",
            [
                ("write op", rel_status, FABRIC_OP_OKAY),
                ("AW delta", rel_deltas[0], 1),
                ("B delta", rel_deltas[2], 1),
                ("read op", rd_status, FABRIC_OP_OKAY),
                ("debug_reset_n", _bit(rd_word, RESET_DEBUG_BIT), RESET_DEBUG_RELEASED),
                ("bits 8:0", rd_word & RESET_LOW_BITS_MASK, d0 & RESET_LOW_BITS_MASK),
            ],
        )
        self._check(
            "CHK-DBG-SMC-DM-DMACTIVE",
            f"after the release the dmi write of dmcontrol = {DMCONTROL_DMACTIVE} read back "
            f"0x{r['dmcontrol']:08x}: dmactive {r['dmcontrol'] & DMCONTROL_DMACTIVE} within the "
            f"retry bound (want {DMCONTROL_DMACTIVE})",
            [("dmactive", r["dmcontrol"] & DMCONTROL_DMACTIVE, DMCONTROL_DMACTIVE)],
        )
        self._check(
            "CHK-DBG-SMC-DM-DMSTATUS",
            f"dtmcs 0x{dtmcs:08x} gave abits {self.abits} used to size the dmi scans; dmstatus "
            f"0x{dmstatus:08x}: version {_field(dmstatus, 0, DMSTATUS_VERSION_MASK)}, "
            f"authenticated {_bit(dmstatus, DMSTATUS_AUTHENTICATED_BIT)}, hasresethaltreq "
            f"{_bit(dmstatus, DMSTATUS_HASRESETHALTREQ_BIT)}, impebreak "
            f"{_bit(dmstatus, DMSTATUS_IMPEBREAK_BIT)}, confstrptrvalid "
            f"{_bit(dmstatus, DMSTATUS_CONFSTRPTRVALID_BIT)} (want {DMSTATUS_VERSION_SPEC_0_13}, "
            f"{DMSTATUS_AUTHENTICATED}, {DMSTATUS_HASRESETHALTREQ}, {DMSTATUS_IMPEBREAK}, "
            f"{DMSTATUS_CONFSTRPTRVALID})",
            [
                ("version", _field(dmstatus, 0, DMSTATUS_VERSION_MASK), DMSTATUS_VERSION_SPEC_0_13),
                (
                    "authenticated",
                    _bit(dmstatus, DMSTATUS_AUTHENTICATED_BIT),
                    DMSTATUS_AUTHENTICATED,
                ),
                (
                    "hasresethaltreq",
                    _bit(dmstatus, DMSTATUS_HASRESETHALTREQ_BIT),
                    DMSTATUS_HASRESETHALTREQ,
                ),
                ("impebreak", _bit(dmstatus, DMSTATUS_IMPEBREAK_BIT), DMSTATUS_IMPEBREAK),
                (
                    "confstrptrvalid",
                    _bit(dmstatus, DMSTATUS_CONFSTRPTRVALID_BIT),
                    DMSTATUS_CONFSTRPTRVALID,
                ),
            ],
        )
        self._check(
            "CHK-DBG-SMC-DM-SBCS",
            f"sbcs 0x{sbcs:08x}: sbversion {sbversion}, "
            f"sbasize {_field(sbcs, SBCS_SBASIZE_LSB, SBCS_SBASIZE_MASK)}, sbaccess8/16/32/64 "
            f"{sbaccess}, "
            f"sbaccess128 {_bit(sbcs, SBCS_SBACCESS128_BIT)} (want {SBCS_SBVERSION}, "
            f"{SBCS_SBASIZE}, {SBCS_SBACCESS_SUPPORTED} each, {SBCS_SBACCESS128})",
            [
                (
                    "sbversion",
                    _field(sbcs, SBCS_SBVERSION_LSB, SBCS_SBVERSION_MASK),
                    SBCS_SBVERSION,
                ),
                ("sbasize", _field(sbcs, SBCS_SBASIZE_LSB, SBCS_SBASIZE_MASK), SBCS_SBASIZE),
                ("sbaccess8", _bit(sbcs, SBCS_SBACCESS8_BIT), SBCS_SBACCESS_SUPPORTED),
                ("sbaccess16", _bit(sbcs, SBCS_SBACCESS16_BIT), SBCS_SBACCESS_SUPPORTED),
                ("sbaccess32", _bit(sbcs, SBCS_SBACCESS32_BIT), SBCS_SBACCESS_SUPPORTED),
                ("sbaccess64", _bit(sbcs, SBCS_SBACCESS64_BIT), SBCS_SBACCESS_SUPPORTED),
                ("sbaccess128", _bit(sbcs, SBCS_SBACCESS128_BIT), SBCS_SBACCESS128),
            ],
        )
        self._check(
            "CHK-DBG-SMC-DM-SBA-WRITE",
            f"the 32-bit system-bus write of X = 0x{SCRATCH_X:08x} to 0x{SCRATCH_X_ADDR:08x} "
            f"completed with (sbbusy, sberror, sbbusyerror) {self._sba_status(wr_sbcs)} within "
            f"the poll bound (want (0, 0, 0))",
            [("sbbusy, sberror, sbbusyerror", self._sba_status(wr_sbcs), (0, 0, 0))],
        )
        self._check(
            "CHK-DBG-SMC-DM-SBA-READ",
            f"fabric read of 0x{SCRATCH_X_ADDR:08x} op {x_op} data 0x{x_word:08x}; system-bus "
            f"read of 0x{SCRATCH_Y_ADDR:08x} first 0x{y_sba:08x} with {self._sba_status(y_sbcs)}; "
            f"system-bus read of 0x{SCRATCH_X_ADDR:08x} second 0x{x_sba:08x} with "
            f"{self._sba_status(x_sbcs)} (want op {FABRIC_OP_OKAY} data 0x{SCRATCH_X:08x}, "
            f"Y 0x{SCRATCH_Y:08x}, X 0x{SCRATCH_X:08x}, (0, 0, 0) each)",
            [
                ("fabric op", x_op, FABRIC_OP_OKAY),
                ("fabric data", x_word, SCRATCH_X),
                ("system-bus Y", y_sba, SCRATCH_Y),
                ("system-bus X", x_sba, SCRATCH_X),
                (
                    "sbbusy, sberror, sbbusyerror",
                    (self._sba_status(y_sbcs), self._sba_status(x_sbcs)),
                    ((0, 0, 0), (0, 0, 0)),
                ),
            ],
        )
        self._check(
            "CHK-DBG-SMC-DM-SBA-PATH",
            f"fabric write of Y op {y_op} moved aw/ar/b by {y_deltas}; fabric read of X moved "
            f"them by {x_deltas}; across the system-bus write they moved by {wr_deltas} and "
            f"across the two system-bus reads by {rd_deltas} (want AW 1 and B 1, AR 1, "
            f"(0, 0, 0), (0, 0, 0))",
            [
                ("fabric write AW", y_deltas[0], 1),
                ("fabric write B", y_deltas[2], 1),
                ("fabric read AR", x_deltas[1], 1),
                ("system-bus write flat", wr_deltas, (0, 0, 0)),
                ("system-bus reads flat", rd_deltas, (0, 0, 0)),
            ],
        )

    async def _finish(self) -> None:
        sb = self.sb
        await self._mark("S11", "ordered checker lines, wait sites and the pass stamp")
        self._queue_checks()
        failures: list[str] = []

        def run_check(chk: str, name: str, got, want) -> None:
            try:
                sb.expect_eq(name, got, want, evidence=chk)
            except AssertionError as exc:
                failures.append(str(exc))

        for chk in CHECK_ORDER:
            proof, legs = self.checks[chk]
            self._log(f"{chk}: {proof}")
            for name, got, want in legs:
                run_check(chk, f"{chk} {name}", got, want)

        for rec in self.sites:
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {state} last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites)
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        no_last = [rec["label"] for rec in self.sites if not rec["last"]]
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} kinds={kinds} expired={expired} "
            f"without_last_state={no_last} (want kinds {EXPECTED_SITE_KINDS}, expired 0)"
        )
        run_check(
            "CHK-TIMEOUT-PATHS",
            "wait records",
            (expired, no_last, kinds),
            (0, [], EXPECTED_SITE_KINDS),
        )

        await ClockCycles(self.dut.clk_smu_i, FENCE_CYCLES)
        self.step_ns["PASS"] = self._now()
        self.step_scans["PASS"] = self.scans
        order = [*STEPS, "PASS"]
        stamps = [self.step_ns[s] for s in order]
        deltas = [b - a for a, b in zip(stamps, stamps[1:])]
        counts = tuple(
            self.step_scans[b] - self.step_scans[a] for a, b in zip(SCANNED_STEPS, STEPS[1:])
        )
        fence = "<".join(f"{s}@{t:.1f}" for s, t in zip(order, stamps))
        self._log(
            f"CHK-NONVAC: ordered sim-time fence {fence} scans={self.scans} polls={self.polls} "
            f"scans per step S1..S10={counts}"
        )
        run_check(
            "CHK-NONVAC", "CHK-NONVAC ordered sim-time fence", all(d > 0 for d in deltas), True
        )
        run_check(
            "CHK-NONVAC",
            "CHK-NONVAC scans per step",
            tuple(n > 0 for n in counts),
            (True,) * len(SCANNED_STEPS),
        )
        if failures:
            raise AssertionError(f"{len(failures)} checker compare(s) failed: {failures}")
        self.done = True
