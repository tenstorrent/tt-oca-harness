# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP UVM environment configuration object."""

from __future__ import annotations

import random
from typing import Any

from cocotb.triggers import Event
from pyuvm import uvm_object

from .dtp_xtrig_types import DtpXtrigCtpShadow

__all__ = ["DtpEnvCfg"]


class DtpEnvCfg(uvm_object):
    """Shared environment configuration / handshakes for the DTP UVM TB."""

    def __init__(self, name: str = "DtpEnvCfg") -> None:
        super().__init__(name)
        # Timing (defaults; randomize_timing() may override per run).
        self.jtag_period_ns = 100
        self.sys_clk_period_ns = 10
        self.idle_tck = 64
        # OCAH AXI RAM memory size (bytes)
        self.axi_mem_size = 2**16
        self.otp_axil_mem_size = 2**16
        # Set by the base test once clocks are running and resets released, so
        # the JTAG/AXI agents start their BFMs at the right time.
        self.reset_done = Event("dtp_reset_done")
        # Published by the AXI agent once the OCAH AXI RAM exists, so
        # sequences/scoreboard can backdoor-check the SMC fabric memory.
        self.axi_ram = None
        self.smc_otp_axil_ram = None
        self.sep_otp_axil_ram = None
        self.jtag2axi_responders: dict[str, Any] = {}
        # Scoreboard features that must end with at least one comparison;
        # set by dtp_base_test from the test's required_features.
        self.required_features: set[str] = set()
        # Shared AXI checker: opt-in per test via
        # dtp_base_test.use_axi_scoreboard. Populated by DtpAxiScoreboard
        # (scoreboard/models/per-bridge checkers) and DtpAxiAgent
        # (monitors/watchers/port histories).
        self.axi_scoreboard_enabled = False
        self.axi_checker_required_ids: set[str] = set()
        self.axi_checker_target_required_ids: set[str] = set()
        self.axi_checker_stream_minimums: dict[str, int] = {}
        self.axi_scoreboard = None
        self.axi_models: dict[str, Any] = {}
        self.axi_target_evidence: dict[str, Any] = {}
        self.axi_monitors: dict[str, Any] = {}
        self.axi_watchers: dict[str, Any] = {}
        self.axi_port_histories: dict[str, Any] = {}
        self.xtrig_axil = None
        self.xtrig_bfm = None
        # Programmed CTP mode/polarity, written by the XTRIG sequences and kept
        # across passes because the DUT keeps its configuration between them.
        self.xtrig_ctp_shadow = DtpXtrigCtpShadow()
        self.xtrig_num_ctp = 16
        self.xtrig_num_int_ct = 10
        # Downstream STAP TAPs: the STAP names whose host port
        # gets a reactive ocah_jtag_vip slave device spliced behind it (empty
        # = every port keeps its wire loopback), plus the per-port slave
        # sequence and device map published by DtpStapDsAgent.
        self.stap_ds_attach: set[str] = set()
        # Extended STAP host scan: True places the tb_top host segment
        # between the host scan-out and scan-in (False keeps the loopback).
        self.stap_host_segment = False
        # DtpTbIf handle published by the base test; agents and sequences bind
        # to the HDL top through it.
        self.tb_if: Any = None
        self.stap_ds_seq: dict[str, Any] = {}
        self.stap_ds_device: dict[str, Any] = {}

    def randomize_timing(self, seed: int | None = None) -> None:
        """Randomize the JTAG TCK and system-clock periods for timing variety.

        Draws the JTAG TCK period (100-1000 ns) and the core clock period
        (10-100 ns) to exercise the TCK-vs-core-clock ratio. Uses a dedicated
        RNG seeded from the runner's
        ``RANDOM_SEED`` so ``run_dv.py --seed`` reproduces the chosen periods
        without disturbing global ``random`` state used elsewhere.
        """
        rng = random.Random(seed)
        self.jtag_period_ns = rng.randint(100, 1000)
        self.sys_clk_period_ns = rng.randint(10, 100)
