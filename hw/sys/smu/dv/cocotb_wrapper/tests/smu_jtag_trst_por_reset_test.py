# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_jtag_trst_por_reset_test - TRST_n and power-on reset put the primary TAP in Test-Logic-Reset.

Sources: hw/ip/jtag/jtag_ptap/doc/architecture.adoc (TAP Controller State Machine, Reset
Hierarchy, TDO Retiming, ID Code), hw/ip/jtag/jtag_ptap/doc/interface.adoc (Instruction encodings),
hw/sys/dtp/doc/clk_rst.adoc (Reset Architecture, Reset Distribution), hw/sys/smu/doc/port_table.adoc

Expected values: Test-Logic-Reset is jtag_ptap_state 16'h0001 and Run-Test/Idle 16'h0002 (one-hot
encodings of the state machine table). The combined reset jtag_trst_n = pwr_on_rst_ni && TRST_n
holds the controller in Test-Logic-Reset without TCK, and Test-Logic-Reset loads IDCODE into the
instruction register, so the decoded instruction is the one-hot 64'h2 (bit <opcode>) and a DR scan
returns the IDCODE 0x0000_0001. A TMS-low TCK is the first one that leaves Test-Logic-Reset. The
reset values of jtag_tdo and jtag_tdo_oen are not documented: the samples after TRST_n,
after power-on reset and after both are compared with each other and logged. How powergood_stable
is derived is not documented: the test drives powergood_i and observes the TAP only.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagState
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_BYPASS,
    DTP_IR_WIDTH,
    dtp_ir_opcode,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from smu_base_test import smu_base_test

TLR = int(OcahJtagState.TEST_LOGIC_RESET)
RTI = int(OcahJtagState.RUN_TEST_IDLE)
IDCODE_DECODED = 1 << 1
BOUND_TCK = 2000
BOUND_REF = 2000
IDCODE_LEN = 32
RELEASE_TMS_HIGH_TCKS = 8
DEBUG_CONTROL_OPCODE = 0x18
EXPECTED_TIMEOUT_PATHS = 33
STEP_ORDER = [f"S{i}" for i in range(1, 8)]

# interface.adoc "Instruction encodings"
PRIOR_INSTRUCTIONS = (
    ("BYPASS", "BYPASS_3F", 0x3F),
    ("DEBUG_CONTROL", "DEBUG_CONTROL", 0x18),
    ("JTAG_CAPS", "JTAG_CAPS", 0x19),
    ("IC_RESET", "IC_RESET", 0x0D),
    ("TAP_3DCR", "TAP_3DCR", 0x0E),
    ("SELECT_IJTAG", "SELECT_IJTAG", 0x1A),
    ("TMP_STATUS", "TMP_STATUS", 0x0C),
)
assert DTP_IR_BYPASS == 0x3F
assert DTP_DEFAULT_IDCODE == 0x0000_0001


def _sample(signal, name: str) -> int:
    val = signal.value
    if isinstance(val, int):
        return val
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_jtag_trst_por_reset_test(smu_base_test):
    """TRST_n and powergood_i each reset the TAP asynchronously; the reset holds and releases."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        self.timeout_paths: list[str] = []
        self.steps: list[str] = []

        await self.cfg.reset_done.wait()
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()

        # S1 SETUP
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await self._confirm_state(jtag, RTI, "s1_rti", hold_tms=0)
        idcode = await self._idcode_read(jtag, "S1")
        self.logger.info("S1 TAP state=0x%x IDCODE=0x%08x", self._state(), idcode)
        sb.expect_eq("S1 IDCODE after reset_tap", idcode, DTP_DEFAULT_IDCODE)
        self._step("S1")

        # S2 RSTH_POR_ONLY
        pre = await self._park_shift_dr(jtag)
        assert _sample(dut.jtag_trst, "jtag_trst") == 1, "S2 requires TRST_n released"
        dut.powergood_i.value = 0
        in_reset = await self._wait_tap_ref(dut, TLR, "s2_por_tlr")
        await self._restore_powergood(dut, "s2")
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        decoded = _sample(dut.tb_ptap_inst_decoded, "tb_ptap_inst_decoded")
        await jtag.goto_state(OcahJtagState.SHIFT_DR)
        dr = await self._dr_scan(jtag, "S2 DR scan")
        self.logger.info(
            "S2 pre=0x%x state_in_reset=0x%x decoded=0x%x dr=0x%08x", pre, in_reset, decoded, dr
        )
        sb.expect_eq(
            "por-only: (pre != TLR, state in reset, decoded, DR scan)",
            (pre != TLR, in_reset, decoded, dr),
            (True, TLR, IDCODE_DECODED, DTP_DEFAULT_IDCODE),
            evidence="RSTH_POR_ONLY",
        )
        self._step("S2")

        # S3 RSTH_TRST_ONLY
        cells = []
        for label, tck_cycles, tms in (
            ("tms0", 8, 0),
            ("tms1", 1, 1),
            ("stopped", 0, 0),
        ):
            pre = await self._park_shift_dr(jtag)
            await jtag.assert_trst(tck_cycles=tck_cycles, tms=tms)
            state = await self._wait_tap_ref(dut, TLR, f"s3_trst_{label}_tlr")
            await jtag.release_trst()
            jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
            await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
            cells.append((pre != TLR, state))
        self.logger.info("S3 (pre != TLR, state) tms0/tms1/stopped: %s", cells)
        sb.expect_eq(
            "trst-only: (pre != TLR, state) with TCK running TMS0, TMS1 and stopped",
            cells,
            [(True, TLR)] * 3,
            evidence="RSTH_TRST_ONLY",
        )
        self._step("S3")

        # S4 RSTH_RST_COMB
        comb = []
        pre = await self._park_shift_dr(jtag)
        comb.append(pre != TLR)
        await jtag.assert_trst(tck_cycles=0)
        dut.powergood_i.value = 0
        comb.append(await self._wait_tap_ref(dut, TLR, "s4_both_tlr"))
        comb.append(await self._tms_low_tck(jtag))
        await jtag.release_trst()
        comb.append(await self._sample_ref(dut))
        comb.append(await self._tms_low_tck(jtag))
        await self._restore_powergood(dut, "s4_a")
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await jtag.step_tms(0)
        comb.append(self._state())

        pre = await self._park_shift_dr(jtag)
        comb.append(pre != TLR)
        await jtag.assert_trst(tck_cycles=0)
        dut.powergood_i.value = 0
        comb.append(await self._wait_tap_ref(dut, TLR, "s4_both2_tlr"))
        await self._restore_powergood(dut, "s4_b")
        comb.append(await self._sample_ref(dut))
        comb.append(await self._tms_low_tck(jtag))
        await jtag.release_trst()
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await jtag.step_tms(0)
        comb.append(self._state())
        self.logger.info("S4 samples: %s", [hex(c) if not isinstance(c, bool) else c for c in comb])
        sb.expect_eq(
            "combined reset: pre-state flags, states while a reset holds, first TMS-low after",
            comb,
            [True, TLR, TLR, TLR, TLR, RTI, True, TLR, TLR, TLR, RTI],
            evidence="RSTH_RST_COMB",
        )
        self._step("S4")

        # S5 RSTH_RST_RELEASE
        await jtag.shift_ir(DEBUG_CONTROL_OPCODE, width=DTP_IR_WIDTH, back_to_rti=True)
        decoded_before = _sample(dut.tb_ptap_inst_decoded, "tb_ptap_inst_decoded")
        if decoded_before != 1 << DEBUG_CONTROL_OPCODE:
            raise AssertionError(
                f"S5 DEBUG_CONTROL not loaded: decoded=0x{decoded_before:x} "
                f"expect=0x{1 << DEBUG_CONTROL_OPCODE:x}"
            )
        self.logger.info("S5 decoded before TRST=0x%x", decoded_before)
        await jtag.assert_trst(tck_cycles=0)
        await self._wait_tap_ref(dut, TLR, "s5_trst_tlr")
        decoded_held = _sample(dut.tb_ptap_inst_decoded, "tb_ptap_inst_decoded")
        self.logger.info("S5 decoded while TRST held=0x%x", decoded_held)
        await jtag.release_trst()
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        held = []
        for _ in range(RELEASE_TMS_HIGH_TCKS):
            await jtag.step_tms(1)
            held.append(self._state())
        decoded_after = _sample(dut.tb_ptap_inst_decoded, "tb_ptap_inst_decoded")
        await jtag.step_tms(0)
        first_low = self._state()
        await jtag.goto_state(OcahJtagState.SHIFT_DR)
        dr = await self._dr_scan(jtag, "S5 DR scan")
        self.logger.info(
            "S5 held=%s decoded_after=0x%x first_low=0x%x dr=0x%08x",
            held,
            decoded_after,
            first_low,
            dr,
        )
        sb.expect_eq(
            "release: DEBUG_CONTROL loaded before TRST, TLR under TMS high with IDCODE decoded, "
            "first TMS-low gives RTI, DR scan before any IR scan",
            (decoded_before, held, decoded_after, first_low, dr),
            (
                1 << DEBUG_CONTROL_OPCODE,
                [TLR] * RELEASE_TMS_HIGH_TCKS,
                IDCODE_DECODED,
                RTI,
                DTP_DEFAULT_IDCODE,
            ),
            evidence="RSTH_RST_RELEASE",
        )
        self._step("S5")

        # S6 RSTH_TLR_IDCODE
        results = []
        for name, helper_name, opcode in PRIOR_INSTRUCTIONS:
            assert dtp_ir_opcode(helper_name) == opcode, f"{name} opcode"
            await jtag.shift_ir(opcode, width=DTP_IR_WIDTH, back_to_rti=True)
            loaded = _sample(dut.tb_ptap_inst_decoded, "tb_ptap_inst_decoded")
            if loaded != 1 << opcode:
                raise AssertionError(
                    f"S6 prior:{name} not loaded: decoded=0x{loaded:x} expect=0x{1 << opcode:x}"
                )
            for _ in range(5):
                await jtag.step_tms(1)
            await self._confirm_state(jtag, TLR, f"s6_{name.lower()}_tlr", hold_tms=1)
            decoded = _sample(dut.tb_ptap_inst_decoded, "tb_ptap_inst_decoded")
            await jtag.goto_state(OcahJtagState.SHIFT_DR)
            dr = await self._dr_scan(jtag, f"S6 prior:{name} DR scan")
            results.append((decoded, dr))
        self.logger.info("S6 (decoded, dr) per prior instruction: %s", results)
        sb.expect_eq(
            "Test-Logic-Reset loads IDCODE for every prior instruction",
            results,
            [(IDCODE_DECODED, DTP_DEFAULT_IDCODE)] * len(PRIOR_INSTRUCTIONS),
            evidence="RSTH_TLR_IDCODE",
        )
        self._step("S6")

        # S7 RSTH_TDO_RST
        legs = {}
        pre_pairs = {}
        await self._park_shift_dr(jtag)
        pre_pairs["trst"] = await self._tdo_pair(dut)
        await jtag.assert_trst(tck_cycles=0)
        await self._wait_tap_ref(dut, TLR, "s7_trst_tlr")
        low = await self._tdo_pair(dut)
        await jtag.release_trst()
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        legs["trst"] = (low, await self._tdo_pair(dut))

        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await self._park_shift_dr(jtag)
        pre_pairs["por"] = await self._tdo_pair(dut)
        dut.powergood_i.value = 0
        await self._wait_tap_ref(dut, TLR, "s7_por_tlr")
        low = await self._tdo_pair(dut)
        await self._restore_powergood(dut, "s7_por")
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        legs["por"] = (low, await self._tdo_pair(dut))

        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await self._park_shift_dr(jtag)
        pre_pairs["both"] = await self._tdo_pair(dut)
        await jtag.assert_trst(tck_cycles=0)
        dut.powergood_i.value = 0
        await self._wait_tap_ref(dut, TLR, "s7_both_tlr")
        low = await self._tdo_pair(dut)
        await self._restore_powergood(dut, "s7_both")
        await jtag.release_trst()
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        legs["both"] = (low, await self._tdo_pair(dut))
        self.logger.info(
            "S7 (jtag_tdo, jtag_tdo_oen) before reset in Shift-DR under BYPASS: %s; "
            "while reset held / after release: %s; the reset values are not documented and are not "
            "compared with a constant",
            pre_pairs,
            legs,
        )
        sb.expect_eq(
            f"jtag_tdo/jtag_tdo_oen equal after TRST_n, power-on reset and both: {legs}",
            (legs["trst"] == legs["por"], legs["por"] == legs["both"]),
            (True, True),
            evidence="RSTH_TDO_RST",
        )
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        self._step("S7")

        # S8 CHK-TIMEOUT-PATHS
        for line in self.timeout_paths:
            self.logger.info("TIMEOUT-PATH %s", line)
        assert not any("EXPIRED" in line for line in self.timeout_paths)
        sb.expect_eq(
            "bounded wait sites",
            len(self.timeout_paths),
            EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step("PASS")
        sb.expect_eq(
            "ordered step fence",
            self.steps,
            [*STEP_ORDER, "PASS"],
            evidence="CHK-NONVAC",
        )
        self.logger.info("CHK-NONVAC: PASS (ordered fence S1<S2<...<S7<PASS)")
        assert _sample(dut.jtag_trst, "jtag_trst") == 1
        assert _sample(dut.powergood_i, "powergood_i") == 1

    def _step(self, step_id: str) -> None:
        self.steps.append(step_id)
        self.logger.info("STEP %s done", step_id)

    def _record(self, label: str, bound: int, last: str) -> None:
        self.timeout_paths.append(f"{label}: bound={bound} ok last={last}")

    def _state(self) -> int:
        return _sample(cocotb.top.jtag_ptap_state, "jtag_ptap_state")

    async def _sample_ref(self, dut) -> int:
        await RisingEdge(dut.clk_ref_i)
        return self._state()

    async def _tms_low_tck(self, jtag) -> int:
        """One TMS-low TCK while a reset holds; the driver model stays in Test-Logic-Reset."""
        await jtag.step_tms(0)
        state = self._state()
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        return state

    async def _tdo_pair(self, dut) -> tuple[int, int]:
        await RisingEdge(dut.clk_ref_i)
        return (
            _sample(dut.jtag_tdo, "jtag_tdo"),
            _sample(dut.jtag_tdo_oen, "jtag_tdo_oen"),
        )

    async def _park_shift_dr(self, jtag) -> int:
        """Load BYPASS and park in Shift-DR; return the state, which must not be TLR."""
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await jtag.shift_ir(DTP_IR_BYPASS, width=DTP_IR_WIDTH, back_to_rti=False)
        await jtag.goto_state(OcahJtagState.SHIFT_DR)
        pre = self._state()
        if pre == TLR:
            raise AssertionError("pre-reset state is already Test-Logic-Reset; the cell is vacuous")
        return pre

    async def _dr_scan(self, jtag, where: str) -> int:
        """DR scan from Shift-DR under the current IR; TDO must be resolvable while driven."""
        dut = cocotb.top
        bad: list[str] = []
        driven = [0]

        async def watch() -> None:
            while True:
                await RisingEdge(dut.jtag_tck)
                oen = dut.jtag_tdo_oen.value
                tdo = dut.jtag_tdo.value
                if not oen.is_resolvable:
                    bad.append(f"jtag_tdo_oen={oen}")
                elif int(oen):
                    if jtag.get_current_state() is OcahJtagState.SHIFT_DR:
                        driven[0] += 1
                    if not tdo.is_resolvable:
                        bad.append(f"jtag_tdo={tdo}")

        watcher = cocotb.start_soon(watch())
        try:
            value = await jtag.shift_dr(0, IDCODE_LEN, back_to_rti=True)
        finally:
            watcher.cancel()
        require_jtag_tdo_resolved(where)
        if bad:
            raise AssertionError(f"X/Z on TDO during {where}: {bad[:8]}")
        if driven[0] < IDCODE_LEN:
            raise AssertionError(f"{where}: {driven[0]} driven Shift-DR TDO bits")
        return int(value)

    async def _idcode_read(self, jtag, where: str) -> int:
        await jtag.shift_ir(dtp_ir_opcode("IDCODE"), width=DTP_IR_WIDTH, back_to_rti=False)
        await jtag.goto_state(OcahJtagState.SHIFT_DR)
        return await self._dr_scan(jtag, f"{where} IDCODE scan")

    async def _confirm_state(self, jtag, expect: int, label: str, *, hold_tms: int) -> None:
        """Bounded TCK wait for the TAP state; hold_tms is driven between samples."""
        last = None
        for _ in range(BOUND_TCK):
            last = self._state()
            if last == expect:
                self._record(label, BOUND_TCK, f"0x{last:x}")
                return
            await jtag.step_tms(hold_tms)
        self.timeout_paths.append(f"{label}: bound={BOUND_TCK} EXPIRED last=0x{last:x}")
        raise AssertionError(f"TIMEOUT {label}: bound={BOUND_TCK} last_state=0x{last:x}")

    async def _wait_tap_ref(self, dut, expect: int, label: str) -> int:
        last = None
        for _ in range(BOUND_REF):
            await RisingEdge(dut.clk_ref_i)
            last = self._state()
            if last == expect:
                self._record(label, BOUND_REF, f"0x{last:x}")
                return last
        self.timeout_paths.append(f"{label}: bound={BOUND_REF} EXPIRED last=0x{last:x}")
        raise AssertionError(f"TIMEOUT {label}: bound={BOUND_REF} last_state=0x{last:x}")

    async def _wait_high(self, dut, signal, label: str) -> None:
        last = None
        for _ in range(BOUND_REF):
            await RisingEdge(dut.clk_ref_i)
            last = signal.value
            if last.is_resolvable and int(last) == 1:
                self._record(label, BOUND_REF, "1")
                return
        self.timeout_paths.append(f"{label}: bound={BOUND_REF} EXPIRED last={last}")
        raise AssertionError(f"TIMEOUT {label}: bound={BOUND_REF} last={last}")

    async def _restore_powergood(self, dut, leg: str) -> None:
        dut.powergood_i.value = 1
        await self._wait_high(dut, dut.obs_powergood_stable_o, f"{leg}_pg_stable")
        await self._wait_high(dut, dut.rst_cold_n_o, f"{leg}_cold_n")
        await self._wait_high(dut, dut.rst_primary_smc_clk_n_o, f"{leg}_smc_n")
