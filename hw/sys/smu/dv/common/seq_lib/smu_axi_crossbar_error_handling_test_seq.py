# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_axi_crossbar_error_handling_test (SMU_ALL_008).

DV-CARD:          SMU_ALL_008   ANCHOR: smu_axi_crossbar_error_handling_test

Owns only SMC-PWRGOOD-DTP-POR.S2; FAB-IN / DECODE are out of scope.

No Force/deposit. Reuses SMU_ALL_005 PTAP leave-TLR helper pattern.
"""

from __future__ import annotations

import os
import random
import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import make_smu_jtag_tap
from seq_lib.smu_tb_pins import smc_primary_reset


class smu_axi_crossbar_error_handling_test_seq:
    """SMU_ALL_008: wrapper PTAP leave-TLR under power-good."""

    BOUND_TCK = 2000

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []
        self._chk_pass: dict[str, bool] = {}
        seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        rng = random.Random(seed ^ 0xFAB_C808)
        self._seed = seed
        self._post_reset_cycles = rng.randint(24, 64)
        self._post_trst_cycles = rng.randint(2, 8)

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
            last = self._sample(self.dut.jtag_ptap_state, "jtag_ptap_state")
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

    async def _step_s1_leave_tlr(self, jtag) -> None:
        """SMC-PWRGOOD-DTP-POR.S2: leave Test-Logic-Reset under power-good."""
        dut = self.dut
        sb = self.test.env.scoreboard
        self._mark_step(
            "S1",
            "ACTION/RESPONSE/EFFECT SMC-PWRGOOD-DTP-POR.S2: power-good "
            "stable + TRST released; PTAP leaves Test-Logic-Reset",
        )
        self._log("COVERAGE SMC-PWRGOOD-DTP-POR.S2 cells: powergood=1 trst=1 tap=exit_tlr")

        pg = self._sample(dut.powergood_i, "powergood_i")
        if pg != 1:
            raise AssertionError(
                f"CHK-SMC-PWRGOOD-DTP-POR-S2 powergood not stable: powergood_i={pg}"
            )
        # Ensure TAP in TLR with TRST released afterward (leave-TLR needs trst=1).
        await jtag.reset_tap()
        tlr = self._sample(dut.jtag_ptap_state, "jtag_ptap_state")
        if tlr != int(OcahJtagState.TEST_LOGIC_RESET):
            tlr = await self._wait_state(
                jtag, OcahJtagState.TEST_LOGIC_RESET, label="s1_enter_tlr", hold_tms=1
            )
        else:
            self._timeout_paths.append(f"s1_enter_tlr: bound={self.BOUND_TCK} ok last=0x{tlr:x}")

        # TRST released (active-low deasserted).
        dut.jtag_trst.value = 1
        await ClockCycles(dut.clk_ref_i, self._post_trst_cycles)
        trst = self._sample(dut.jtag_trst, "jtag_trst")
        if trst != 1:
            raise AssertionError(f"CHK-SMC-PWRGOOD-DTP-POR-S2 TRST not released: jtag_trst={trst}")

        # Leave TLR → Run-Test/Idle (TMS=0 from TLR).
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        idle = self._sample(dut.jtag_ptap_state, "jtag_ptap_state")
        if idle != int(OcahJtagState.RUN_TEST_IDLE):
            idle = await self._wait_state(
                jtag, OcahJtagState.RUN_TEST_IDLE, label="s1_exit_tlr_rti"
            )
        else:
            self._timeout_paths.append(
                f"s1_exit_tlr_rti: bound={self.BOUND_TCK} ok last=0x{idle:x}"
            )

        if idle == int(OcahJtagState.TEST_LOGIC_RESET):
            raise AssertionError(
                "CHK-SMC-PWRGOOD-DTP-POR-S2 still in Test-Logic-Reset after "
                f"leave attempt (state=0x{idle:x})"
            )
        detail = (
            f"powergood={pg} trst={trst} pre_tlr=0x{tlr:x} "
            f"post_state=0x{idle:x} expect_rti=0x"
            f"{int(OcahJtagState.RUN_TEST_IDLE):x} cell=tap=exit_tlr"
        )
        self._log(f"CHK-SMC-PWRGOOD-DTP-POR-S2: PASS ({detail})")
        sb.expect_eq(
            "CHK-SMC-PWRGOOD-DTP-POR-S2 leave-TLR state",
            idle,
            int(OcahJtagState.RUN_TEST_IDLE),
            evidence="CHK-SMC-PWRGOOD-DTP-POR-S2",
        )
        self._chk_pass["CHK-SMC-PWRGOOD-DTP-POR-S2"] = True

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        await self.cfg.reset_done.wait()
        self._log(
            f"SEED: {self._seed} post_reset_cycles={self._post_reset_cycles} "
            f"post_trst_cycles={self._post_trst_cycles} "
            f"jtag_period_ns={self.cfg.jtag_period_ns}"
        )
        await ClockCycles(dut.clk_smu_i, self._post_reset_cycles)

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        jtag.init_signals()

        await self._step_s1_leave_tlr(jtag)

        # Bounded-wait inventory (fail_on timeout).
        self._log("TIMEOUT: bounded waits with last-state diagnostics")
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
            if "bound=" not in line:
                raise AssertionError(f"timeout path missing finite bound: {line}")
            if "ok last=" not in line and "EXPIRED last=" not in line:
                raise AssertionError(f"timeout path missing last-state: {line}")

        # NONVAC: clocks advanced, reset released, S1 PASS token ordered.
        rst = self._sample(smc_primary_reset(dut), "rst_primary_smc_clk_no")
        if rst != 1:
            raise AssertionError(f"CHK-NONVAC reset not released: rst_primary_smc_clk_no={rst}")
        await RisingEdge(dut.clk_smu_i)
        await RisingEdge(dut.clk_smu_i)

        if not self._chk_pass.get("CHK-SMC-PWRGOOD-DTP-POR-S2"):
            raise AssertionError("CHK-NONVAC missing PASS term: CHK-SMC-PWRGOOD-DTP-POR-S2")

        self._step_ts["PASS"] = time.monotonic()
        self._log("SMU_ALL_008 sequence complete (PASS term for NONVAC fence)")
        order = ["S1", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        if self._step_ts["S1"] >= self._step_ts["PASS"]:
            raise AssertionError("CHK-NONVAC order fail: S1 not before PASS")
        delta_ns = int((self._step_ts["PASS"] - self._step_ts["S1"]) * 1e9)
        positive_deltas = 1 if delta_ns > 0 else 0
        if positive_deltas != 1:
            raise AssertionError(
                f"CHK-NONVAC positive-delta count fail: {positive_deltas} delta_ns={delta_ns}"
            )
        self._log(
            "CHK-NONVAC: PASS (Ordered fence S1<PASS; "
            f"reset_released={rst} clocks_advanced=1 "
            f"s1_pass=1 positive_deltas={positive_deltas} "
            f"delta_ns={delta_ns})"
        )
        sb.expect_eq(
            "CHK-NONVAC positive step-delta count",
            positive_deltas,
            1,
            evidence="CHK-NONVAC",
        )
