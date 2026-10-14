# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_dtp_sysreset_stop_clks_test. No Force.

Steps S1-S3, checkers CHK-DTP-SYSRESET-S1..S2.
Spec: hw/sys/dtp/doc/clk_rst.adoc (Clock Stop, Reset Architecture), hw/sys/smu/doc/port_table.adoc.

The clock-stop controller sits on the DTP ``rst_n_i``, which resets the clock-stop
output to 0, and ``stop_clks_o`` follows the requests three ``clk_smu_i`` cycles
later. The JTAG request is programmed in DEBUG_CONTROL and stays programmed
through the primary reset, so TRST stays high and the TAP never re-enters
Test-Logic-Reset.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    make_smu_jtag_tap,
    pack_debug_control,
)
from seq_lib.smu_tb_pins import smc_primary_reset

RESET_HOLD_REF_CYCLES = 64
RESET_ASSERT_BOUND_SMU_CYCLES = 8192
RESET_RELEASE_BOUND_REF_CYCLES = 8192
POLL_BOUND_SMU_CYCLES = 64
RETURN_AFTER_RELEASE_SMU_CYCLES = 3

STEP_ORDER = ["S1", "S2", "S3", "PASS"]


class smu_dtp_sysreset_stop_clks_test_seq:
    """dtp_stop_clks_o across a primary reset with jtag_clock_stop programmed."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.steps: list[str] = []
        self.hold_done = False

    def _bit(self, pin, name: str) -> int:
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    def _stop(self) -> int:
        return self._bit(self.dut.dtp_stop_clks_o, "dtp_stop_clks_o")

    def _rst(self) -> int:
        return self._bit(smc_primary_reset(self.dut), "rst_primary_smc_clk_n_o")

    async def _wait_stop(self, level: int, what: str) -> None:
        for _ in range(POLL_BOUND_SMU_CYCLES):
            if self._stop() == level:
                return
            await RisingEdge(self.dut.clk_smu_i)
        raise AssertionError(
            f"TIMEOUT {what}: dtp_stop_clks_o never read {level} within "
            f"{POLL_BOUND_SMU_CYCLES} clk_smu"
        )

    async def _open_tap(self) -> None:
        self.jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")

    async def _hold_timer(self) -> None:
        await ClockCycles(self.dut.clk_ref_i, RESET_HOLD_REF_CYCLES)
        self.hold_done = True

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        await self._open_tap()
        if self._stop() != 0:
            raise AssertionError("baseline dtp_stop_clks_o is not 0")
        self.steps.append("S1")

        # S2: the JTAG request raises stop_clks_o; the primary reset holds it low.
        await self.jtag.write("DEBUG_CONTROL", pack_debug_control(jtag_clock_stop=1))
        await self._wait_stop(1, "jtag_clock_stop request")
        sb.expect_eq(
            "dtp_stop_clks_o reads 1 with jtag_clock_stop programmed",
            self._stop(),
            1,
            evidence="DTP_SYSRESET_S1",
        )
        dut.tb_cool_reset_pin.value = 1
        for _ in range(RESET_ASSERT_BOUND_SMU_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            if self._rst() == 0:
                break
        else:
            raise AssertionError("TIMEOUT: rst_primary_smc_clk_n_o never read 0")
        self.hold_done = False
        timer = cocotb.start_soon(self._hold_timer())
        samples = 0
        ones_seen = 0
        while True:
            if self._rst() != 0:
                raise AssertionError("rst_primary_smc_clk_n_o rose inside the reset hold")
            samples += 1
            ones_seen += self._stop()
            if self.hold_done:
                break
            await RisingEdge(dut.clk_smu_i)
        await timer
        if samples == 0:
            raise AssertionError("no dtp_stop_clks_o sample taken inside the primary reset")
        self.log.info("S2: %d clk_smu samples inside the reset, %d read 1", samples, ones_seen)
        sb.expect_eq(
            "dtp_stop_clks_o reads 1 on none of the clk_smu edges inside the primary reset",
            ones_seen,
            0,
            evidence="DTP_SYSRESET_S1",
        )
        self.steps.append("S2")

        # S3: after release the request still programmed returns stop_clks_o to 1.
        dut.tb_cool_reset_pin.value = 0
        for _ in range(RESET_RELEASE_BOUND_REF_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            if self._rst() == 1:
                break
        else:
            raise AssertionError("TIMEOUT: rst_primary_smc_clk_n_o never read 1 after release")
        index = -1
        for edge in range(1, POLL_BOUND_SMU_CYCLES + 1):
            await RisingEdge(dut.clk_smu_i)
            if self._stop() == 1:
                index = edge
                break
        if index < 0:
            raise AssertionError(
                f"TIMEOUT: dtp_stop_clks_o never read 1 within {POLL_BOUND_SMU_CYCLES} clk_smu "
                "after rst_primary_smc_clk_n_o rose"
            )
        sb.expect_eq(
            "dtp_stop_clks_o first reads 1 three clk_smu edges after the primary reset releases",
            index,
            RETURN_AFTER_RELEASE_SMU_CYCLES,
            evidence="DTP_SYSRESET_S2",
        )
        self.steps.append("S3")

        await self.jtag.write("DEBUG_CONTROL", 0)
        await self._wait_stop(0, "jtag_clock_stop clear")

        self.steps.append("PASS")
        if self.steps != STEP_ORDER:
            raise AssertionError(f"CHK-NONVAC order fail: {self.steps} != {STEP_ORDER}")
        self.log.info("CHK-NONVAC: PASS (ordered fence S1<S2<S3<PASS)")
