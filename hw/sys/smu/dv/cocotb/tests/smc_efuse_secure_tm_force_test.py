# SPDX-License-Identifier: Apache-2.0
"""smc_efuse_secure_tm_force_test - P4 Force secure_tm_i → fuse cmd blocked.

SEP=0 has no pin-driven secure_tm (secure_tm_o tied 0; wrapper ties
secure_tm_i=0). This test Forces the hier eFuse controller input and proves
``is_secure_tm_blocked_o`` transitions 0→1 (efuse_guard kills fuse commands).

SMC LOCKS shadow map has no lock[3] SECURE_TM bit and is W1S — do NOT use
LOCKS readback as secure_tm evidence (vacuous under W1S).

Must FAIL if Force is ignored (blocked stays 0).
Does NOT claim pin-level secure_tm or secure_tm_o behavior.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    force_jtag2axi_lifecycle_enable,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

_SECURE_TM_PATHS = (
    "u_dut.u_smc.u_smc_peripherals.u_smc_efuse_wrapper."
    "u_efuse_interface_controller.secure_tm_i",
)
_BLOCKED_PATHS = (
    "u_dut.u_smc.u_smc_peripherals.u_smc_efuse_wrapper."
    "u_efuse_interface_controller.is_secure_tm_blocked_o",
)


def _resolve(dut, path: str):
    node = dut
    for part in path.split("."):
        if hasattr(node, part):
            node = getattr(node, part)
            continue
        try:
            node = node._id(part, extended=False)
            continue
        except Exception:  # noqa: BLE001
            return None
    return node


def _resolve_any(dut, paths):
    for path in paths:
        node = _resolve(dut, path)
        if node is not None:
            return node, path
    return None, None


@pyuvm.test()
class smc_efuse_secure_tm_force_test(smu_base_test):
    """Force secure_tm_i; is_secure_tm_blocked_o asserts."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()

        stm, stm_path = _resolve_any(dut, _SECURE_TM_PATHS)
        blocked, blk_path = _resolve_any(dut, _BLOCKED_PATHS)
        assert stm is not None, "secure_tm_i Force target not resolved"
        assert blocked is not None, "is_secure_tm_blocked_o not resolved"
        self.logger.info("SECURE_TM_FORCE via %s; observe %s", stm_path, blk_path)

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            sb.expect_eq(
                "secure_tm_blocked idle before Force",
                int(blocked.value) & 1,
                0,
                evidence="SECURE_TM_FORCE",
            )

            stm.value = Force(1)
            await ClockCycles(dut.clk_smu_i, 4)

            sb.expect_eq(
                "secure_tm_i Force landed",
                int(stm.value) & 1,
                1,
                evidence="SECURE_TM_FORCE",
            )
            sb.expect_eq(
                "is_secure_tm_blocked_o under Force",
                int(blocked.value) & 1,
                1,
                evidence="SECURE_TM_FORCE",
            )
        finally:
            try:
                stm.value = Release()
            except Exception:  # noqa: BLE001
                pass
            release_forced(forced)

        self.logger.info(
            "smc_efuse_secure_tm_force_test: SECURE_TM_FORCE blocked 0->1 OK"
        )
