# SPDX-License-Identifier: Apache-2.0
"""Shared PyUVM base test for the production SMU wrapper OSS environment."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from pyuvm import ConfigDB, uvm_test


_COCOTB_ROOT = Path(__file__).resolve().parents[1]
_OSS_HW_ROOT = Path(__file__).resolve().parents[5]
for _path in (_COCOTB_ROOT, _OSS_HW_ROOT / "common" / "dv" / "vip"):
    _path_text = str(_path)
    if _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from env.smu_env_cfg import SmuEnvCfg  # noqa: E402


class smu_base_test(uvm_test):
    """Clock/reset bring-up and scenario hook shared by every SMU OSS test."""

    @staticmethod
    def random_seed() -> int:
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    @staticmethod
    def read_int(signal, name: str, *, allow_xz: bool = False) -> int:
        value = signal.value
        if hasattr(value, "is_resolvable") and not value.is_resolvable:
            if allow_xz:
                return 0
            raise AssertionError(f"{name} contains X/Z: {value}")
        return int(value)

    def build_phase(self) -> None:
        self.cfg = SmuEnvCfg("cfg")
        self.cfg.randomize_timing(self.random_seed())
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.logger.info(
            "SMU seed=%d clocks(ref/smu/periph/wdt)=%d/%d/%d/%dns "
            "reset(powergood/hold/post)=%d/%d/%d cycles",
            self.random_seed(),
            self.cfg.ref_clk_period_ns,
            self.cfg.smu_clk_period_ns,
            self.cfg.periph_clk_period_ns,
            self.cfg.sep_wdt_clk_period_ns,
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
            Clock(dut.clk_smu_i, self.cfg.smu_clk_period_ns, units="ns").start()
        )
        cocotb.start_soon(
            Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, units="ns").start()
        )
        cocotb.start_soon(
            Clock(dut.clk_sep_wdt_i, self.cfg.sep_wdt_clk_period_ns, units="ns").start()
        )

    async def bring_up(self) -> None:
        """Apply the production wrapper power-good and cold-reset sequence."""
        dut = cocotb.top
        # Verilator two-state simulation initializes every signal to 0, so a
        # reset input that starts low never produces the falling edge that
        # fires async-reset flops. Flops with nonzero reset values (e.g. the
        # DTP IC_RESET TDR default of "override disabled") would keep their
        # power-up zeros and hold SEP in reset. Pre-drive the resets high for
        # two cycles so the subsequent assertion is a real falling edge, as
        # the X->0 transition would be in a four-state simulator.
        self.logger.info("Step 0: pre-drive resets high to arm async resets")
        dut.powergood_i.value = 1
        dut.rst_cold_ni.value = 1
        self.start_clocks()
        await ClockCycles(dut.clk_ref_i, 2)

        self.logger.info("Step 1: assert power-good low and cold reset")
        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, self.cfg.powergood_delay_cycles)
        self.pre_release_sep_reset = self.read_int(
            dut.sep_reset_n_o, "sep_reset_n_o during cold reset"
        )
        self.pre_release_sep_fuse = self.read_int(
            dut.sep_fuse_sense_done_o,
            "sep_fuse_sense_done_o during cold reset",
        )
        self.logger.info(
            "Reset-state SEP evidence: reset_n=%d fuse_done=%d",
            self.pre_release_sep_reset,
            self.pre_release_sep_fuse,
        )

        self.logger.info("Step 2: assert power-good while retaining cold reset")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.reset_hold_cycles)

        self.logger.info("Step 3: release cold reset and wait for resolved outputs")
        dut.rst_cold_ni.value = 1
        # Extra settle so the TB JTAG TCK reload (after TRST rise) can clear
        # IC_RESET TDR overrides before observers sample fuse/primary reset.
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_cycles + 40)
        self.post_release_sep_reset = self.read_int(
            dut.sep_reset_n_o, "sep_reset_n_o after cold reset"
        )
        self.post_release_sep_fuse = self.read_int(
            dut.sep_fuse_sense_done_o,
            "sep_fuse_sense_done_o after cold reset",
        )
        self.logger.info(
            "Post-reset SEP evidence: reset_n=%d fuse_done=%d",
            self.post_release_sep_reset,
            self.post_release_sep_fuse,
        )
        self.cfg.reset_done.set()

    async def run_scenario(self) -> None:
        raise NotImplementedError

    async def run_phase(self) -> None:
        self.raise_objection()
        await self.bring_up()
        await self.run_scenario()
        self.drop_objection()
