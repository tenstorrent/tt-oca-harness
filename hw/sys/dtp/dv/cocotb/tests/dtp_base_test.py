# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP UVM base test: builds the env, brings up clocks/resets, runs a scenario."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from pyuvm import ConfigDB, uvm_test

# The cocotb runner only puts the test dir on sys.path; make the DV root (env/,
# seq_lib/) importable. Shared VIP roots come from dtp_sim_cfg.toml.
_DV_ROOT = Path(__file__).resolve().parents[1]
_dv_root_str = str(_DV_ROOT)
if _dv_root_str not in sys.path:
    sys.path.insert(0, _dv_root_str)

from env.dtp_dbg_disable import DBG_DISABLE_FIELDS, format_dbg_disable
from env.dtp_env import DtpEnv
from env.dtp_env_cfg import DtpEnvCfg


class dtp_base_test(uvm_test):
    """Shared DTP test: env build, clock/reset bring-up, scenario hook."""

    # Shared-VIP AXI scoreboard adoption (issue #3295): opt-in per test.
    # Tests that enable it declare the CHK-* IDs that must execute and the
    # minimum compared-transaction count per JTAG2AXI stream.
    use_axi_scoreboard = False
    axi_checker_required_ids: tuple[str, ...] = ()
    axi_checker_stream_minimums: dict[str, int] | None = None

    # Every looped scenario runs at least this many passes by default. Each
    # pass gets its own scenario seed (base_seed + loop_idx), so directed
    # scenarios re-prove back-to-back recovery and randomized scenarios add
    # stimulus diversity. Env knobs (specific/group/DTP_TEST_LOOPS) can still
    # raise or lower the count for a given run.
    MIN_DEFAULT_LOOPS = 16

    @staticmethod
    def random_seed() -> int:
        """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    @staticmethod
    def env_int(name: str, default: int, *, minimum: int = 1) -> int:
        """Read an integer environment knob with a lower-bound check."""
        value = int(os.environ.get(name, str(default)), 0)
        if value < minimum:
            raise ValueError(f"{name} must be >= {minimum}, got {value}")
        return value

    @classmethod
    def loop_count(
        cls,
        specific_env: str,
        default: int,
        *,
        group_env: str | None = "DTP_TEST_LOOPS",
    ) -> int:
        """Read a per-test loop count, falling back to a group/default knob."""
        if specific_env in os.environ:
            return cls.env_int(specific_env, default)
        if group_env is None:
            return default
        if group_env in os.environ:
            return cls.env_int(group_env, default)
        if group_env != "DTP_TEST_LOOPS" and "DTP_TEST_LOOPS" in os.environ:
            return cls.env_int("DTP_TEST_LOOPS", default)
        return cls.env_int(group_env, default)

    def build_phase(self) -> None:
        self.cfg = DtpEnvCfg("cfg")
        self.cfg.randomize_timing(self.random_seed())
        self.logger.info(
            "DTP timing: jtag_period=%dns sys_clk_period=%dns (seed=%d)",
            self.cfg.jtag_period_ns,
            self.cfg.sys_clk_period_ns,
            self.random_seed(),
        )
        self.cfg.axi_scoreboard_enabled = self.use_axi_scoreboard
        self.cfg.axi_checker_required_ids = set(self.axi_checker_required_ids)
        self.cfg.axi_checker_stream_minimums = dict(self.axi_checker_stream_minimums or {})
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.env = DtpEnv("env", self)

    async def start_seq(self, seq) -> None:
        """Configure a test sequence and run it on the JTAG sequencer."""
        seq.cfg = self.env.cfg
        await seq.start(self.env.jtag_agent.sequencer)

    async def start_looped_seq(
        self,
        seq_cls,
        base_name: str,
        *,
        specific_env: str,
        default_loops: int = 16,
        group_env: str | None = "DTP_TEST_LOOPS",
        **seq_kwargs,
    ) -> list:
        """Run a sequence class multiple times with deterministic per-loop seeds."""
        default_loops = max(default_loops, self.MIN_DEFAULT_LOOPS)
        loops = self.loop_count(specific_env, default_loops, group_env=group_env)
        random_count = self.env_int("DTP_RANDOM_COUNT", 5)
        base_seed = self.random_seed()
        sequences = []

        for loop_idx in range(loops):
            seq = seq_cls(
                f"{base_name}_{loop_idx}",
                scenario_seed=base_seed + loop_idx,
                random_count=random_count,
                **seq_kwargs,
            )
            await self.start_seq(seq)
            sequences.append(seq)

        return sequences

    async def _bring_up(self) -> None:
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
        await self._bring_up()
        await self.run_scenario()
        self.drop_objection()
