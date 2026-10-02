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
from env.dtp_tb_if import DtpTbIf
from env.dtp_types import (
    DTP_FEATURE_IR_DECODE,
    DTP_FEATURE_JTAG2AXI_REQ,
    DTP_FEATURE_JTAG2AXI_STATUS,
)


class dtp_base_test(OcahTest):
    """Shared DTP test: env build, clock/reset bring-up, scenario hook.

    The framework bases come from ``ocah_lib``: the seed accessor, the knob
    accessor, the loop policy, and ``start_looped_seq`` are inherited. This
    class binds the DTP knob names, the JTAG agent sequencer every scenario
    runs on, and the reset ladder.
    """

    # Scoreboard features this test must exercise; a required feature that
    # ends with zero comparisons fails the run. Every JTAG scenario loads an
    # instruction, so ir_decode is the default.
    required_features: tuple[str, ...] = (DTP_FEATURE_IR_DECODE,)

    # Shared-VIP AXI scoreboard adoption: opt-in per test.
    # Tests that enable it declare the CHK-* IDs that must execute and the
    # minimum compared-transaction count per JTAG2AXI stream.
    use_axi_scoreboard = False
    axi_checker_required_ids: tuple[str, ...] = ()
    axi_checker_stream_minimums: dict[str, int] | None = None
    # Scenario IDs each of the three JTAG2AXI bridges must record on its own
    # checker, which then takes that bridge's judgements instead of the shared
    # scoreboard.
    axi_checker_target_required_ids: tuple[str, ...] = ()

    # Downstream STAP TAPs: the STAP host ports (env.dtp_scan_ref_model
    # STAP_ORDER names) that get a reactive ocah_jtag_vip slave device spliced
    # behind them for this test. Default empty keeps every port's wire
    # loopback; the STAP-selection and zero-length-bypass scenarios attach
    # all four.
    stap_ds_attach: tuple[str, ...] = ()
    # Extended STAP host segment: True places the tb_top host segment behind
    # the extended STAP host scan interface for this test. Default False
    # keeps the host scan loopback; the extended-STAP scenario sets it.
    stap_host_segment = False

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
        self.cfg.required_features = set(self.required_features)
        if self.use_axi_scoreboard:
            # A scenario that drives a bridge lands both bridge features: every
            # launched transaction paired with its JTAG request, and every status
            # capture paired with the completions behind it.
            self.cfg.required_features |= {DTP_FEATURE_JTAG2AXI_REQ, DTP_FEATURE_JTAG2AXI_STATUS}
        self.cfg.axi_scoreboard_enabled = self.use_axi_scoreboard
        self.cfg.axi_checker_required_ids = set(self.axi_checker_required_ids)
        self.cfg.axi_checker_target_required_ids = set(self.axi_checker_target_required_ids)
        both = self.cfg.axi_checker_required_ids & self.cfg.axi_checker_target_required_ids
        if both:
            raise ValueError(
                f"per-bridge ID(s) also required on the shared scoreboard: {sorted(both)}"
            )
        self.cfg.axi_checker_stream_minimums = dict(self.axi_checker_stream_minimums or {})
        unknown = set(self.stap_ds_attach) - set(STAP_ORDER)
        if unknown:
            raise ValueError(f"unknown STAP name(s) in stap_ds_attach: {sorted(unknown)}")
        self.cfg.stap_ds_attach = set(self.stap_ds_attach)
        self.cfg.stap_host_segment = self.stap_host_segment
        self.tb_if = DtpTbIf(cocotb.top)
        self.cfg.tb_if = self.tb_if
        ConfigDB().set(None, "*", "tb_if", self.tb_if)
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.env = DtpEnv("env", self)

    def scenario_sequencer(self) -> uvm_sequencer:
        """Every DTP scenario runs on the primary-TAP JTAG agent's sequencer."""
        return self.env.jtag_agent.sequencer

    def plumb_scenario_seq(self, seq: OcahSequence) -> None:
        seq.cfg = self.env.cfg
        # Sequence evidence reaches the simulation log only from a logger under
        # the `cocotb` hierarchy; a root-child logger drops INFO records silently.
        if not seq.log.name.startswith("cocotb."):
            raise RuntimeError(
                f"{seq.get_name()} logger {seq.log.name!r} is outside the cocotb hierarchy"
            )

    async def bring_up(self) -> None:
        """Walk the DTP reset ladder: start the system clock, release POR, then reset."""
        tb = self.tb_if
        self.logger.info("Bringing up system clock and resets")
        tb.por_rst_n.value = 0
        tb.sys_rst_n.value = 0
        tb.ctrl.xtrig_clk_stop_req.value = 0
        # Downstream STAP TAP ports: each port's attach mux follows the test's
        # stap_ds_attach selection (0 = wire loopback) for the whole run, and
        # the extended STAP host scan mux its stap_host_segment.
        for stap in STAP_ORDER:
            getattr(tb.scan, f"stap_{stap}_ds_en").value = int(stap in self.cfg.stap_ds_attach)
        tb.scan.stap_host_seg_en.value = int(self.cfg.stap_host_segment)
        # Startup vector, driven while POR is still asserted: all eleven
        # active-high disables cleared so tests begin with full debug access
        # and assert the disables they gate explicitly. The DUT itself is
        # fail-closed until its TCK-domain synchronizers pass the cleared
        # values through.
        startup = {name: 0 for name in DBG_DISABLE_FIELDS}
        tb.set_dbg_disable_vector(startup)
        self.logger.info("dbg_disable startup vector: %s", format_dbg_disable(startup))
        cocotb.start_soon(Clock(tb.clk, self.cfg.sys_clk_period_ns, units="ns").start())
        await ClockCycles(tb.clk, 5)
        tb.check_dv_cfg()
        tb.por_rst_n.value = 1
        await ClockCycles(tb.clk, 5)
        tb.sys_rst_n.value = 1
        await ClockCycles(tb.clk, 10)
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
