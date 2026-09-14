# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_dtp_jtag_smoke_test (SMU_ALL_005).

DV-CARD:          SMU_ALL_005   ANCHOR: smu_dtp_jtag_smoke_test

Allocated (PTAP only):
  DTP-JTAG-PTAP.S1 — IDCODE instruction returns configured IDCODE fields
  DTP-JTAG-PTAP.S2 — BYPASS places a single-bit register between TDI and TDO
  DTP-JTAG-PTAP.S3 — TRST or power-on returns TAP to Test-Logic-Reset
    (required_cells: rst=TRST, rst=POR, state=Test-Logic-Reset)

No Force/deposit. No JTAG2AXI / OTP / STAP.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_WIDTH,
    make_smu_jtag_tap,
)


class smu_dtp_jtag_smoke_test_seq:
    """SMU_ALL_005: PTAP IDCODE / BYPASS / TRST+POR → TLR."""

    BYPASS_PATTERN = 0xA5A5_A5A5
    BYPASS_WIDTH = 32
    BOUND_TCK = 2000
    BOUND_REF = 2000
    POR_RECOVER_REF = 64
    TRST_CYCLES = 8
    # Real poll-with-expiry sites (each can hit EXPIRED):
    #   s1_rti, s2_idcode_rti, s3_select_dr, s3_capture_dr, s3_shift_dr,
    #   s3_update_dr, s3_back_rti, s4_trst_tlr, s4_por_tlr
    EXPECTED_TIMEOUT_PATHS = 9

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = time.monotonic()
        self._log(f"STEP {step_id}: {detail}")

    def _sample(self, signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    def _sample_tap_state(self) -> int:
        return self._sample(self.dut.jtag_ptap_state, "jtag_ptap_state")

    async def _wait_state_after_step(
        self,
        jtag,
        tms: int,
        expect: OcahJtagState,
        *,
        label: str,
    ) -> int:
        """Drive one TMS cycle then poll until expect (or EXPIRED)."""
        await jtag.step_tms(tms)
        last = self._sample_tap_state()
        if last == int(expect):
            self._timeout_paths.append(f"{label}: bound={self.BOUND_TCK} ok last=0x{last:x}")
            return last
        hold_tms = (
            0
            if expect
            in (
                OcahJtagState.SHIFT_DR,
                OcahJtagState.SHIFT_IR,
                OcahJtagState.RUN_TEST_IDLE,
                OcahJtagState.PAUSE_DR,
                OcahJtagState.PAUSE_IR,
            )
            else tms
        )
        for _ in range(self.BOUND_TCK - 1):
            await jtag.step_tms(hold_tms)
            last = self._sample_tap_state()
            if last == int(expect):
                self._timeout_paths.append(f"{label}: bound={self.BOUND_TCK} ok last=0x{last:x}")
                return last
        self._timeout_paths.append(
            f"{label}: bound={self.BOUND_TCK} EXPIRED last="
            f"{'None' if last is None else f'0x{last:x}'}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={self.BOUND_TCK} last_state={last} "
            f"expect={expect.name}(0x{int(expect):x})"
        )

    async def _wait_state(
        self,
        jtag,
        expect: OcahJtagState,
        *,
        label: str,
        hold_tms: int = 0,
    ) -> int:
        last = None
        for _ in range(self.BOUND_TCK):
            await jtag.step_tms(hold_tms)
            last = self._sample_tap_state()
            if last == int(expect):
                self._timeout_paths.append(f"{label}: bound={self.BOUND_TCK} ok last=0x{last:x}")
                return last
        self._timeout_paths.append(
            f"{label}: bound={self.BOUND_TCK} EXPIRED last="
            f"{'None' if last is None else f'0x{last:x}'}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={self.BOUND_TCK} last_state={last} "
            f"expect={expect.name}(0x{int(expect):x})"
        )

    async def _wait_tap_eq_ref(
        self,
        expect: OcahJtagState,
        *,
        label: str,
        bound: int | None = None,
    ) -> int:
        """Poll jtag_ptap_state on refclk (async TRST/POR paths)."""
        bound = self.BOUND_REF if bound is None else bound
        last = None
        for _ in range(bound):
            await RisingEdge(self.dut.clk_ref_i)
            last = self._sample_tap_state()
            if last == int(expect):
                self._timeout_paths.append(f"{label}: bound={bound} ok last=0x{last:x}")
                return last
        self._timeout_paths.append(
            f"{label}: bound={bound} EXPIRED last={'None' if last is None else f'0x{last:x}'}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={bound} last_state={last} "
            f"expect={expect.name}(0x{int(expect):x})"
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        jtag.init_signals()

        # ------------------------------------------------------------------
        # S1 SETUP
        # ------------------------------------------------------------------
        self._mark_step(
            "S1",
            "SETUP: clocks stable; bare tb_top JTAG pins ready for PTAP; "
            "baseline TAP reset then Run-Test/Idle",
        )
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        idle = self._sample_tap_state()
        if idle != int(OcahJtagState.RUN_TEST_IDLE):
            idle = await self._wait_state(jtag, OcahJtagState.RUN_TEST_IDLE, label="s1_rti")
        else:
            self._timeout_paths.append(f"s1_rti: bound={self.BOUND_TCK} ok last=0x{idle:x}")
        self._log(
            f"BASELINE: jtag_ptap_state=0x{idle:x} "
            f"(RUN_TEST_IDLE) idcode_expect=0x{DTP_DEFAULT_IDCODE:08x}"
        )

        # ------------------------------------------------------------------
        # S2 DTP-JTAG-PTAP.S1 IDCODE
        # ------------------------------------------------------------------
        self._mark_step(
            "S2",
            "ACTION/RESPONSE/EFFECT DTP-JTAG-PTAP.S1: load IDCODE IR; "
            "shift 32b DR; observe configured IDCODE fields on TDO",
        )
        idcode = await jtag.read_idcode()
        fields = jtag.decode_idcode(idcode)
        expect = DTP_DEFAULT_IDCODE
        exp_fields = jtag.decode_idcode(expect)
        if idcode != expect:
            raise AssertionError(
                f"IDCODE mismatch: got=0x{idcode:08x} expect=0x{expect:08x} "
                f"fields={fields} expect_fields={exp_fields}"
            )
        # Confirm TAP returned to RTI after IDCODE (bounded)
        st = self._sample_tap_state()
        if st != int(OcahJtagState.RUN_TEST_IDLE):
            st = await self._wait_state(jtag, OcahJtagState.RUN_TEST_IDLE, label="s2_idcode_rti")
        else:
            self._timeout_paths.append(f"s2_idcode_rti: bound={self.BOUND_TCK} ok last=0x{st:x}")
        decoded = self._sample(dut.jtag_ptap_inst_decoded, "jtag_ptap_inst_decoded")
        detail_s1 = (
            f"idcode=0x{idcode:08x} expect=0x{expect:08x} "
            f"marker={fields['marker']} mfr=0x{fields['manufacturer']:x} "
            f"part=0x{fields['part_number']:x} ver=0x{fields['version']:x} "
            f"inst_decoded=0x{decoded:x} cell=inst=IDCODE"
        )
        self._log(f"CHK-DTP-JTAG-PTAP-S1: PASS ({detail_s1})")
        sb.expect_eq(
            "CHK-DTP-JTAG-PTAP-S1 IDCODE fields",
            idcode,
            expect,
            evidence="CHK-DTP-JTAG-PTAP-S1",
        )

        # ------------------------------------------------------------------
        # S3 DTP-JTAG-PTAP.S2 BYPASS
        # ------------------------------------------------------------------
        self._mark_step(
            "S3",
            "ACTION/RESPONSE/EFFECT DTP-JTAG-PTAP.S2: load BYPASS IR; "
            "shift known TDI; capture TDO (single-bit register latency)",
        )
        bypass_op = (1 << DTP_IR_WIDTH) - 1
        await jtag.shift_ir(bypass_op, width=DTP_IR_WIDTH, back_to_rti=False)
        st_sel = self._sample_tap_state()
        if st_sel != int(OcahJtagState.SELECT_DR_SCAN):
            await jtag.goto_state(OcahJtagState.SELECT_DR_SCAN)
            st_sel = self._sample_tap_state()
        if st_sel != int(OcahJtagState.SELECT_DR_SCAN):
            st_sel = await self._wait_state(
                jtag, OcahJtagState.SELECT_DR_SCAN, label="s3_select_dr"
            )
        else:
            self._timeout_paths.append(f"s3_select_dr: bound={self.BOUND_TCK} ok last=0x{st_sel:x}")

        st_cap = await self._wait_state_after_step(
            jtag, 0, OcahJtagState.CAPTURE_DR, label="s3_capture_dr"
        )
        st_sh = await self._wait_state_after_step(
            jtag, 0, OcahJtagState.SHIFT_DR, label="s3_shift_dr"
        )

        pattern = self.BYPASS_PATTERN
        width = self.BYPASS_WIDTH
        captured = 0
        for bit_idx in range(width):
            tdi = (pattern >> bit_idx) & 0x1
            end = 1 if bit_idx == width - 1 else 0
            tdo = await jtag.step(end, tdi)
            captured |= (tdo & 0x1) << bit_idx

        st_upd = await self._wait_state_after_step(
            jtag, 1, OcahJtagState.UPDATE_DR, label="s3_update_dr"
        )
        await jtag.step_tms(0)  # UPDATE_DR -> RTI
        st_rti = self._sample_tap_state()
        if st_rti != int(OcahJtagState.RUN_TEST_IDLE):
            st_rti = await self._wait_state(jtag, OcahJtagState.RUN_TEST_IDLE, label="s3_back_rti")
        else:
            self._timeout_paths.append(f"s3_back_rti: bound={self.BOUND_TCK} ok last=0x{st_rti:x}")

        expected_tdo = (pattern & 0x7FFF_FFFF) << 1
        got = int(captured) & 0xFFFF_FFFF
        if got != expected_tdo:
            raise AssertionError(
                f"BYPASS TDO mismatch: tdi=0x{pattern:08x} "
                f"tdo=0x{got:08x} expect=0x{expected_tdo:08x}"
            )
        detail_s2 = (
            f"tdi=0x{pattern:08x} tdo=0x{got:08x} expect=0x{expected_tdo:08x} "
            f"cap=0x{st_cap:x} sh=0x{st_sh:x} upd=0x{st_upd:x} "
            f"cell=inst=BYPASS"
        )
        self._log(f"CHK-DTP-JTAG-PTAP-S2: PASS ({detail_s2})")
        sb.expect_eq(
            "CHK-DTP-JTAG-PTAP-S2 BYPASS one-bit latency",
            got,
            expected_tdo,
            evidence="CHK-DTP-JTAG-PTAP-S2",
        )

        # ------------------------------------------------------------------
        # S4 DTP-JTAG-PTAP.S3 TRST + POR → Test-Logic-Reset
        # ------------------------------------------------------------------
        self._mark_step(
            "S4",
            "ACTION/RESPONSE/EFFECT DTP-JTAG-PTAP.S3: from non-TLR, "
            "TRST pulse then POR (powergood) each return TAP to "
            "Test-Logic-Reset",
        )
        # Leave TLR via RTI then enter SHIFT_DR under BYPASS
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await jtag.shift_ir(bypass_op, width=DTP_IR_WIDTH, back_to_rti=False)
        await jtag.goto_state(OcahJtagState.SHIFT_DR)
        pre_trst = self._sample_tap_state()
        if pre_trst == int(OcahJtagState.TEST_LOGIC_RESET):
            raise AssertionError(
                f"CHK-DTP-JTAG-PTAP-S3 pre-TRST already TLR "
                f"(state=0x{pre_trst:x}); cannot prove TRST effect"
            )

        # TRST path (active-low): assert while holding TCK, observe TLR
        await jtag.assert_trst(tck_cycles=self.TRST_CYCLES)
        tlr_trst = await self._wait_tap_eq_ref(OcahJtagState.TEST_LOGIC_RESET, label="s4_trst_tlr")
        await jtag.release_trst()
        await ClockCycles(dut.clk_ref_i, 4)
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)

        # POR path: hold TRST deasserted; pulse powergood_i (SMC→DTP
        # pwr_on_rst_ni = powergood_stable). Async drop forces TLR.
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await jtag.shift_ir(bypass_op, width=DTP_IR_WIDTH, back_to_rti=False)
        await jtag.goto_state(OcahJtagState.SHIFT_DR)
        pre_por = self._sample_tap_state()
        if pre_por == int(OcahJtagState.TEST_LOGIC_RESET):
            raise AssertionError(
                f"CHK-DTP-JTAG-PTAP-S3 pre-POR already TLR "
                f"(state=0x{pre_por:x}); cannot prove POR effect"
            )
        if int(dut.jtag_trst.value) != 1:
            raise AssertionError(
                "CHK-DTP-JTAG-PTAP-S3 POR path requires TRST deasserted "
                f"(jtag_trst={int(dut.jtag_trst.value)})"
            )

        dut.powergood_i.value = 0
        tlr_por = await self._wait_tap_eq_ref(OcahJtagState.TEST_LOGIC_RESET, label="s4_por_tlr")
        # Restore power-good / cold-reset baseline for scoreboard teardown
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, self.POR_RECOVER_REF)
        dut.rst_cold_ni.value = 1
        await jtag.release_trst()
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)

        detail_s3 = (
            f"pre_trst=0x{pre_trst:x} tlr_trst=0x{tlr_trst:x} "
            f"pre_por=0x{pre_por:x} tlr_por=0x{tlr_por:x} "
            f"cells=rst=TRST,rst=POR,state=Test-Logic-Reset"
        )
        self._log(f"CHK-DTP-JTAG-PTAP-S3: PASS ({detail_s3})")
        tlr = int(OcahJtagState.TEST_LOGIC_RESET)
        sb.expect_eq(
            "CHK-DTP-JTAG-PTAP-S3 TRST+POR → TLR",
            (tlr_trst, tlr_por),
            (tlr, tlr),
            evidence="CHK-DTP-JTAG-PTAP-S3",
        )

        # ------------------------------------------------------------------
        # S5 TIMEOUT inventory
        # ------------------------------------------------------------------
        self._mark_step(
            "S5",
            "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last TAP state",
        )
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS}"
            )
        for i, line in enumerate(self._timeout_paths):
            if "bound=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing finite bound: {line}")
            if "ok last=" not in line and "EXPIRED last=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing last-state: {line}")
        self._log(
            "CHK-TIMEOUT-PATHS: Finite bound on S5; expiry fails with "
            f"last-state diagnostics (paths={n_paths} "
            f"expect={self.EXPECTED_TIMEOUT_PATHS} "
            f"bound_tck={self.BOUND_TCK} bound_ref={self.BOUND_REF})"
        )
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count+shape",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step_ts["PASS"] = time.monotonic()
        self._log("SMU_ALL_005 sequence complete (PASS term recorded for NONVAC fence)")
        order = ["S1", "S2", "S3", "S4", "S5", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        deltas_ns = [
            int((self._step_ts[b] - self._step_ts[a]) * 1e9) for a, b in zip(order, order[1:])
        ]
        positive_deltas = sum(1 for d in deltas_ns if d > 0)
        if positive_deltas != 5:
            raise AssertionError(
                f"CHK-NONVAC positive-delta count fail: {positive_deltas} deltas_ns={deltas_ns}"
            )
        self._log("CHK-NONVAC: Ordered fence S1<S2<S3<S4<S5<PASS all hold")
        sb.expect_eq(
            "CHK-NONVAC positive step-delta count",
            positive_deltas,
            5,
            evidence="CHK-NONVAC",
        )
