# SPDX-License-Identifier: Apache-2.0
"""SMU OSS PyUVM base test: clocks, reset, scenario hook, no vacuous PASS."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from pyuvm import ConfigDB, uvm_test

_COCOTB_ROOT = Path(__file__).resolve().parents[1]
for _path in (_COCOTB_ROOT,):
    _s = str(_path)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from env.smu_env import SmuEnv
from env.smu_env_cfg import SmuEnvCfg
from seq_lib.smu_axi_helpers import wait_signal_high


class smu_base_test(uvm_test):
    """Shared SMU test: env build, clock/reset, require run_scenario evidence."""

    @staticmethod
    def random_seed() -> int:
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    def build_phase(self) -> None:
        self.cfg = SmuEnvCfg("cfg")
        self.cfg.randomize_timing(self.random_seed())
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.env = SmuEnv("env", self)
        self._scenario_ran = False

    async def run_phase(self) -> None:
        self.raise_objection()
        try:
            await self.bring_up()
            await self.run_scenario()
            self._scenario_ran = True
            # Hit scenario-intent FCOV bins before scoreboard check_phase.
            n = self.env.scoreboard.fcov.hit_for_test(self.get_type_name())
            if n:
                self.logger.info(
                    "FCOV: auto-hit %d bin(s) for %s", n, self.get_type_name()
                )
        finally:
            self.drop_objection()

    async def bring_up(self) -> None:
        dut = cocotb.top
        # Must schedule Clock.start() - bare .start() returns an unawaited coroutine
        # and leaves all clocks dead (sim never advances; premature shutdown).
        cocotb.start_soon(
            Clock(dut.clk_smu_i, self.cfg.smu_clk_period_ns, units="ns").start()
        )
        cocotb.start_soon(
            Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, units="ns").start()
        )
        cocotb.start_soon(
            Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, units="ns").start()
        )

        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        dut.jtag_tck.value = 0
        dut.jtag_tms.value = 0
        dut.jtag_trst.value = 0
        dut.jtag_tdi.value = 0
        # Cross-trigger CTM / clock-stop idle defaults (tests may override)
        if hasattr(dut, "xtrig_ctm_dst_req"):
            dut.xtrig_ctm_dst_req.value = 0
        if hasattr(dut, "xtrig_ctm_src_ack"):
            dut.xtrig_ctm_src_ack.value = 0
        if hasattr(dut, "xtrig_clk_stop_req"):
            dut.xtrig_clk_stop_req.value = 0
        if hasattr(dut, "captured_straps_i"):
            dut.captured_straps_i.value = 0
        if hasattr(dut, "gpio_boot_stall_drive_i"):
            dut.gpio_boot_stall_drive_i.value = 0
        # Telemetry ATB channel-0 idle (driven only by telemetry handshake test).
        if hasattr(dut, "tb_tel_atdata"):
            dut.tb_tel_atdata.value = 0
        if hasattr(dut, "tb_tel_atid"):
            dut.tb_tel_atid.value = 0
        if hasattr(dut, "tb_tel_atvalid"):
            dut.tb_tel_atvalid.value = 0
        if hasattr(dut, "tb_tel_afready"):
            dut.tb_tel_afready.value = 0
        if hasattr(dut, "tb_force_wdt_reset_raw"):
            dut.tb_force_wdt_reset_raw.value = 0
        if hasattr(dut, "tb_force_cluster_isolate"):
            dut.tb_force_cluster_isolate.value = 0
        # Idle AXI
        for name in (
            "s_axi_awvalid", "s_axi_wvalid", "s_axi_bready",
            "s_axi_arvalid", "s_axi_rready",
        ):
            getattr(dut, name).value = 0
        dut.s_axi_awid.value = 0
        dut.s_axi_awaddr.value = 0
        dut.s_axi_awlen.value = 0
        dut.s_axi_awsize.value = 3
        dut.s_axi_awburst.value = 1
        dut.s_axi_awlock.value = 0
        dut.s_axi_awcache.value = 0
        dut.s_axi_awprot.value = 0
        dut.s_axi_awqos.value = 0
        dut.s_axi_awregion.value = 0
        dut.s_axi_awuser.value = 0
        dut.s_axi_wdata.value = 0
        dut.s_axi_wstrb.value = 0
        dut.s_axi_wlast.value = 1
        dut.s_axi_wuser.value = 0
        dut.s_axi_arid.value = 0
        dut.s_axi_araddr.value = 0
        dut.s_axi_arlen.value = 0
        dut.s_axi_arsize.value = 3
        dut.s_axi_arburst.value = 1
        dut.s_axi_arlock.value = 0
        dut.s_axi_arcache.value = 0
        dut.s_axi_arprot.value = 0
        dut.s_axi_arqos.value = 0
        dut.s_axi_arregion.value = 0
        dut.s_axi_aruser.value = 0

        # Sequence mirrors SMC OSS bring-up against real smc_reset_ctrl:
        # powergood sync -> hold rst_cold asserted ≥32 ref cycles (deglitch) ->
        # release -> wait ≥255 extender (+ sync) until stable/primary rise.
        await ClockCycles(dut.clk_ref_i, 10)
        self.logger.info("Asserting powergood")
        dut.powergood_i.value = 1
        # Cover powergood sync + 32-cycle cold deglitch while rst_cold stays low.
        await ClockCycles(dut.clk_ref_i, 64)
        self.logger.info("Releasing cold reset")
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await wait_signal_high(
            dut.rst_cold_stable_ref_clk_no,
            dut.clk_ref_i,
            timeout_cycles=2000,
            name="rst_cold_stable_ref_clk_no",
        )
        await wait_signal_high(
            dut.rst_primary_smc_clk_no,
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary_smc_clk_no",
        )
        self.cfg.reset_done.set()
        self.logger.info(
            "SMU bring-up complete (powergood + cold/primary resets released)"
        )


    async def run_scenario(self) -> None:
        raise NotImplementedError("concrete SMU tests must implement run_scenario()")

    def check_phase(self) -> None:
        if not self._scenario_ran:
            raise AssertionError(
                f"{self.get_type_name()}: run_scenario() did not complete - refusing vacuous PASS"
            )
