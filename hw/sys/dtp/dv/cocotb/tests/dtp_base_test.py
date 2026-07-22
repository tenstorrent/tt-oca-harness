# SPDX-License-Identifier: Apache-2.0
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
# seq_lib/) and shared OSS BFM roots importable. Imported by every concrete
# test, so this runs first.
_DV_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _DV_ROOT.parents[5]
for _path in (
    _DV_ROOT,
    _REPO_ROOT / "dv" / "oss" / "hw" / "dv" / "py",
    _REPO_ROOT / "dv" / "vip" / "cocotb",
):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from env.dtp_env import DtpEnv
from env.dtp_env_cfg import DtpEnvCfg


class dtp_base_test(uvm_test):
    """Shared DTP test: env build, clock/reset bring-up, scenario hook."""

    # JTAG2AXI scenarios with randomized address/data/series choices get more
    # default passes. Directed/exhaustive scenarios stay one-pass so group loop
    # knobs do not inflate simulation time without adding coverage.
    JTAG2AXI_DEFAULT_LOOP_SCENARIOS = {
        "series_write_incr",
        "series_write_no_incr",
        "series_write_incr_with_error",
        "random_ops",
        "series_write_read_incr",
        "series_write_read_no_incr",
        "series_write_read_incr_with_error",
        "read_random_ops",
        "error_single_write",
        "error_single_read",
        "backpressure_aw_before_w",
        "backpressure_long_stall",
        "backpressure_abort_at_data_w",
        "decode_error_mixed",
    }
    JTAG2AXI_ONE_PASS_SCENARIOS = {
        "single_write",
        "single_write_data_verify",
        "write_security_gating",
        "single_write_read",
        "read_security_gating",
        "read_security_gating_no_axi_activity",
        "error_series_no_incr_write",
        "error_series_no_incr_read",
        "error_series_incr_write",
        "error_series_incr_read",
        "error_series_incr_write_with_status",
        "error_series_incr_read_with_status",
        "error_security_gating",
        "cdc_clear_abort_narrow_reset_mid_xaction",
        "cdc_clear_abort_back_to_back_reset",
        "decode_error_decerr_write",
        "decode_error_decerr_read",
        "series_corner_all_bridges",
    }
    SCAN_DEFAULT_LOOP_SCENARIOS = {
        "sib_random",
        "dfd",
    }
    SCAN_ONE_PASS_SCENARIOS = {
        "sib_all_off",
        "sib_all_on",
        "dft",
        "stap_sel_ds",
        "stap_sel_smc",
        "stap_sel_extra",
        "stap_sel_sep",
        "ext_stap_scan",
        "config_hold",
        "tms_hold",
    }
    XTRIG_DEFAULT_LOOP_SCENARIOS = {
        "random",
        "ctm_rand_all_scenarios",
        "ctm_rand_wire_or_only",
        "ctm_rand_p2p_only",
        "ctm_rand_cla_to_ctp",
        "ctm_rand_ctp_to_cla",
    }
    XTRIG_ONE_PASS_SCENARIOS = {
        "reg_stall",
        "ctp_csr_sweep",
        "ctm_csr_sweep",
        "wire_or",
        "p2p",
        "reset",
        "dst_port_sweep",
        "axi_channel_skew",
        "axi_channel_skew_demux_aw_lock_release",
        "axi_channel_skew_read_decode_backpressure",
        "ctm_wire_or_cla_to_ctp",
        "ctm_wire_or_ctp_to_cla",
        "ctm_wire_or_cla_to_cla",
        "ctm_wire_or_ctp_to_ctp",
        "ctm_p2p_cla_to_ctp",
        "ctm_p2p_ctp_to_cla",
        "ctm_p2p_cla_to_cla",
        "ctm_p2p_ctp_to_ctp",
        "ctm_reset_wire_or_mode",
        "ctm_reset_p2p_mode",
        "ctm_reset_all_modes",
        "ctm_all_source_select",
    }

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
        default_loops: int = 4,
        group_env: str | None = "DTP_TEST_LOOPS",
        **seq_kwargs,
    ) -> list:
        """Run a sequence class multiple times with deterministic per-loop seeds."""
        scenario = seq_kwargs.get("scenario")
        if group_env == "DTP_JTAG2AXI_TEST_LOOPS":
            if scenario in self.JTAG2AXI_DEFAULT_LOOP_SCENARIOS:
                default_loops = max(default_loops, 16)
            elif scenario in self.JTAG2AXI_ONE_PASS_SCENARIOS:
                default_loops = 1
                group_env = None
        elif group_env == "DTP_SCAN_TEST_LOOPS":
            if scenario in self.SCAN_DEFAULT_LOOP_SCENARIOS:
                default_loops = max(default_loops, 16)
            elif scenario in self.SCAN_ONE_PASS_SCENARIOS:
                default_loops = 1
                group_env = None
        elif group_env == "DTP_XTRIG_TEST_LOOPS":
            if scenario in self.XTRIG_DEFAULT_LOOP_SCENARIOS:
                default_loops = max(default_loops, 16)
            elif scenario in self.XTRIG_ONE_PASS_SCENARIOS:
                default_loops = 1
                group_env = None

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
        for name in (
            "feat_ctrl_sip_debug",
            "feat_ctrl_soc_debug",
            "feat_ctrl_ap_debug",
            "feat_ctrl_sep_debug",
            "feat_ctrl_fuse_test",
        ):
            if hasattr(dut, name):
                getattr(dut, name).value = 1
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
