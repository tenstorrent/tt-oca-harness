# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP TAP → SEP debug-module DMI on the SEP=1 wrapper.

S0: the lifecycle posture leaves SEP debug open. The entry names a TEST_DEV
    shadow image; the exported lc_state must leave its pre-sense value and
    `lcc_dbg_disable_o` must read the posture the lifecycle table gives that
    state (every path open), since the DTP gates the SEP STAP host interface
    with `dbg_disable_i.stap_sep` (integrator guide, STAP Scan Chain Topology).
S1: PTAP IDCODE is the configured IEEE packing.
S2: TAP_3DCR selects the SEP STAP; host TMS then follows the PTAP, and the
    PTAP IDCODE reads back through the spliced network at the depth the chain
    layout gives it.
S3: with the SEP TAP's IR loaded with dmi through the same network, the
    debugger's first act is a dmcontrol write setting dmactive (RISC-V Debug
    Specification: the module holds its reset state until dmactive is 1); a
    DMI read of dmstatus then completes with status 0 and reports the
    debug-spec version the SEP core implements.

While the PTAP 3DCR select is set, the STAP chain replaces the TDR mux output
on every IR and DR scan (jtag_ptap architecture, "STAP selection"). The chain
carries one SIB flop per STAP in chain order, and a selected STAP splices its
host TAP's register TDI-side of its own SIB (DTP scan reference model,
``chain_layout``): a scan is the PTAP register, the SIBs of the STAPs ahead of
the SEP, the SEP TAP's register, the SEP's SIB, then the SIBs behind it. Every
scan after selection is composed over that full network; a scan sized for the
PTAP register alone lands its bits in the SEP TAP and the SIBs instead.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagMasterSequence, OcahJtagState

from seq_lib.smu_boundary_regs import (
    SMU_SEP_STAP_ORDER,
    ptap_prefixed,
    stap_3dcr_scan_word,
    stap_sib_pattern,
)
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    PTAP_3DCR_WIDTH,
    dtp_ir_opcode,
    make_smu_jtag_tap,
    ptap_3dcr_value,
)
from seq_lib.smu_lifecycle_table import (
    LC_STATE_PRESENSE,
    lc_raw_from_shadow_preload,
    lc_state_name,
    posture,
)

# SEP debug TAP: RISC-V Debug Specification DTM. IR is 5 bits; dtmcs/dmi are
# the spec's 0x10/0x11; an unrecognised IR is BYPASS (IEEE 1149.1).
SEP_TAP_IR_WIDTH = 5
SEP_TAP_IR_BYPASS = 0x1F
SEP_TAP_IR_DMI = 0x11
DMI_ABITS = 7
DMI_DR_WIDTH = DMI_ABITS + 34
DMI_OP_NOP = 0
DMI_OP_READ = 1
DMI_OP_WRITE = 2
DMI_STATUS_OK = 0
DMCONTROL_ADDR = 0x10
DMCONTROL_DMACTIVE = 0x1
DMSTATUS_ADDR = 0x11
# RISC-V Debug Specification, dmstatus.version: 2 encodes specification 0.13,
# the debug specification the VeeR EL2 Programmer's Reference Manual names.
DMSTATUS_VERSION_SPEC_0_13 = 2
# TCKs in Run-Test/Idle between the DMI request scan and the scan that captures
# its result, so the DTM's request crosses to the debug module and back.
DMI_IDLE_TCKS = 16
IDCODE_DR_WIDTH = 32
# SIB flops ahead of the SEP's host segment, and the SEP's own SIB plus those behind it.
SIBS_BEFORE_SEP = SMU_SEP_STAP_ORDER.index("sep")
SIBS_FROM_SEP = len(SMU_SEP_STAP_ORDER) - SIBS_BEFORE_SEP
EDGE_SAMPLE_CYCLES = 2000
MIN_PTAP_TMS_EDGES = DTP_IR_WIDTH
POSTURE_SETTLE_POLLS = 500
POSTURE_FOLLOW_CYCLES = 200

# Bench taps published by tb_wrapper_top: the SEP STAP TCK/TMS as the DTP
# drives them. Struct members of an internal net are not addressable from
# cocotb under Verilator, so the bench brings them out.
SEP_STAP_TMS = "tb_stap_sep_tms"
SEP_STAP_TCK = "tb_stap_sep_tck"


def pack_dmi(addr: int, data: int, op: int, *, abits: int = DMI_ABITS) -> int:
    return (
        ((int(addr) & ((1 << abits) - 1)) << 34)
        | ((int(data) & 0xFFFF_FFFF) << 2)
        | (int(op) & 0x3)
    )


def unpack_dmi(raw: int) -> tuple[int, int, int]:
    op = int(raw) & 0x3
    data = (int(raw) >> 2) & 0xFFFF_FFFF
    addr = (int(raw) >> 34) & 0x7F
    return addr, data, op


def network_scan(ptap_reg: int, ptap_width: int, sep_reg: int, sep_width: int) -> tuple[int, int]:
    """A scan over the network with the SEP STAP selected and every SIB closed.

    TDI-nearest first: the PTAP register, the SIBs ahead of the SEP, the SEP
    TAP's register, the SEP's SIB and the SIBs behind it, all SIB bits 0.
    """
    width = ptap_width + SIBS_BEFORE_SEP + sep_width + SIBS_FROM_SEP
    value = int(ptap_reg) << (SIBS_BEFORE_SEP + sep_width + SIBS_FROM_SEP)
    value |= int(sep_reg) << SIBS_FROM_SEP
    return value, width


def network_ir_scan(ptap_instr: int, sep_ir: int) -> tuple[int, int]:
    return network_scan(ptap_instr, DTP_IR_WIDTH, sep_ir, SEP_TAP_IR_WIDTH)


def sep_dr_from_capture(captured: int, sep_width: int) -> int:
    """The SEP register's segment of a network capture, natural bit order."""
    return (int(captured) >> SIBS_FROM_SEP) & ((1 << sep_width) - 1)


def ptap_dr_from_capture(captured: int, ptap_width: int, sep_width: int) -> int:
    shift = SIBS_BEFORE_SEP + sep_width + SIBS_FROM_SEP
    return (int(captured) >> shift) & ((1 << ptap_width) - 1)


class smu_dtp_sep_dm_dmi_test_seq:
    """Select the SEP STAP and read dmstatus through the SEP TAP's dmi register."""

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
        return sample(hier(self.dut, path), path) & 1

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
            "sep", config_hold=1, stap_sel=1, tms_hold=1, sib_en=0
        )
        value, width = ptap_prefixed(stap_word, stap_width)
        await jtag.shift_dr(value, width, back_to_rti=True)
        # The selected SEP TAP now sees the PTAP's TMS; two idle TCKs re-establish
        # lockstep in Run-Test/Idle before the first composed scan.
        await jtag.step_tms(0)
        await jtag.step_tms(0)
        self._log(
            f"OBS SEP STAP TAP_3DCR selected sib=0x{sib:x}->{sib_word:x}/{sib_width} "
            f"3dcr=0x{stap_word:x}->{value:x}/{width} order={SMU_SEP_STAP_ORDER}"
        )

    async def _dmi_scan(self, jtag, req: int) -> int:
        """One dmi DR scan through the network; returns the SEP's captured dmi word."""
        value, width = network_scan(
            ptap_3dcr_value(config_hold=1, select=1), PTAP_3DCR_WIDTH, req, DMI_DR_WIDTH
        )
        captured = await jtag.shift_dr(value, width, back_to_rti=True)
        for _ in range(DMI_IDLE_TCKS):
            await jtag.step_tms(0)
        return sep_dr_from_capture(captured, DMI_DR_WIDTH)

    async def _require_debug_open(self, sb) -> None:
        """The SEP STAP is reachable only when the lifecycle posture leaves debug open."""
        preload = cocotb.plusargs.get("sep_shadow_reg_preload")
        assert preload is not None, (
            "+sep_shadow_reg_preload is required: it names the lifecycle state under test"
        )
        state = lc_state_name(lc_raw_from_shadow_preload(str(preload)))
        want = posture(state)
        assert want.all_open, (
            f"the entry's shadow image encodes {state}, whose posture keeps debug disabled; "
            f"the SEP STAP cannot be selected under it"
        )
        for _ in range(POSTURE_SETTLE_POLLS):
            lc_state = sample(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o")
            if lc_state != LC_STATE_PRESENSE:
                break
            await ClockCycles(self.dut.clk_smu_i, 10)
        else:
            raise AssertionError(
                "lc_state never left its pre-sense value; the eFuse image was not applied"
            )
        await ClockCycles(self.dut.clk_smu_i, POSTURE_FOLLOW_CYCLES)
        lc_state = sample(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o")
        dbg_disable = sample(self.dut.lcc_dbg_disable_o, "lcc_dbg_disable_o")
        sb.expect_eq(f"lc_state exported for {state}", lc_state, want.lc_state)
        sb.expect_eq(f"dbg_disable posture for {state} (every debug path open)", dbg_disable, 0)
        self._log(
            f"OBS lifecycle posture {state}: lc_state=0x{lc_state:02x} "
            f"dbg_disable=0x{dbg_disable:04x}; the SEP STAP host interface is ungated"
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self._require_debug_open(sb)
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
        ir_value, ir_width = network_ir_scan(dtp_ir_opcode("IDCODE"), SEP_TAP_IR_BYPASS)
        await jtag.shift_ir(ir_value, width=ir_width, back_to_rti=True)
        dr_value, dr_width = network_scan(0, IDCODE_DR_WIDTH, 0, 1)
        captured = await jtag.shift_dr(dr_value, dr_width, back_to_rti=True)
        sel = await sel_mon
        spliced_idcode = ptap_dr_from_capture(captured, IDCODE_DR_WIDTH, 1)
        self._log(
            f"OBS network IDCODE scan width={dr_width} raw=0x{captured:x} "
            f"ptap_idcode=0x{spliced_idcode:08x}"
        )
        sb.expect_eq(
            "PTAP IDCODE at its network depth with the SEP STAP spliced",
            spliced_idcode,
            DTP_DEFAULT_IDCODE,
        )
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

        ir_value, ir_width = network_ir_scan(DTP_IR_TAP_3DCR, SEP_TAP_IR_DMI)
        await jtag.shift_ir(ir_value, width=ir_width, back_to_rti=True)
        await self._dmi_scan(jtag, pack_dmi(DMCONTROL_ADDR, DMCONTROL_DMACTIVE, op=DMI_OP_WRITE))
        await self._dmi_scan(jtag, pack_dmi(DMSTATUS_ADDR, 0, op=DMI_OP_READ))
        captured = await self._dmi_scan(jtag, pack_dmi(DMSTATUS_ADDR, 0, op=DMI_OP_NOP))
        _, data, status = unpack_dmi(captured)
        version = data & 0xF
        self._log(
            f"CHK-SEP-DMI-DMSTATUS dmi=0x{captured:x} dmstatus=0x{data:08x} "
            f"status={status} version={version}"
        )
        sb.expect_eq(
            "CHK-SEP-DMI-DMSTATUS",
            (status, version),
            (DMI_STATUS_OK, DMSTATUS_VERSION_SPEC_0_13),
            evidence="CHK-SEP-DMI-DMSTATUS",
        )
        self.dmstatus = data
        self.s3_ok = True
