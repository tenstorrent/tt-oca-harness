# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP UVM base test: builds the env, brings up clocks/resets, runs a scenario."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from ocah_lib import OcahSequence, OcahTest
from pyuvm import ConfigDB, uvm_sequencer

# The cocotb runner only puts the test dir on sys.path; make the DV root (env/,
# seq_lib/) importable. Shared VIP roots come from dtp_sim_cfg.toml.
_DV_ROOT = Path(__file__).resolve().parents[1]
_dv_root_str = str(_DV_ROOT)
if _dv_root_str not in sys.path:
    sys.path.insert(0, _dv_root_str)

from env.dtp_dbg_disable import DBG_DISABLE_FIELDS, format_dbg_disable
from env.dtp_env import DtpEnv
from env.dtp_env_cfg import DtpEnvCfg
from env.dtp_scan_ref_model import STAP_ORDER


class dtp_base_test(OcahTest):
    """Shared DTP test: env build, clock/reset bring-up, scenario hook.

    The framework bases come from ``ocah_lib``: the seed accessor, the knob
    accessor, the loop policy, and ``start_looped_seq`` are inherited. This
    class binds the DTP knob names, the JTAG agent sequencer every scenario
    runs on, and the reset ladder.
    """

    # Shared-VIP AXI scoreboard adoption: opt-in per test.
    # Tests that enable it declare the CHK-* IDs that must execute and the
    # minimum compared-transaction count per JTAG2AXI stream.
    use_axi_scoreboard = False
    axi_checker_required_ids: tuple[str, ...] = ()
    axi_checker_stream_minimums: dict[str, int] | None = None

    # Downstream STAP TAPs: the STAP host ports (env.dtp_scan_ref_model
    # STAP_ORDER names) that get a reactive ocah_jtag_vip slave device spliced
    # behind them for this test. Default empty keeps every port's wire
    # loopback; the STAP-selection scenarios attach all four.
    stap_ds_attach: tuple[str, ...] = ()

    # Knob names of the DTP loop policy; the library resolves the per-test
    # knob, then the group knob, then these.
    def suite_loops_knob(self) -> str:
        return "DTP_TEST_LOOPS"

    def random_count_knob(self) -> str:
        return "DTP_RANDOM_COUNT"

    def build_phase(self) -> None:
        self.cfg = DtpEnvCfg("cfg")
        self.cfg.randomize_timing(self.base_seed())
        self.logger.info(
            "DTP timing: jtag_period=%dns sys_clk_period=%dns (seed=%d)",
            self.cfg.jtag_period_ns,
            self.cfg.sys_clk_period_ns,
            self.base_seed(),
        )
        self.cfg.axi_scoreboard_enabled = self.use_axi_scoreboard
        self.cfg.axi_checker_required_ids = set(self.axi_checker_required_ids)
        self.cfg.axi_checker_stream_minimums = dict(self.axi_checker_stream_minimums or {})
        unknown = set(self.stap_ds_attach) - set(STAP_ORDER)
        if unknown:
            raise ValueError(f"unknown STAP name(s) in stap_ds_attach: {sorted(unknown)}")
        self.cfg.stap_ds_attach = set(self.stap_ds_attach)
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.env = DtpEnv("env", self)

    def scenario_sequencer(self) -> uvm_sequencer:
        """Every DTP scenario runs on the primary-TAP JTAG agent's sequencer."""
        return self.env.jtag_agent.sequencer

    def plumb_scenario_seq(self, seq: OcahSequence) -> None:
        seq.cfg = self.env.cfg

    async def bring_up(self) -> None:
        """Walk the DTP reset ladder: idle the pins, start the system clock, release POR, then reset."""
        dut = cocotb.top
        self.logger.info("Bringing up system clock and resets")
        dut.pwr_on_rst_ni.value = 0
        dut.rst_n_i.value = 0
        if hasattr(dut, "xtrig_clk_stop_req"):
            dut.xtrig_clk_stop_req.value = 0
        for name in (
            "xtrig_axil_awaddr",
            "xtrig_axil_awprot",
            "xtrig_axil_awvalid",
            "xtrig_axil_wdata",
            "xtrig_axil_wstrb",
            "xtrig_axil_wvalid",
            "xtrig_axil_bready",
            "xtrig_axil_araddr",
            "xtrig_axil_arprot",
            "xtrig_axil_arvalid",
            "xtrig_axil_rready",
            "xtrig_ctm_src_ack",
            "xtrig_ctm_dst_req",
            "xtrig_ctp_req_out_din",
            "xtrig_ctp_req_in_din",
            "xtrig_ctp_ack_in_din",
            "xtrig_ctp_ack_out_din",
        ):
            if hasattr(dut, name):
                getattr(dut, name).value = 0
        # Downstream STAP TAP ports: the device TDO inputs idle low and each
        # port's attach mux follows the test's stap_ds_attach selection
        # (0 = wire loopback) for the whole run.
        for stap in STAP_ORDER:
            getattr(dut, f"jtag_stap_{stap}_tdi").value = 0
            getattr(dut, f"jtag_stap_{stap}_ds_en").value = int(stap in self.cfg.stap_ds_attach)
        # Startup vector, driven while POR is still asserted: all eleven
        # active-high disables cleared so tests begin with full debug access
        # and assert the disables they gate explicitly. The DUT itself is
        # fail-closed until its TCK-domain synchronizers pass the cleared
        # values through.
        startup = {name: 0 for name in DBG_DISABLE_FIELDS}
        for name, value in startup.items():
            getattr(dut, f"dbg_disable_{name}").value = value
        self.logger.info("dbg_disable startup vector: %s", format_dbg_disable(startup))
        cocotb.start_soon(Clock(dut.clk_i, self.cfg.sys_clk_period_ns, units="ns").start())
        await ClockCycles(dut.clk_i, 5)
        dut.pwr_on_rst_ni.value = 1
        await ClockCycles(dut.clk_i, 5)
        dut.rst_n_i.value = 1
        await ClockCycles(dut.clk_i, 10)
        # Release the JTAG/AXI agents now that the DUT is out of reset.
        self.cfg.reset_done.set()

    async def run_scenario(self) -> None:
        """Override with the per-test stimulus."""
        raise NotImplementedError

    async def run_phase(self) -> None:
        self.raise_objection()
        await self.bring_up()
        await self.run_scenario()
        self.drop_objection()
