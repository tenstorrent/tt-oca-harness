# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP TAP → SEP debug-module DMI (IR=5'h11) on the SEP=1 wrapper.

S1: PTAP IDCODE is the configured IEEE packing.
S2: TAP_3DCR selects the SEP STAP; host TMS then follows the PTAP.
S3: PTAP IR 6'h11 is the RISC-V reserved DMI encoding (maps to BYPASS on
    the PTAP). The lockstep SEP EL2 TAP captures the same five LSBs as
    IR=5'h11. A DMI read of dmstatus must return a non-zero version. That
    read goes through dmi_mux and is gated by dmi_core_enable; a tie of 0
    leaves the core aperture silent and this compare fails.

No Force. Observe-only hierarchy is the SEP STAP host TAP and SEP TDO.
Not claimed: abstract commands, SBA, DTMCS (IR=5'h10 does not enter the mux).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagMasterSequence, OcahJtagState

from seq_lib.smu_boundary_regs import (
    SMU_SEP_STAP_ORDER,
    ptap_prefixed,
    stap_3dcr_scan_word,
    stap_sib_pattern,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    PTAP_3DCR_WIDTH,
    dtp_ir_opcode,
    make_smu_jtag_tap,
    ptap_3dcr_value,
)

DTP_IR_DMI = dtp_ir_opcode("RISCV_RESERVED_1")
EL2_IR_DMI = 0x11
DMI_DR_WIDTH = 41
DMI_ABITS = 7
DMSTATUS_ADDR = 0x11
EDGE_SAMPLE_CYCLES = 2000
MIN_PTAP_TMS_EDGES = DTP_IR_WIDTH

SEP_STAP_TMS = "u_dut.u_smu.dtp_sep_stap_tap_ctrl.tms"
SEP_STAP_TCK = "u_dut.u_smu.dtp_sep_stap_tap_ctrl.tck"
SEP_TDO = "u_dut.u_smu.gen_sep.u_sep.jtag_tdo_o"


def pack_dmi(addr: int, data: int, op: int, *, abits: int = DMI_ABITS) -> int:
    return ((int(addr) & ((1 << abits) - 1)) << 34) | ((int(data) & 0xFFFF_FFFF) << 2) | (
        int(op) & 0x3
    )


def unpack_dmi(raw: int) -> tuple[int, int, int]:
    op = int(raw) & 0x3
    data = (int(raw) >> 2) & 0xFFFF_FFFF
    addr = (int(raw) >> 34) & 0x7F
    return addr, data, op


class smu_dtp_sep_dm_dmi_test_seq:
    """Select the SEP STAP and read dmstatus through DMI IR=5'h11."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.dmstatus = 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _hier_bit(self, path: str) -> int:
        obj = self.dut
        for part in path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                raise AssertionError(f"{path} unobservable on the wrapper")
        val = obj.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {path}: {val}")
        return int(val) & 1

    async def _observe_tms(self, cycles: int) -> dict[str, int]:
        prev_ptap = int(self.dut.jtag_tms.value) & 1
        prev_sep = self._hier_bit(SEP_STAP_TMS)
        ptap_edges = 0
        sep_edges = 0
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_ref_i)
            ptap = int(self.dut.jtag_tms.value) & 1
            sep = self._hier_bit(SEP_STAP_TMS)
            if ptap != prev_ptap:
                ptap_edges += 1
                prev_ptap = ptap
            if sep != prev_sep:
                sep_edges += 1
                prev_sep = sep
        return {"ptap_edges": ptap_edges, "sep_edges": sep_edges}

    async def _collect_sep_tdo(self, nbits: int) -> int:
        bits = 0
        got = 0
        prev_tck = self._hier_bit(SEP_STAP_TCK)
        guard = 0
        while got < nbits and guard < 20000:
            await RisingEdge(self.dut.clk_ref_i)
            tck = self._hier_bit(SEP_STAP_TCK)
            if tck == 1 and prev_tck == 0:
                bits |= self._hier_bit(SEP_TDO) << got
                got += 1
            prev_tck = tck
            guard += 1
        if got != nbits:
            raise AssertionError(f"SEP TDO collected {got} bits want {nbits}")
        return bits

    async def _select_sep_stap(self, jtag) -> None:
        await jtag.shift_ir(DTP_IR_TAP_3DCR, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(
            ptap_3dcr_value(config_hold=1, select=1),
            PTAP_3DCR_WIDTH,
            back_to_rti=True,
        )
        await jtag.step_tms(0)
        await jtag.step_tms(0)
        sib = stap_sib_pattern("sep", 1)
        sib_word, sib_width = ptap_prefixed(sib, len(SMU_SEP_STAP_ORDER))
        await jtag.shift_dr(sib_word, sib_width, back_to_rti=True)
        stap_word, stap_width = stap_3dcr_scan_word(
            "sep", config_hold=1, stap_sel=1, tms_hold=1, close_sib=0
        )
        value, width = ptap_prefixed(stap_word, stap_width)
        await jtag.shift_dr(value, width, back_to_rti=True)
        self._log(
            f"OBS SEP STAP TAP_3DCR selected sib=0x{sib:x}->{sib_word:x}/{sib_width} "
            f"3dcr=0x{stap_word:x}->{value:x}/{width} order={SMU_SEP_STAP_ORDER}"
        )

    async def _dmi_scan(self, jtag, req: int) -> int:
        watcher = cocotb.start_soon(self._collect_sep_tdo(DMI_DR_WIDTH))
        await jtag.shift_dr(req, DMI_DR_WIDTH, back_to_rti=True)
        for _ in range(8):
            await jtag.step_tms(0)
        return await watcher

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        raw = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        jtag = OcahJtagMasterSequence(raw)
        await jtag.reset_to_tlr()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await raw.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        sb.expect_eq("CHK-SEP-DMI-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)
        self.s1_ok = True

        unsel_mon = cocotb.start_soon(self._observe_tms(EDGE_SAMPLE_CYCLES))
        await jtag.shift_ir(dtp_ir_opcode("IDCODE"), width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(0, 32, back_to_rti=True)
        unsel = await unsel_mon
        if unsel["ptap_edges"] < MIN_PTAP_TMS_EDGES:
            raise AssertionError(
                f"unselected IDCODE PTAP TMS edges={unsel['ptap_edges']} "
                f"want >={MIN_PTAP_TMS_EDGES}"
            )
        if unsel["sep_edges"] != 0:
            raise AssertionError(
                f"SEP STAP TMS toggled while unselected: sep_edges={unsel['sep_edges']}"
            )

        await self._select_sep_stap(jtag)

        sel_mon = cocotb.start_soon(self._observe_tms(EDGE_SAMPLE_CYCLES))
        await jtag.shift_ir(dtp_ir_opcode("IDCODE"), width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(0, 32, back_to_rti=True)
        sel = await sel_mon
        if sel["sep_edges"] != sel["ptap_edges"]:
            raise AssertionError(
                f"SEP STAP selected TMS sep_edges={sel['sep_edges']} "
                f"want ptap_edges={sel['ptap_edges']}"
            )
        if sel["sep_edges"] <= unsel["sep_edges"]:
            raise AssertionError(
                f"SEP STAP selected TMS not distinguishable from unselected "
                f"sel={sel['sep_edges']} unsel={unsel['sep_edges']}"
            )
        sb.expect_eq("CHK-SEP-DMI-STAP-SEL", sel["sep_edges"], sel["ptap_edges"])
        self.s2_ok = True
        self._log(
            f"CHK-SEP-DMI-STAP-SEL sep_edges={sel['sep_edges']} ptap_edges={sel['ptap_edges']}"
        )

        if DTP_IR_DMI != EL2_IR_DMI:
            raise AssertionError(
                f"DTP RISC-V reserved DMI encoding 0x{DTP_IR_DMI:x} is not EL2 IR 5'h11"
            )
        await jtag.shift_ir(DTP_IR_DMI, width=DTP_IR_WIDTH, back_to_rti=True)
        req = pack_dmi(DMSTATUS_ADDR, 0, op=1)
        await self._dmi_scan(jtag, req)
        captured = await self._dmi_scan(jtag, pack_dmi(0, 0, op=0))
        _, data, status = unpack_dmi(captured)
        version = data & 0xF
        self._log(
            f"CHK-SEP-DMI-DMSTATUS raw=0x{captured:x} data=0x{data:08x} "
            f"status={status} version={version}"
        )
        if status != 0:
            raise AssertionError(
                f"DMI dmstatus status={status} data=0x{data:08x} "
                f"(IR=5'h11 through dmi_mux)"
            )
        if version == 0:
            raise AssertionError(
                f"DMI dmstatus version=0 data=0x{data:08x}; "
                "dmi_mux core aperture returned no debug module"
            )
        sb.expect_eq(
            "CHK-SEP-DMI-DMSTATUS",
            (status, version != 0),
            (0, True),
            evidence="CHK-SEP-DMI-DMSTATUS",
        )
        self.dmstatus = data
        self.s3_ok = True
