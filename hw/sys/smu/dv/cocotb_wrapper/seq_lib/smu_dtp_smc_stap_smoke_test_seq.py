# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP-SMC-STAP: TRST + TAP_3DCR select via select-gated host TMS.

S1: PTAP TRST (active-low) is visible on ``tb_stap_smc_trst_n``.
S2: Same IDCODE while SMC STAP is *not* selected: ``tb_stap_smc_tms`` stays
    at tms_hold and must *not* track ``jtag_tms``. After TAP_3DCR selects SMC,
    the same IDCODE must make host TMS follow PTAP TMS (stap_sel mux).
S3: TRST restores the 2-bit PTAP 3DCR: an IDCODE scan after the TRST and
    before any re-select leaves ``tb_stap_smc_tms`` and ``tb_stap_smc_tdo_oen``
    quiet, as the unselected control does; then re-select, IDCODE with
    non-zero DR.

TMS is held low through every TRST assert here, so the TAP has no path to
Test-Logic-Reset other than the reset itself.

TDI/TCK fan out without ``stap_sel``; they are not the select proof.
``tb_stap_smc_tdo_oen`` is logged when live. IO + SMC + SEP debug + extra0 on the wrapper.
Not claimed: SMC DTM abstract commands, STAP slave BFM IDCODE, real LCC.
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
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_IDCODE,
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    PTAP_3DCR_WIDTH,
    make_smu_jtag_tap,
    ptap_3dcr_value,
)

EDGE_SAMPLE_CYCLES = 2000
DR_WIDTH = 32
EXPECTED_SHIFT_TCKS = DTP_IR_WIDTH + DR_WIDTH
# TAP IR+DR from RTI produces many TMS edges; unselected host TMS must stay quiet.
MIN_PTAP_TMS_EDGES = DTP_IR_WIDTH
TRST_CYCLES = 8
PAYLOAD = 0x35353535


class smu_dtp_smc_stap_smoke_test_seq:
    """Prove SMC STAP TRST + TAP_3DCR select via TB observe pins."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _observe_scan(self, cycles: int) -> dict[str, int]:
        """TCK-sync TMS follow/hold + tdo_oen high TCK count during a scan."""
        prev_tck = self._sample_bit("tb_stap_smc_tck")
        prev_ptap = self._sample_bit("jtag_tms")
        prev_smc = self._sample_bit("tb_stap_smc_tms")
        tck_n = 0
        mismatch = 0
        ptap_edges = 0
        smc_edges = 0
        oen_tcks = 0
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_ref_i)
            tck = self._sample_bit("tb_stap_smc_tck")
            ptap = self._sample_bit("jtag_tms")
            smc = self._sample_bit("tb_stap_smc_tms")
            oen = self._sample_bit("tb_stap_smc_tdo_oen")
            if ptap != prev_ptap:
                ptap_edges += 1
                prev_ptap = ptap
            if smc != prev_smc:
                smc_edges += 1
                prev_smc = smc
            if tck == 1 and prev_tck == 0:
                tck_n += 1
                if smc != ptap:
                    mismatch += 1
                if oen:
                    oen_tcks += 1
            prev_tck = tck
        return {
            "tck_n": tck_n,
            "mismatch": mismatch,
            "ptap_edges": ptap_edges,
            "smc_edges": smc_edges,
            "oen_tcks": oen_tcks,
        }

    def _hier_bit(self, path: str) -> int | None:
        obj = self.dut
        for part in path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        val = obj.value
        if not val.is_resolvable:
            return None
        return int(val) & 1

    async def _select_smc_stap(self, jtag) -> None:
        """TAP_3DCR select matching dtp_scan_base_test_seq.select_stap('smc').

        Load IR once. STAP scan_ctrl ORs IR update_en, so reloading TAP_3DCR
        would Update-IR the SIB/3DCR chain and close the SMC SIB.
        """
        await jtag.shift_ir(DTP_IR_TAP_3DCR, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(
            ptap_3dcr_value(config_hold=1, select=1),
            PTAP_3DCR_WIDTH,
            back_to_rti=True,
        )
        await jtag.step_tms(0)
        await jtag.step_tms(0)

        sib = stap_sib_pattern("smc", 1)
        sib_word, sib_width = ptap_prefixed(sib, len(SMU_SEP_STAP_ORDER))
        await jtag.shift_dr(sib_word, sib_width, back_to_rti=True)

        stap_word, stap_width = stap_3dcr_scan_word(
            "smc", config_hold=1, stap_sel=1, tms_hold=1, sib_en=0
        )
        value, width = ptap_prefixed(stap_word, stap_width)
        await jtag.shift_dr(value, width, back_to_rti=True)
        sec = self._hier_bit(
            "u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_jtag2axi_security_disable"
        )
        self._log(
            f"OBS SMC STAP TAP_3DCR selected "
            f"sib=0x{sib:x}->{sib_word:x}/{sib_width} "
            f"3dcr=0x{stap_word:x}->{value:x}/{width} order={SMU_SEP_STAP_ORDER} "
            f"j2a_security_disable={sec}"
        )

    async def _scan_idcode(self, jtag) -> None:
        await jtag.shift_ir(DTP_IR_IDCODE, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(0, DR_WIDTH, back_to_rti=True)

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
        sb.expect_eq("CHK-DTP-SMC-STAP-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        # S1: TRST (active-low) reaches SMC STAP host trst_n
        await jtag.assert_trst(tck_cycles=TRST_CYCLES, tms=0)
        trst_asserted = self._sample_bit("tb_stap_smc_trst_n")
        if trst_asserted != 0:
            raise AssertionError(f"SMC STAP trst_n during TRST want 0 got {trst_asserted}")
        await jtag.release_trst()
        await ClockCycles(self.dut.clk_ref_i, 4)
        trst_released = self._sample_bit("tb_stap_smc_trst_n")
        if trst_released != 1:
            raise AssertionError(f"SMC STAP trst_n after TRST release want 1 got {trst_released}")
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        self.s1_ok = True
        self._log("CHK-DTP-SMC-STAP-TRST: trst_n 0->1 on tb_stap_smc_trst_n")
        sb.expect_eq("CHK-DTP-SMC-STAP-TRST", (trst_asserted, trst_released), (0, 1))

        # Unselected-scan control: same IDCODE while stap_sel is still 0.
        # Host TMS must stay at tms_hold (0) while PTAP TMS executes the scan.
        unsel_mon = cocotb.start_soon(self._observe_scan(EDGE_SAMPLE_CYCLES))
        await self._scan_idcode(jtag)
        unsel = await unsel_mon
        if unsel["ptap_edges"] < MIN_PTAP_TMS_EDGES:
            raise AssertionError(
                f"unselected IDCODE PTAP TMS edges={unsel['ptap_edges']} "
                f"want >={MIN_PTAP_TMS_EDGES} (scan did not run)"
            )
        if unsel["smc_edges"] != 0:
            raise AssertionError(
                "SMC STAP TMS toggled while unselected: "
                f"smc_edges={unsel['smc_edges']} want 0 "
                f"(ptap_edges={unsel['ptap_edges']} mismatch={unsel['mismatch']})"
            )
        if unsel["oen_tcks"] != 0:
            raise AssertionError(
                f"SMC STAP tdo_oen during unselected IDCODE oen_tcks={unsel['oen_tcks']} want 0"
            )
        self._log(
            f"CHK-DTP-SMC-STAP-UNSEL: smc_tms_edges={unsel['smc_edges']} "
            f"ptap_edges={unsel['ptap_edges']} mismatch={unsel['mismatch']} "
            f"oen_tcks={unsel['oen_tcks']}"
        )
        sb.expect_eq("CHK-DTP-SMC-STAP-UNSEL", unsel["smc_edges"], 0)
        sb.expect_eq("CHK-DTP-SMC-STAP-UNSEL-OEN", unsel["oen_tcks"], 0)

        await self._select_smc_stap(jtag)

        # S2: same IDCODE after TAP_3DCR — host TMS must follow PTAP TMS
        sel_mon = cocotb.start_soon(self._observe_scan(EDGE_SAMPLE_CYCLES))
        await self._scan_idcode(jtag)
        sel = await sel_mon
        if sel["smc_edges"] != sel["ptap_edges"]:
            raise AssertionError(
                f"SMC STAP selected IDCODE smc_tms_edges={sel['smc_edges']} "
                f"want ptap_edges={sel['ptap_edges']} "
                f"(unsel_smc={unsel['smc_edges']} mismatch={sel['mismatch']} "
                f"oen_tcks={sel['oen_tcks']})"
            )
        if sel["smc_edges"] <= unsel["smc_edges"]:
            raise AssertionError(
                f"SMC STAP selected TMS not distinguishable from unselected "
                f"sel={sel['smc_edges']} unsel={unsel['smc_edges']}"
            )
        if sel["oen_tcks"] != EXPECTED_SHIFT_TCKS:
            raise AssertionError(
                f"SMC STAP selected IDCODE oen_tcks={sel['oen_tcks']} "
                f"want {EXPECTED_SHIFT_TCKS} (IR={DTP_IR_WIDTH}+DR={DR_WIDTH})"
            )
        if sel["mismatch"] != 0:
            raise AssertionError(
                f"SMC STAP selected IDCODE TMS mismatch={sel['mismatch']} "
                f"want 0 (host must follow PTAP on each TCK)"
            )
        self.s2_ok = True
        self._log(
            f"CHK-DTP-SMC-STAP-IDCODE: smc_tms_edges={sel['smc_edges']} "
            f"ptap_edges={sel['ptap_edges']} mismatch={sel['mismatch']} "
            f"oen_tcks={sel['oen_tcks']} unsel_smc={unsel['smc_edges']}"
        )
        sb.expect_eq(
            "CHK-DTP-SMC-STAP-IDCODE",
            sel["smc_edges"],
            sel["ptap_edges"],
            evidence="CHK-DTP-SMC-STAP-IDCODE",
        )
        sb.expect_eq(
            "CHK-DTP-SMC-STAP-IDCODE-OEN",
            sel["oen_tcks"],
            EXPECTED_SHIFT_TCKS,
            evidence="CHK-DTP-SMC-STAP-IDCODE",
        )
        sb.expect_eq(
            "CHK-DTP-SMC-STAP-IDCODE-TMS-MATCH",
            sel["mismatch"],
            0,
            evidence="CHK-DTP-SMC-STAP-IDCODE",
        )

        # S3: TRST restores the 2-bit PTAP 3DCR (config_hold holds it across
        # Test-Logic-Reset, so only the reset can clear the select). Before
        # any re-select, the same IDCODE scan as the unselected control must
        # leave host TMS and tdo_oen quiet.
        await jtag.assert_trst(tck_cycles=TRST_CYCLES, tms=0)
        await jtag.release_trst()
        await ClockCycles(self.dut.clk_ref_i, 4)
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        desel_mon = cocotb.start_soon(self._observe_scan(EDGE_SAMPLE_CYCLES))
        await self._scan_idcode(jtag)
        desel = await desel_mon
        if desel["ptap_edges"] < MIN_PTAP_TMS_EDGES:
            raise AssertionError(
                f"post-TRST IDCODE PTAP TMS edges={desel['ptap_edges']} "
                f"want >={MIN_PTAP_TMS_EDGES} (scan did not run)"
            )
        if desel["smc_edges"] != 0:
            raise AssertionError(
                "SMC STAP TMS still follows PTAP after TRST: "
                f"smc_edges={desel['smc_edges']} want 0 "
                f"(ptap_edges={desel['ptap_edges']} sel_before_trst={sel['smc_edges']})"
            )
        if desel["oen_tcks"] != 0:
            raise AssertionError(f"SMC STAP tdo_oen after TRST oen_tcks={desel['oen_tcks']} want 0")
        self._log(
            f"CHK-DTP-SMC-STAP-TRST-DESEL: smc_tms_edges={desel['smc_edges']} "
            f"ptap_edges={desel['ptap_edges']} oen_tcks={desel['oen_tcks']} "
            f"sel_before_trst={sel['smc_edges']}"
        )
        sb.expect_eq(
            "CHK-DTP-SMC-STAP-TRST-DESEL",
            (desel["smc_edges"], desel["oen_tcks"]),
            (0, 0),
            evidence="CHK-DTP-SMC-STAP-TRST-DESEL",
        )
        await self._select_smc_stap(jtag)
        byp_mon = cocotb.start_soon(self._observe_scan(EDGE_SAMPLE_CYCLES))
        await jtag.shift_ir(DTP_IR_IDCODE, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(PAYLOAD, DR_WIDTH, back_to_rti=True)
        byp = await byp_mon
        if byp["smc_edges"] != byp["ptap_edges"]:
            raise AssertionError(
                f"SMC STAP reselect payload smc_tms_edges={byp['smc_edges']} "
                f"want ptap_edges={byp['ptap_edges']} "
                f"mismatch={byp['mismatch']} oen_tcks={byp['oen_tcks']} "
                f"payload=0x{PAYLOAD:08x}"
            )
        if byp["smc_edges"] <= unsel["smc_edges"]:
            raise AssertionError(
                f"SMC STAP reselect TMS not distinguishable from unselected "
                f"byp={byp['smc_edges']} unsel={unsel['smc_edges']}"
            )
        if byp["oen_tcks"] != EXPECTED_SHIFT_TCKS:
            raise AssertionError(
                f"SMC STAP reselect payload oen_tcks={byp['oen_tcks']} "
                f"want {EXPECTED_SHIFT_TCKS} payload=0x{PAYLOAD:08x}"
            )
        if byp["mismatch"] != 0:
            raise AssertionError(
                f"SMC STAP reselect payload TMS mismatch={byp['mismatch']} "
                f"want 0 payload=0x{PAYLOAD:08x}"
            )
        self.s3_ok = True
        self._log(
            f"CHK-DTP-SMC-STAP-IDCODE-BFM: smc_tms_edges={byp['smc_edges']} "
            f"ptap_edges={byp['ptap_edges']} mismatch={byp['mismatch']} "
            f"oen_tcks={byp['oen_tcks']} payload=0x{PAYLOAD:08x}"
        )
        sb.expect_eq(
            "CHK-DTP-SMC-STAP-IDCODE-BFM",
            byp["smc_edges"],
            byp["ptap_edges"],
            evidence="CHK-DTP-SMC-STAP-IDCODE",
        )
        sb.expect_eq("CHK-DTP-SMC-STAP-PAYLOAD-OEN", byp["oen_tcks"], EXPECTED_SHIFT_TCKS)
        sb.expect_eq("CHK-DTP-SMC-STAP-PAYLOAD-TMS-MATCH", byp["mismatch"], 0)

        self._log(
            "PASS DTP-SMC-STAP "
            f"s1={self.s1_ok} s2={self.s2_ok} s3={self.s3_ok} "
            f"tms={sel['smc_edges']}/{byp['smc_edges']}"
        )
