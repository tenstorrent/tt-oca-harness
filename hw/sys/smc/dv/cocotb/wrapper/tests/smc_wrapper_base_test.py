# SPDX-License-Identifier: Apache-2.0
"""Shared PyUVM base test for the OSS smc_wrapper environment.

Nested under ``cocotb/wrapper/`` so the wrapper smoke catalog lives beside the
bare-SMC tree without sharing ``SmcEnv`` / bare bring-up. ``python_root`` in
``smc_wrapper_sim_cfg.toml`` points here, so imports stay local to this flavor.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from pyuvm import ConfigDB, uvm_test


# tests/ -> wrapper/ -> cocotb/ -> dv/ -> smc/ -> sys/ -> hw/
_WRAPPER_ROOT = Path(__file__).resolve().parents[1]
_OSS_HW_ROOT = Path(__file__).resolve().parents[6]
for _path in (_WRAPPER_ROOT, _OSS_HW_ROOT / "common" / "dv" / "vip"):
    _path_text = str(_path)
    if _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from env.smc_wrapper_env_cfg import SmcWrapperEnvCfg  # noqa: E402


class smc_wrapper_base_test(uvm_test):
    """Clock/reset bring-up and scenario hook for every SMC wrapper test."""

    @staticmethod
    def random_seed() -> int:
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    @staticmethod
    def read_int(signal, name: str) -> int:
        value = signal.value
        if hasattr(value, "is_resolvable") and not value.is_resolvable:
            raise AssertionError(f"{name} contains X/Z: {value}")
        return int(value)

    def build_phase(self) -> None:
        self.cfg = SmcWrapperEnvCfg("cfg")
        self.cfg.randomize_timing(self.random_seed())
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.logger.info(
            "SMC wrapper seed=%d clocks(ref/smc/periph)=%d/%d/%dns "
            "reset(powergood/hold/post)=%d/%d/%d cycles",
            self.random_seed(),
            self.cfg.ref_clk_period_ns,
            self.cfg.smc_clk_period_ns,
            self.cfg.periph_clk_period_ns,
            self.cfg.powergood_delay_cycles,
            self.cfg.reset_hold_cycles,
            self.cfg.post_reset_cycles,
        )

    def start_clocks(self) -> None:
        dut = cocotb.top
        cocotb.start_soon(
            Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, units="ns").start()
        )
        cocotb.start_soon(
            Clock(dut.clk_smc_i, self.cfg.smc_clk_period_ns, units="ns").start()
        )
        cocotb.start_soon(
            Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, units="ns").start()
        )

    async def bring_up(self) -> None:
        """Apply the production wrapper power-good and cold-reset sequence."""
        dut = cocotb.top
        self.logger.info("Step 0: pre-drive resets high to arm async resets")
        dut.powergood_i.value = 1
        dut.rst_cold_ni.value = 1
        self.start_clocks()
        await ClockCycles(dut.clk_ref_i, 2)

        self.logger.info("Step 1: assert power-good low and cold reset")
        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, self.cfg.powergood_delay_cycles)

        self.logger.info("Step 2: assert power-good while retaining cold reset")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.reset_hold_cycles)

        self.logger.info("Step 3: release cold reset and wait for resolved outputs")
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_cycles)
        self.cfg.reset_done.set()

    async def run_scenario(self) -> None:
        raise NotImplementedError

    async def run_phase(self) -> None:
        self.raise_objection()
        await self.bring_up()
        await self.run_scenario()
        self.drop_objection()
