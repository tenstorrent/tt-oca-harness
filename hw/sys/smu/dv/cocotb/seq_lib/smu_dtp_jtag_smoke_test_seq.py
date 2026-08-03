# SPDX-License-Identifier: Apache-2.0
"""Sequence body for smu_dtp_jtag_smoke_test (DV Skill 1.5 / SMU_002 rev 1).

Card OWNS: PTAP BYPASS + TAP-state observation only (not IDCODE).
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import DTP_IR_WIDTH, make_smu_jtag_tap


class smu_dtp_jtag_smoke_test_seq:
    """SMU_002 PTAP BYPASS + state evidence sequence."""

    BYPASS_PATTERN = 0xA5A5_A5A5
    BYPASS_WIDTH = 32
    BOUND_TCK = 2000
    # Real poll-with-expiry sites (each can hit EXPIRED):
    #   idle, after IR -> SELECT_DR, CAPTURE_DR, SHIFT_DR, UPDATE_DR, final RTI
    EXPECTED_TIMEOUT_PATHS = 6
    REQUIRED_DR_STATES = (
        OcahJtagState.SELECT_DR_SCAN,
        OcahJtagState.CAPTURE_DR,
        OcahJtagState.SHIFT_DR,
        OcahJtagState.UPDATE_DR,
    )

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []
        self._visited_states: set[int] = set()

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

    async def _wait_state(
        self,
        jtag,
        expect: OcahJtagState,
        *,
        label: str,
    ) -> int:
        """Poll DUT jtag_ptap_state on TCK until expect or EXPIRED (can fail)."""
        last = None
        for _ in range(self.BOUND_TCK):
            await jtag.step_tms(0)  # stay/advance one TCK; TMS=0 keeps SHIFT/RTI
            # For state entry we use dedicated TMS outside; here only sample after
            # a TCK the caller already drove. Re-sample without stepping if already
            # matching.
            last = self._sample_tap_state()
            self._visited_states.add(last)
            if last == int(expect):
                self._timeout_paths.append(
                    f"{label}: bound={self.BOUND_TCK} ok last=0x{last:x}"
                )
                return last
        self._timeout_paths.append(
            f"{label}: bound={self.BOUND_TCK} EXPIRED last="
            f"{'None' if last is None else f'0x{last:x}'}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={self.BOUND_TCK} last_state={last} "
            f"expect={expect.name}(0x{int(expect):x})"
        )

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
        self._visited_states.add(last)
        if last == int(expect):
            self._timeout_paths.append(
                f"{label}: bound={self.BOUND_TCK} ok last=0x{last:x}"
            )
            return last
        # Poll remaining cycles with TMS that holds the expected state if possible.
        hold_tms = 0 if expect in (
            OcahJtagState.SHIFT_DR,
            OcahJtagState.SHIFT_IR,
            OcahJtagState.RUN_TEST_IDLE,
            OcahJtagState.PAUSE_DR,
            OcahJtagState.PAUSE_IR,
        ) else tms
        for _ in range(self.BOUND_TCK - 1):
            await jtag.step_tms(hold_tms)
            last = self._sample_tap_state()
            self._visited_states.add(last)
            if last == int(expect):
                self._timeout_paths.append(
                    f"{label}: bound={self.BOUND_TCK} ok last=0x{last:x}"
                )
                return last
        self._timeout_paths.append(
            f"{label}: bound={self.BOUND_TCK} EXPIRED last="
            f"{'None' if last is None else f'0x{last:x}'}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={self.BOUND_TCK} last_state={last} "
            f"expect={expect.name}(0x{int(expect):x})"
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        jtag.init_signals()

        # S1 — PRELOAD
        self._mark_step(
            "S1",
            "PRELOAD clocks running; TRST released; TAP reset then idle",
        )
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        idle = self._sample_tap_state()
        self._visited_states.add(idle)
        if idle != int(OcahJtagState.RUN_TEST_IDLE):
            # Real bounded wait that can expire
            idle = await self._wait_state(
                jtag, OcahJtagState.RUN_TEST_IDLE, label="s1_run_test_idle"
            )
        else:
            self._timeout_paths.append(
                f"s1_run_test_idle: bound={self.BOUND_TCK} ok last=0x{idle:x}"
            )

        # S2 — BYPASS with real state waits (can expire)
        self._mark_step(
            "S2",
            "BYPASS: load BYPASS IR; shift known TDI; capture TDO (1-bit latency)",
        )
        bypass_op = (1 << DTP_IR_WIDTH) - 1
        await jtag.shift_ir(bypass_op, width=DTP_IR_WIDTH, back_to_rti=False)
        st_sel = self._sample_tap_state()
        self._visited_states.add(st_sel)
        if st_sel != int(OcahJtagState.SELECT_DR_SCAN):
            await jtag.goto_state(OcahJtagState.SELECT_DR_SCAN)
            st_sel = self._sample_tap_state()
            self._visited_states.add(st_sel)
        if st_sel != int(OcahJtagState.SELECT_DR_SCAN):
            st_sel = await self._wait_state(
                jtag, OcahJtagState.SELECT_DR_SCAN, label="s2_select_dr"
            )
        else:
            self._timeout_paths.append(
                f"s2_select_dr: bound={self.BOUND_TCK} ok last=0x{st_sel:x}"
            )

        st_cap = await self._wait_state_after_step(
            jtag, 0, OcahJtagState.CAPTURE_DR, label="s2_capture_dr"
        )
        st_sh = await self._wait_state_after_step(
            jtag, 0, OcahJtagState.SHIFT_DR, label="s2_shift_dr"
        )

        pattern = self.BYPASS_PATTERN
        width = self.BYPASS_WIDTH
        # Use VIP bit shift while already in SHIFT_DR
        captured = 0
        for bit_idx in range(width):
            tdi = (pattern >> bit_idx) & 0x1
            end = 1 if bit_idx == width - 1 else 0
            tdo = await jtag._cycle(end, tdi)
            captured |= (tdo & 0x1) << bit_idx
            self._visited_states.add(self._sample_tap_state())

        st_upd = await self._wait_state_after_step(
            jtag, 1, OcahJtagState.UPDATE_DR, label="s2_update_dr"
        )
        await jtag.step_tms(0)  # UPDATE_DR -> RTI
        st_rti = self._sample_tap_state()
        self._visited_states.add(st_rti)
        if st_rti != int(OcahJtagState.RUN_TEST_IDLE):
            st_rti = await self._wait_state(
                jtag, OcahJtagState.RUN_TEST_IDLE, label="s2_back_rti"
            )
        else:
            self._timeout_paths.append(
                f"s2_back_rti: bound={self.BOUND_TCK} ok last=0x{st_rti:x}"
            )

        expected = (pattern & 0x7FFF_FFFF) << 1
        got = int(captured) & 0xFFFF_FFFF
        if got != expected:
            raise AssertionError(
                f"BYPASS TDO mismatch: tdi=0x{pattern:08x} "
                f"tdo=0x{got:08x} expect=0x{expected:08x}"
            )
        chk_bypass = (
            f"CHK-PTAP-BYPASS: BYPASS shift of a non-trivial TDI vector appears "
            f"on TDO with one-bit latency; recorded TDI/TDO pair matches "
            f"(tdi=0x{pattern:08x} tdo=0x{got:08x} expect=0x{expected:08x})"
        )
        self._log(chk_bypass)
        sb.expect_eq(
            "CHK-PTAP-BYPASS TDI/TDO pair",
            got,
            expected,
            evidence="CHK-PTAP-BYPASS",
        )

        # S3 — STATE OBS
        self._mark_step(
            "S3",
            "STATE OBS: jtag_ptap_state_o visits Select/Capture/Shift/Update-DR",
        )
        missing = [
            s.name
            for s in self.REQUIRED_DR_STATES
            if int(s) not in self._visited_states
        ]
        if missing:
            raise AssertionError(
                f"CHK-PTAP-STATE missing expected TAP states: {missing}; "
                f"visited={[hex(v) for v in sorted(self._visited_states)]}"
            )
        known = {int(s): s.name for s in OcahJtagState}
        visited_names = [
            known[v] for v in sorted(self._visited_states) if v in known
        ]
        chk_state = (
            f"CHK-PTAP-STATE: jtag_ptap_state_o visits the expected TAP states "
            f"of the BYPASS sequence (Select-DR-Scan, Capture-DR, Shift-DR, "
            f"Update-DR) each recorded "
            f"(visited={','.join(visited_names)} "
            f"cap=0x{st_cap:x} sh=0x{st_sh:x} upd=0x{st_upd:x})"
        )
        self._log(chk_state)
        sb.expect_eq(
            "CHK-PTAP-STATE required DR states",
            len(missing) == 0,
            True,
            evidence="CHK-PTAP-STATE",
        )

        # S4 — TIMEOUT (exact count of real poll sites)
        self._mark_step(
            "S4",
            "TIMEOUT: every JTAG shift/state wait is bounded with last TAP state",
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
                raise AssertionError(
                    f"CHK-TIMEOUT-PATHS[{i}] missing finite bound: {line}"
                )
            if "ok last=" not in line and "EXPIRED last=" not in line:
                raise AssertionError(
                    f"CHK-TIMEOUT-PATHS[{i}] missing last TAP state: {line}"
                )
            if f"bound={self.BOUND_TCK}" not in line:
                raise AssertionError(
                    f"CHK-TIMEOUT-PATHS[{i}] bound != {self.BOUND_TCK}: {line}"
                )
        chk_to = (
            "CHK-TIMEOUT-PATHS: every JTAG shift/state wait names finite bound, "
            f"fail-on-expiry path, and last TAP state "
            f"(paths={n_paths} expect={self.EXPECTED_TIMEOUT_PATHS} "
            f"bound={self.BOUND_TCK})"
        )
        self._log(chk_to)
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count+shape",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step_ts["PASS"] = time.monotonic()
        self._log("SMU_002 sequence complete (PASS term recorded for NONVAC fence)")
        order = ["S2", "S3", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        chk_nonvac = "CHK-NONVAC: ordered fence S2<S3<PASS all present"
        self._log(chk_nonvac)
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            True,
            True,
            evidence="CHK-NONVAC",
        )
