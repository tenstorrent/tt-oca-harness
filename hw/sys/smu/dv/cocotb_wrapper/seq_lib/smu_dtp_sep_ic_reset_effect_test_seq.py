# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""IC_RESET override of the SEP main reset, observed through the SEP debug system bus.

The SEP slice of the IC_RESET TDR holds the sep_reset_n pair at TDR bits 13 (reset_enable) and 14
(reset_control) with the default one-port external slice. The sequence writes a non-zero word to SEP
cold scratch word 0 over the SEP debug system bus and reads it back, engages the override in the
documented order (reset_control first, then reset_enable), and shows the SEP reset output falling
while the SMC slice, the external slice and the SMC fabric stay untouched. Test-Logic-Reset
releases the override with reset_hold 1 and keeps it with reset_hold 0. The release follows the
documented order (reset_enable first). The cold scratch word reads 0 after every override and
takes a new write. An external-slice leg drives jtag_ic_reset_ext_o to ovrd 1 with val 0 and
releases it to ovrd 0. The sep_trace_valid_o counts, the fall and rise latencies and the first
captures are measured and logged only.

Sources: hw/ip/jtag/jtag_ptap/doc/architecture.adoc (JTAG Capabilities, IC_RESET fields, 3DCR),
hw/sys/dtp/doc/clk_rst.adoc (IC_RESET overrides, reset_hold), hw/sys/dtp/doc/jtag.adoc,
doc/integrator/src/smu-composition.adoc (IC_RESET TDR structure), hw/sys/sep/doc/cpu.adoc (Dual
Scratch Register Banks), hw/sys/sep/regs/gen/c/sep_addr.h and hw/sys/smc/regs/gen/c/smc_addr.h.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_indexed_addr
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
    ptap_dr_from_capture,
    sep_dr_from_capture,
    unpack_dmi,
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
    DTP_IR_IC_RESET,
    DTP_IR_JTAG_CAPS,
    DTP_IR_SMC_AXI_SINGLE_OP,
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    DTP_JTAG_CAPS_LEN,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    PTAP_3DCR_WIDTH,
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SINGLE_OP_LEN,
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_EXT_PORT,
    SMU_IC_RESET_LEN,
    SMU_IC_RESET_SEP_PORTS,
    ic_reset_control_bit,
    ic_reset_enable_bit,
    make_smu_jtag_tap,
    pack_ic_reset_ports,
    pack_single_op,
    ptap_3dcr_value,
    require_jtag_tdo_resolved,
    unpack_single_op,
)
from seq_lib.smu_lifecycle_table import LC_STATE_PRESENSE

_SEP_ADDR_H = Path(__file__).resolve().parents[6] / "hw/sys/sep/regs/gen/c/sep_addr.h"


def _sep_indexed_addr(symbol: str, index: int) -> int:
    """Evaluate ``#define SYMBOL(idx) (BASE + (idx * STRIDE))`` from ``sep_addr.h``."""
    pattern = re.compile(
        rf"^#define {symbol}\(\w+\)\s+\((0x[0-9A-Fa-f]+) \+ \(\w+ \* (0x[0-9A-Fa-f]+)\)\s*\)"
    )
    for line in _SEP_ADDR_H.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            return int(match.group(1), 16) + index * int(match.group(2), 16)
    raise KeyError(f"{symbol} not in {_SEP_ADDR_H}")


# hw/sys/sep/regs/gen/c/sep_addr.h: SEP cold scratch word 0 (0x10802000). hw/sys/sep/doc/cpu.adoc,
# Scratch-bank reset behavior: scratch set 0 is cleared by sep_reset_n.
SEP_COLD_SCRATCH_0 = _sep_indexed_addr("SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
# hw/sys/smc/regs/gen/c/smc_addr.h: CPU_CTRL SCRATCH[11] (0xC00390D8) on the SMC fabric bridge.
SMC_SCRATCH_11 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 11)
SMC_SCRATCH_VALUE = 0x5C5C_0B01
# Non-zero words written to the SEP cold scratch word; each override must clear the one before.
SEP_WORD_BEFORE_OVERRIDE = 0x5EC0_1D5E
SEP_WORD_AFTER_HOLD_TLR = 0x5EC0_2D5E
SEP_WORD_AFTER_RELEASE = 0x5EC0_3D5E
SEP_WORD_CLEARED = 0

# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, JTAG Capabilities: num_smc_ic_rst bits 40:33,
# num_sep_ic_rst bits 32:25, num_ext_ic_rst bits 24:17.
CAPS_SMC_LSB, CAPS_SEP_LSB, CAPS_EXT_LSB = 33, 25, 17
CAPS_FIELD_MASK = 0xFF
# doc/integrator/src/smu-composition.adoc, IC_RESET TDR structure: 68 SMC ports, 8 SEP ports and
# the default one-port external slice give 2 * 77 + 1 = 155 bits.
CAPS_PORT_COUNTS = (68, 8, 1)
IC_RESET_TDR_BITS = 155
# Extra bits shifted ahead of the reset image so the capture shows where the TDR ends.
IC_RESET_PROBE_BITS = 32

# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, PTAP IC_RESET fields: port n holds reset_enable at
# TDR bit 2n+1 and reset_control at 2n+2, counted from TDO after reset_hold at bit 0.
# doc/integrator/src/smu-composition.adoc: the SEP slice runs km, otbn, aes, hmac, kmac,
# sep_reset_n, trng, abr from the external slice inward, which is the reverse of the helper's
# scan order from TDI.
RESET_HOLD_BIT = 0
SEP_SLICE_FROM_EXTERNAL = tuple(reversed(SMU_IC_RESET_SEP_PORTS))
SEP_RESET_PORT = SMU_IC_RESET_EXT_PORT + 1 + SEP_SLICE_FROM_EXTERNAL.index("sep_reset_n")
SEP_ENABLE_BIT = ic_reset_enable_bit(SEP_RESET_PORT)
SEP_CONTROL_BIT = ic_reset_control_bit(SEP_RESET_PORT)
ALL_ONES = SMU_IC_RESET_DEFAULT

# IC_RESET images. reset_enable is active low: 0 hands the port to reset_control
# (hw/sys/dtp/doc/clk_rst.adoc, IC_RESET overrides).
SEP_STAGED = pack_ic_reset_ports(
    reset_hold=1, port_enable={SEP_RESET_PORT: 1}, port_control={SEP_RESET_PORT: 0}
)
SEP_HELD = pack_ic_reset_ports(
    reset_hold=1, port_enable={SEP_RESET_PORT: 0}, port_control={SEP_RESET_PORT: 0}
)
HOLD_CLEAR = pack_ic_reset_ports(reset_hold=0)
HOLD_CLEAR_SEP_STAGED = pack_ic_reset_ports(
    reset_hold=0, port_enable={SEP_RESET_PORT: 1}, port_control={SEP_RESET_PORT: 0}
)
HOLD_CLEAR_SEP_CONTROL_LOW = pack_ic_reset_ports(reset_hold=0, port_control={SEP_RESET_PORT: 0})
HOLD_CLEAR_SEP_HELD = pack_ic_reset_ports(
    reset_hold=0, port_enable={SEP_RESET_PORT: 0}, port_control={SEP_RESET_PORT: 0}
)
HOLD_CLEAR_EXT_STAGED = pack_ic_reset_ports(
    reset_hold=0, port_enable={SMU_IC_RESET_EXT_PORT: 1}, port_control={SMU_IC_RESET_EXT_PORT: 0}
)
HOLD_CLEAR_EXT_HELD = pack_ic_reset_ports(
    reset_hold=0, port_enable={SMU_IC_RESET_EXT_PORT: 0}, port_control={SMU_IC_RESET_EXT_PORT: 0}
)
# hw/sys/dtp/doc/clk_rst.adoc: jtag_ic_reset_ext_o carries .ovrd (active high) and .val
# (reset_control); with every external bit at its reset value the output reads ovrd 0, val 1.
EXT_RESET_IMAGE = (0, 1)
EXT_HELD_LOW = (1, 0)
EXT_OVRD_IDLE = 0

# hw/sys/dtp/doc/clk_rst.adoc: Test-Logic-Reset is five TMS-high TCKs (IEEE 1149.1).
TLR_TCKS = 5
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, 3DCR: config hold 0 lets Test-Logic-Reset clear
# the PTAP select bit; the STAP 3DCR resets the same way.
CONFIG_HOLD_CLEAR = 0
PTAP_3DCR_SELECT = 1
SEP_STAP_NAME = "sep"
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SINGLE_OP wstrb: all eight byte lanes of the
# 64-bit SMC fabric beat.
WSTRB_FULL = 0xFF
FABRIC_OP_OKAY = J2A_STATUS_SUCCESS

# Bounds and windows.
SENSE_POLL_LIMIT = 2000
SENSE_POLL_CLK = 50
LEVEL_POLL_LIMIT = 400
LEVEL_POLL_CLK = 16
CAPTURE_POLL_LIMIT = 8
CAPTURE_POLL_CLK = 16
DMI_RETRY_LIMIT = 16
SBA_POLL_LIMIT = 16
ALIVE_WINDOW = 2000
CLK_WINDOW = 200
STILL_WINDOW = 200
HOLD_WINDOW = 2000
SMC_WINDOW = 500
TLR_WINDOW = 400
RELEASE_WINDOW = 200

# Wait sites per kind: the sensing wait; the SMC SINGLE_OP capture polls of the scratch write and
# read; the reset fall waits of the two overrides; the reset rise waits of the two releases; the
# external-output waits of the control leg; ten system-bus completion polls (S2 two, S3 one, S4
# one, S7 three, S9 three); dmi retry loops of the non-poll dmi accesses (four activations of two
# accesses, ten system-bus accesses of three).
EXPECTED_SITE_KINDS = {
    "sensing": 1,
    "op_capture": 2,
    "reset_fall": 2,
    "reset_rise": 2,
    "ext_output": 2,
    "sba_busy": 10,
    "dmi_retry": 38,
}
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
SCANNED_STEPS = STEPS[:-1]
FENCE_CYCLES = 2
CHECK_ORDER = (
    "CHK-DBG-IC-SEP-SETUP",
    "CHK-DBG-IC-SEP-POSITION",
    "CHK-DBG-IC-SEP-QUIESCE",
    "CHK-DBG-IC-SEP-ISOLATION",
    "CHK-DBG-IC-SEP-HOLD-TLR",
    "CHK-DBG-IC-SEP-RELEASE",
)
# Pins that can run at the clk_smu_i rate, so a rising-edge sample alone can read one level.
CLOCK_PINS = ("obs_sep_clk_o",)
NOP_REQUEST = pack_dmi(0, 0, op=DMI_OP_NOP)


def _cleared_bits(image: int) -> list[int]:
    """Indices of the IC_RESET TDR bits that read 0."""
    return [bit for bit in range(SMU_IC_RESET_LEN) if not (image >> bit) & 1]


def _trailing_ones(value: int, limit: int) -> int:
    count = 0
    while count < limit and (value >> count) & 1:
        count += 1
    return count


class smu_dtp_sep_ic_reset_effect_test_seq:
    """SEP slice sep_reset_n override of the SEP main reset."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.selected = False
        self.ir_key: tuple[bool, int] | None = None
        self.scans = 0
        self.polls = 0
        self.step_ns: dict[str, float] = {}
        self.step_scans: dict[str, int] = {}
        self.sites: list[dict] = []
        self.checks: dict[str, tuple] = {}
        self.r: dict[str, object] = {}
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

    def _check(self, chk: str, proof: str, got, want) -> None:
        """Queue a compare; its proof line and the compare run in step order at the end."""
        self.checks[chk] = (proof, got, want)

    def _pin(self, name: str) -> int:
        return sample(getattr(self.dut, name), name)

    async def _window(self, cycles: int, *names: str) -> dict[str, list[int]]:
        """Each named pin sampled on every clk_smu_i rising edge; clock pins also on the falling."""
        out: dict[str, list[int]] = {name: [] for name in names}
        clocks = [name for name in names if name in CLOCK_PINS]
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_smu_i)
            for name in names:
                out[name].append(self._pin(name))
            if clocks:
                await FallingEdge(self.dut.clk_smu_i)
                for name in clocks:
                    out[name].append(self._pin(name))
        return out

    # ---- JTAG access -------------------------------------------------------------------------

    async def _ir(self, opcode: int, label: str) -> None:
        key = (self.selected, opcode)
        if self.ir_key == key:
            return
        if self.selected:
            value, width = network_ir_scan(opcode, SEP_TAP_IR_DMI)
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
        sep_request: int = NOP_REQUEST,
        idle: int = 0,
    ) -> tuple[int, int]:
        """Scan one PTAP register; returns (its capture, the SEP dmi capture or 0)."""
        await self._ir(opcode, label)
        if self.selected:
            word, total = network_scan(value, width, sep_request, DMI_DR_WIDTH)
            raw = await self.jtag.shift_dr(word, total, back_to_rti=True)
            captured = ptap_dr_from_capture(raw, width, DMI_DR_WIDTH)
            sep = sep_dr_from_capture(raw, DMI_DR_WIDTH)
        else:
            total = width
            raw = await self.jtag.shift_dr(value, width, back_to_rti=True)
            captured, sep = raw, 0
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
            f"sep_in=0x{sep_request:x} sep_out=0x{sep:x}"
        )
        return captured, sep

    async def _ic_reset(self, image: int, label: str) -> int:
        captured, _ = await self._dr(DTP_IR_IC_RESET, image, SMU_IC_RESET_LEN, label)
        return captured

    async def _tlr(self) -> None:
        for _ in range(TLR_TCKS):
            await self.jtag.step_tms(1)
        self.selected = False
        self.ir_key = None
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)

    async def _select_sep_stap(self) -> None:
        jtag = self.jtag
        await jtag.shift_ir(DTP_IR_TAP_3DCR, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(
            ptap_3dcr_value(config_hold=CONFIG_HOLD_CLEAR, select=PTAP_3DCR_SELECT),
            PTAP_3DCR_WIDTH,
            back_to_rti=True,
        )
        await jtag.step_tms(0)
        await jtag.step_tms(0)
        sib = stap_sib_pattern(SEP_STAP_NAME, 1)
        sib_word, sib_width = ptap_prefixed(
            sib, len(SMU_SEP_STAP_ORDER), config_hold=CONFIG_HOLD_CLEAR
        )
        await jtag.shift_dr(sib_word, sib_width, back_to_rti=True)
        stap_word, stap_width = stap_3dcr_scan_word(
            SEP_STAP_NAME, config_hold=CONFIG_HOLD_CLEAR, stap_sel=1, tms_hold=1, sib_en=0
        )
        value, width = ptap_prefixed(stap_word, stap_width, config_hold=CONFIG_HOLD_CLEAR)
        await jtag.shift_dr(value, width, back_to_rti=True)
        await jtag.step_tms(0)
        await jtag.step_tms(0)
        self.selected = True
        self.ir_key = None
        self.scans += 3
        self._log(
            f"SCAN SEP STAP selected through TAP_3DCR sib=0x{sib:x} 3dcr=0x{stap_word:x} "
            f"order={SMU_SEP_STAP_ORDER}"
        )

    async def _dmi_op(self, addr: int, data: int, op: int, label: str, *, record: bool = True):
        """One dmi access: the request scan, then collect scans retried while the status is busy."""
        request = pack_dmi(addr, data, op=op)
        await self._dr(
            DTP_IR_TAP_3DCR,
            ptap_3dcr_value(config_hold=CONFIG_HOLD_CLEAR, select=PTAP_3DCR_SELECT),
            PTAP_3DCR_WIDTH,
            f"dmi_{label}_req",
            sep_request=request,
            idle=DMI_IDLE_TCKS,
        )
        used = 0
        while True:
            _, captured = await self._dr(
                DTP_IR_TAP_3DCR,
                ptap_3dcr_value(config_hold=CONFIG_HOLD_CLEAR, select=PTAP_3DCR_SELECT),
                PTAP_3DCR_WIDTH,
                f"dmi_{label}_c{used}",
                counted=False,
                sep_request=pack_dmi(addr, 0, op=DMI_OP_NOP),
                idle=DMI_IDLE_TCKS,
            )
            used += 1
            _, value, status = unpack_dmi(captured)
            if status != DMI_STATUS_BUSY:
                break
            if used >= DMI_RETRY_LIMIT:
                self._site(
                    "dmi_retry", label, DMI_RETRY_LIMIT, "retries", used, f"status={status}", True
                )
        self._log(f"CELL dmi {label} status={status} data=0x{value:08x}")
        if status != DMI_STATUS_OK:
            raise AssertionError(f"dmi {label} addr=0x{addr:02x} status={status}")
        if record:
            self._site(
                "dmi_retry", label, DMI_RETRY_LIMIT, "retries", used, f"status={status}", False
            )
        return value

    async def _sba_wait(self, label: str) -> None:
        used = 0
        while True:
            sbcs = await self._dmi_op(
                SBCS_ADDR, 0, DMI_OP_READ, f"{label}_sbcs{used}", record=False
            )
            used += 1
            if not sbcs & SBCS_SBBUSY:
                break
            if used >= SBA_POLL_LIMIT:
                self._site(
                    "sba_busy", label, SBA_POLL_LIMIT, "polls", used, f"sbcs=0x{sbcs:08x}", True
                )
        self._site("sba_busy", label, SBA_POLL_LIMIT, "polls", used, f"sbcs=0x{sbcs:08x}", False)
        sberror = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        if sberror or sbcs & SBCS_SBBUSYERROR:
            raise AssertionError(f"system bus {label}: sbcs=0x{sbcs:08x} sberror={sberror}")

    async def _sba_write(self, addr: int, data: int, label: str) -> None:
        await self._dmi_op(
            SBCS_ADDR, SBCS_SBACCESS_32 | SBCS_SBERROR_W1C, DMI_OP_WRITE, f"{label}_sbcs"
        )
        await self._dmi_op(SBADDRESS0_ADDR, addr, DMI_OP_WRITE, f"{label}_addr")
        await self._dmi_op(SBDATA0_ADDR, data, DMI_OP_WRITE, f"{label}_data")
        await self._sba_wait(label)

    async def _sba_read(self, addr: int, label: str) -> int:
        await self._dmi_op(
            SBCS_ADDR,
            SBCS_SBACCESS_32 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
            DMI_OP_WRITE,
            f"{label}_sbcs",
        )
        await self._dmi_op(SBADDRESS0_ADDR, addr, DMI_OP_WRITE, f"{label}_addr")
        await self._sba_wait(label)
        return await self._dmi_op(SBDATA0_ADDR, 0, DMI_OP_READ, f"{label}_data")

    async def _activate_debug_module(self, label: str) -> int:
        """Select the SEP STAP, set dmcontrol.dmactive and return the dmactive bit read back."""
        await self._select_sep_stap()
        await self._dmi_op(DMCONTROL_ADDR, DMCONTROL_DMACTIVE, DMI_OP_WRITE, f"{label}_dmactive_wr")
        dmcontrol = await self._dmi_op(DMCONTROL_ADDR, 0, DMI_OP_READ, f"{label}_dmactive_rd")
        return dmcontrol & DMCONTROL_DMACTIVE

    async def _fabric(self, op: int, addr: int, data: int, label: str) -> tuple[int, int]:
        """SMC fabric SINGLE_OP; captures until op leaves busy, bounded."""
        size = SMC_DBG_AXSIZE_8B
        wstrb = WSTRB_FULL if op == J2A_OP_WRITE else 0
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
        self._log(f"CELL {label} op={status} data=0x{rdata:016x}")
        return status, rdata

    async def _wait_level(self, kind: str, label: str, name: str, want: int) -> int:
        """Poll a pin until it reads `want`, bounded; returns the level."""
        used = 0
        start = self._now()
        while True:
            level = self._pin(name)
            if level == want:
                break
            if used >= LEVEL_POLL_LIMIT:
                self._site(kind, label, LEVEL_POLL_LIMIT, "polls", used, f"{name}={level}", True)
            used += 1
            await ClockCycles(self.dut.clk_smu_i, LEVEL_POLL_CLK)
        self._site(kind, label, LEVEL_POLL_LIMIT, "polls", used, f"{name}={level}", False)
        self._log(
            f"OBSERVATION {label} {name} reached {want} after {used} polls "
            f"({self._now() - start:.1f}ns after the update) measured and logged only"
        )
        return level

    def _ext(self) -> tuple[int, int]:
        return (self._pin("jtag_ic_reset_ext_ovrd"), self._pin("jtag_ic_reset_ext_ctrl_n"))

    async def run(self) -> None:
        await self._setup()
        await self._alive_written()
        await self._attribution_control()
        await self._engage_update_one()
        await self._engage_update_two()
        await self._isolation_while_engaged()
        await self._tlr_hold_one()
        await self._tlr_hold_zero()
        await self._release()
        await self._external_leg()
        await self._finish()

    async def _setup(self) -> None:
        await self._mark("S1", "TAP reset, IDCODE, JTAG_CAPS, IC_RESET image, SCRATCH[11] write")
        self.jtag = jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        self._log(f"OBSERVATION jtag_period_ns={self.cfg.jtag_period_ns} measured and logged only")
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        self.scans += 1
        idcode = await jtag.read_idcode()
        require_jtag_tdo_resolved("IDCODE")
        self._log(f"SCAN {self.scans} DR IDCODE out=0x{idcode:08x}")

        used = 0
        while True:
            lc_state = self._pin("lc_state_o")
            dbg_disable = self._pin("lcc_dbg_disable_o")
            last = f"lc_state=0x{lc_state:02x} dbg_disable=0x{dbg_disable:04x}"
            if lc_state != LC_STATE_PRESENSE and dbg_disable == 0:
                break
            if used >= SENSE_POLL_LIMIT:
                self._site("sensing", "lc_state", SENSE_POLL_LIMIT, "polls", used, last, True)
            used += 1
            await ClockCycles(self.dut.clk_smu_i, SENSE_POLL_CLK)
        self._site("sensing", "lc_state", SENSE_POLL_LIMIT, "polls", used, last, False)

        caps, _ = await self._dr(DTP_IR_JTAG_CAPS, 0, DTP_JTAG_CAPS_LEN, "jtag_caps")
        counts = tuple(
            (caps >> lsb) & CAPS_FIELD_MASK for lsb in (CAPS_SMC_LSB, CAPS_SEP_LSB, CAPS_EXT_LSB)
        )
        probe_width = SMU_IC_RESET_LEN + IC_RESET_PROBE_BITS
        probe, _ = await self._dr(
            DTP_IR_IC_RESET, ALL_ONES << IC_RESET_PROBE_BITS, probe_width, "ic_reset_image"
        )
        tdr_bits = _trailing_ones(probe, probe_width)
        status, _ = await self._fabric(
            J2A_OP_WRITE, SMC_SCRATCH_11, SMC_SCRATCH_VALUE, "scratch11_wr"
        )
        self.r["setup"] = (idcode, counts, tdr_bits, status)

    async def _alive_written(self) -> None:
        await self._mark("S2", "SEP STAP, debug module, cold scratch word written and read back")
        dmactive = await self._activate_debug_module("s2")
        await self._sba_write(SEP_COLD_SCRATCH_0, SEP_WORD_BEFORE_OVERRIDE, "s2_wr")
        word = await self._sba_read(SEP_COLD_SCRATCH_0, "s2_rd")
        win = await self._window(
            ALIVE_WINDOW, "sep_reset_n_o", "obs_sep_clk_o", "sep_trace_valid_o"
        )
        self._log(
            f"OBSERVATION sep_trace_valid_o 1-samples in {ALIVE_WINDOW} cycles before the override "
            f"measured={sum(win['sep_trace_valid_o'])} measured and logged only"
        )
        clk = sorted(set(win["obs_sep_clk_o"][: 2 * CLK_WINDOW]))
        self.r["alive"] = (dmactive, word, win["sep_reset_n_o"][0], clk)

    async def _attribution_control(self) -> None:
        await self._mark("S3", "no override: Test-Logic-Reset, STAP re-select, cold scratch read")
        await self._tlr()
        dmactive = await self._activate_debug_module("s3")
        word = await self._sba_read(SEP_COLD_SCRATCH_0, "s3_rd")
        self.r["attribution"] = (dmactive, word)

    async def _engage_update_one(self) -> None:
        await self._mark("S4", "update 1: reset_control 0 with reset_enable 1")
        await self._ic_reset(SEP_STAGED, "sep_staged")
        win = await self._window(STILL_WINDOW, "sep_reset_n_o")
        word = await self._sba_read(SEP_COLD_SCRATCH_0, "s4_rd")
        self.r["update1"] = (sum(win["sep_reset_n_o"]), len(win["sep_reset_n_o"]), word)

    async def _engage_update_two(self) -> None:
        await self._mark("S5", "update 2: reset_enable 0 and 0, hold window")
        await self._ic_reset(SEP_HELD, "sep_held")
        level = await self._wait_level("reset_fall", "sep_held", "sep_reset_n_o", 0)
        win = await self._window(
            HOLD_WINDOW, "sep_reset_n_o", "obs_sep_clk_o", "sep_trace_valid_o", "obs_sep_rst_n_o"
        )
        self._log(
            f"OBSERVATION sep_trace_valid_o 1-samples in {HOLD_WINDOW} hold cycles "
            f"measured={sum(win['sep_trace_valid_o'])}; obs_sep_rst_n_o 1-samples "
            f"measured={sum(win['obs_sep_rst_n_o'])} measured and logged only"
        )
        self.r["update2"] = (
            level,
            sum(win["sep_reset_n_o"]),
            len(win["sep_reset_n_o"]),
            sorted(set(win["obs_sep_clk_o"])),
        )

    async def _isolation_while_engaged(self) -> None:
        await self._mark("S6", "held image capture, external output, SMC reset, SMC fabric read")
        captured = await self._ic_reset(SEP_HELD, "held_capture")
        ext = self._ext()
        win = await self._window(SMC_WINDOW, "obs_smc_rst_n_o")
        status, rdata = await self._fabric(J2A_OP_READ, SMC_SCRATCH_11, 0, "scratch11_rd")
        smc_samples = win["obs_smc_rst_n_o"]
        self.r["held"] = (captured, ext, all(smc_samples), len(smc_samples), status, rdata)

    async def _tlr_hold_one(self) -> None:
        await self._mark("S7", "Test-Logic-Reset with reset_hold 1, SEP alive again")
        await self._tlr()
        level = await self._wait_level("reset_rise", "tlr_hold1", "sep_reset_n_o", 1)
        captured = await self._ic_reset(ALL_ONES, "tlr_hold1_capture")
        dmactive = await self._activate_debug_module("s7")
        cleared = await self._sba_read(SEP_COLD_SCRATCH_0, "s7_rd0")
        await self._sba_write(SEP_COLD_SCRATCH_0, SEP_WORD_AFTER_HOLD_TLR, "s7_wr")
        word = await self._sba_read(SEP_COLD_SCRATCH_0, "s7_rd1")
        self.r["tlr1"] = (level, captured, dmactive, cleared, word)

    async def _tlr_hold_zero(self) -> None:
        await self._mark("S8", "override engaged with reset_hold 0, Test-Logic-Reset")
        await self._ic_reset(HOLD_CLEAR, "hold_clear")
        await self._ic_reset(HOLD_CLEAR_SEP_CONTROL_LOW, "hold_clear_control")
        await self._ic_reset(HOLD_CLEAR_SEP_HELD, "hold_clear_held")
        level = await self._wait_level("reset_fall", "hold0_held", "sep_reset_n_o", 0)
        await self._tlr()
        win = await self._window(TLR_WINDOW, "sep_reset_n_o")
        captured = await self._ic_reset(HOLD_CLEAR_SEP_HELD, "tlr_hold0_capture")
        self.r["tlr0"] = (level, sum(win["sep_reset_n_o"]), len(win["sep_reset_n_o"]), captured)

    async def _release(self) -> None:
        await self._mark("S9", "release: reset_enable 1 first, then reset_control 1")
        await self._ic_reset(HOLD_CLEAR_SEP_STAGED, "release_enable")
        level = await self._wait_level("reset_rise", "release_enable", "sep_reset_n_o", 1)
        await self._ic_reset(HOLD_CLEAR, "release_control")
        win = await self._window(RELEASE_WINDOW, "sep_reset_n_o")
        captured = await self._ic_reset(HOLD_CLEAR, "release_capture")
        dmactive = await self._activate_debug_module("s9")
        cleared = await self._sba_read(SEP_COLD_SCRATCH_0, "s9_rd0")
        await self._sba_write(SEP_COLD_SCRATCH_0, SEP_WORD_AFTER_RELEASE, "s9_wr")
        word = await self._sba_read(SEP_COLD_SCRATCH_0, "s9_rd1")
        self.r["release"] = (
            level,
            sum(win["sep_reset_n_o"]),
            len(win["sep_reset_n_o"]),
            captured,
            dmactive,
            cleared,
            word,
        )

    async def _external_leg(self) -> None:
        await self._mark("S10", "external slice: control staged, override applied, released")
        sep_levels = []
        await self._ic_reset(HOLD_CLEAR_EXT_STAGED, "ext_staged")
        staged = self._ext()
        sep_levels.append(self._pin("sep_reset_n_o"))
        await self._ic_reset(HOLD_CLEAR_EXT_HELD, "ext_held")
        await self._wait_level("ext_output", "ext_held", "jtag_ic_reset_ext_ovrd", 1)
        held = self._ext()
        sep_levels.append(self._pin("sep_reset_n_o"))
        await self._ic_reset(HOLD_CLEAR_EXT_STAGED, "ext_release_enable")
        await self._ic_reset(HOLD_CLEAR, "ext_release_control")
        await self._wait_level("ext_output", "ext_released", "jtag_ic_reset_ext_ovrd", 0)
        released = self._ext()
        sep_levels.append(self._pin("sep_reset_n_o"))
        await self._ic_reset(ALL_ONES, "hold_restore")
        self.r["ext"] = (staged[0], held, released[0], sep_levels)

    async def _finish(self) -> None:
        sb = self.sb
        await self._mark("S11", "ordered checker lines, wait sites and the pass stamp")
        self._queue_checks()
        failures = []

        def run_check(chk: str, name: str, got, want) -> None:
            try:
                sb.expect_eq(name, got, want, evidence=chk)
            except AssertionError as exc:
                failures.append(str(exc))

        for chk in CHECK_ORDER:
            proof, got, want = self.checks[chk]
            self._log(f"{chk}: {proof}")
            run_check(chk, chk, got, want)

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
        fence_order = [*STEPS, "PASS"]
        stamps = [self.step_ns[s] for s in fence_order]
        deltas = [b - a for a, b in zip(stamps, stamps[1:])]
        counts = tuple(
            self.step_scans[b] - self.step_scans[a] for a, b in zip(SCANNED_STEPS, STEPS[1:])
        )
        fence = "<".join(f"{s}@{t:.1f}" for s, t in zip(fence_order, stamps))
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

    def _queue_checks(self) -> None:
        r = self.r
        idcode, counts, tdr_bits, scratch_status = r["setup"]
        dmactive, word_z1, rst_alive, clk_alive = r["alive"]
        dmactive_attribution, word_attribution = r["attribution"]
        ones, window, word_after_u1 = r["update1"]
        fall_level, hold_ones, hold_len, clk_hold = r["update2"]
        held_capture, ext_held, smc_all_one, smc_len, fabric_status, fabric_data = r["held"]
        hold1_level, hold1_capture, dmactive_tlr, cleared_tlr, word_z2 = r["tlr1"]
        hold0_level, hold0_ones, hold0_len, hold0_capture = r["tlr0"]
        (
            rel_level,
            rel_ones,
            rel_len,
            rel_capture,
            dmactive_release,
            cleared_release,
            word_z3,
        ) = r["release"]
        ext_staged_ovrd, ext_driven, ext_released_ovrd, sep_levels = r["ext"]
        sep_bits = [SEP_ENABLE_BIT, SEP_CONTROL_BIT]

        self._check(
            "CHK-DBG-IC-SEP-SETUP",
            f"IDCODE 0x{idcode:08x}; JTAG_CAPS num_smc/num_sep/num_ext_ic_rst read {counts}; the "
            f"IC_RESET scan returned a run of {tdr_bits} ones then the shifted-in zeros; "
            f"SCRATCH[11] 0x{SMC_SCRATCH_11:08x} write captured op {scratch_status}; the SEP STAP "
            f"was selected and dmcontrol.dmactive read {dmactive} (want "
            f"0x{DTP_DEFAULT_IDCODE:08x}, {CAPS_PORT_COUNTS}, {IC_RESET_TDR_BITS}, "
            f"op {FABRIC_OP_OKAY}, 1)",
            (idcode, counts, tdr_bits, scratch_status, dmactive),
            (DTP_DEFAULT_IDCODE, CAPS_PORT_COUNTS, IC_RESET_TDR_BITS, FABRIC_OP_OKAY, 1),
        )
        self._check(
            "CHK-DBG-IC-SEP-POSITION",
            f"after update 1 (bit {SEP_CONTROL_BIT} = 0, bit {SEP_ENABLE_BIT} = 1) "
            f"sep_reset_n_o read 1 on {ones} of {window} samples and cold scratch word 0 read "
            f"0x{word_after_u1:08x}; after update 2 (bits {SEP_ENABLE_BIT} and {SEP_CONTROL_BIT} "
            f"= 0) sep_reset_n_o read {fall_level} within the bound; the capture with the SEP "
            f"override held cleared bits {_cleared_bits(held_capture)} (want {window} of {window}, "
            f"0x{SEP_WORD_BEFORE_OVERRIDE:08x}, 0, bits {sep_bits})",
            (ones, word_after_u1, fall_level, _cleared_bits(held_capture)),
            (window, SEP_WORD_BEFORE_OVERRIDE, 0, sep_bits),
        )
        self._check(
            "CHK-DBG-IC-SEP-QUIESCE",
            f"cold scratch word 0 read 0x{word_z1:08x} over the system bus before the override "
            f"with sep_reset_n_o {rst_alive} and obs_sep_clk_o levels {clk_alive} in "
            f"{CLK_WINDOW} cycles; with no override, after Test-Logic-Reset and the STAP re-select "
            f"dmactive read {dmactive_attribution} and the word read 0x{word_attribution:08x}; "
            f"after the override sep_reset_n_o read {fall_level} within the bound and 1 on "
            f"{hold_ones} of {hold_len} hold samples, obs_sep_clk_o levels {clk_hold} (want "
            f"0x{SEP_WORD_BEFORE_OVERRIDE:08x}, 1, [0, 1], 1, 0x{SEP_WORD_BEFORE_OVERRIDE:08x}, 0, "
            f"0 ones, [0, 1])",
            (
                word_z1,
                rst_alive,
                clk_alive,
                dmactive_attribution,
                word_attribution,
                fall_level,
                hold_ones,
                clk_hold,
            ),
            (SEP_WORD_BEFORE_OVERRIDE, 1, [0, 1], 1, SEP_WORD_BEFORE_OVERRIDE, 0, 0, [0, 1]),
        )
        self._check(
            "CHK-DBG-IC-SEP-ISOLATION",
            f"while the SEP override held, jtag_ic_reset_ext_o (ovrd, val) read {ext_held} and "
            f"rst_primary_smc_clk_no read 1 on every one of {smc_len} samples ({smc_all_one}) and "
            f"the fabric "
            f"read of 0x{SMC_SCRATCH_11:08x} captured op {fabric_status} with data "
            f"0x{fabric_data:x}; the control leg left ovrd {ext_staged_ovrd} with control "
            f"staged, drove (ovrd, val) {ext_driven} and read ovrd {ext_released_ovrd} after "
            f"release, sep_reset_n_o levels {sep_levels} (want {EXT_RESET_IMAGE}, True, "
            f"op {FABRIC_OP_OKAY}, 0x{SMC_SCRATCH_VALUE:x}, {EXT_OVRD_IDLE}, {EXT_HELD_LOW}, "
            f"{EXT_OVRD_IDLE}, all 1)",
            (
                ext_held,
                smc_all_one,
                fabric_status,
                fabric_data,
                ext_staged_ovrd,
                ext_driven,
                ext_released_ovrd,
                sep_levels,
            ),
            (
                EXT_RESET_IMAGE,
                True,
                FABRIC_OP_OKAY,
                SMC_SCRATCH_VALUE,
                EXT_OVRD_IDLE,
                EXT_HELD_LOW,
                EXT_OVRD_IDLE,
                [1] * len(sep_levels),
            ),
        )
        self._check(
            "CHK-DBG-IC-SEP-HOLD-TLR",
            f"with reset_hold 1 Test-Logic-Reset returned sep_reset_n_o to {hold1_level} within "
            f"the bound, the capture cleared bits {_cleared_bits(hold1_capture)}, dmactive read "
            f"{dmactive_tlr}, cold scratch word 0 read 0x{cleared_tlr:08x} and "
            f"0x{SEP_WORD_AFTER_HOLD_TLR:08x} read back as 0x{word_z2:08x}; with reset_hold 0 "
            f"sep_reset_n_o was 0 within the bound ({hold0_level}) and read 1 on {hold0_ones} "
            f"of {hold0_len} samples after Test-Logic-Reset, the capture cleared bits "
            f"{_cleared_bits(hold0_capture)} (want 1, [], 1, 0x{SEP_WORD_CLEARED:08x}, "
            f"0x{SEP_WORD_AFTER_HOLD_TLR:08x}, 0, 0 ones, "
            f"{[RESET_HOLD_BIT, *sep_bits]})",
            (
                hold1_level,
                _cleared_bits(hold1_capture),
                dmactive_tlr,
                cleared_tlr,
                word_z2,
                hold0_level,
                hold0_ones,
                _cleared_bits(hold0_capture),
            ),
            (
                1,
                [],
                1,
                SEP_WORD_CLEARED,
                SEP_WORD_AFTER_HOLD_TLR,
                0,
                0,
                [RESET_HOLD_BIT, *sep_bits],
            ),
        )
        self._check(
            "CHK-DBG-IC-SEP-RELEASE",
            f"after update 1 (bit {SEP_ENABLE_BIT} = 1) sep_reset_n_o read {rel_level} within "
            f"the bound and read 1 on {rel_ones} of {rel_len} samples after update 2 "
            f"(bit {SEP_CONTROL_BIT} = 1); the capture cleared bits {_cleared_bits(rel_capture)}, "
            f"dmactive read {dmactive_release}, cold scratch word 0 read "
            f"0x{cleared_release:08x} and 0x{SEP_WORD_AFTER_RELEASE:08x} read back as "
            f"0x{word_z3:08x} (want 1, {rel_len} of {rel_len}, [{RESET_HOLD_BIT}], 1, "
            f"0x{SEP_WORD_CLEARED:08x}, "
            f"0x{SEP_WORD_AFTER_RELEASE:08x})",
            (
                rel_level,
                rel_ones,
                _cleared_bits(rel_capture),
                dmactive_release,
                cleared_release,
                word_z3,
            ),
            (
                1,
                rel_len,
                [RESET_HOLD_BIT],
                1,
                SEP_WORD_CLEARED,
                SEP_WORD_AFTER_RELEASE,
            ),
        )
