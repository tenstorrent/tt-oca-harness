# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP environment configuration: timing, memory sizes, and the handles the env publishes.

The base test builds one ``DtpEnvCfg``, draws its timing from the runner seed,
fills the per-test controls (required features, AXI scoreboard policy, STAP
attach set), and publishes it through ``ConfigDB``; the agents and the AXI
scoreboard publish their runtime handles on it in ``run_phase`` and
``build_phase``. The SV-UVM twins are ``dtp_test_cfg`` (timing and per-test
controls) and ``dtp_env_cfg``.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from cocotb.triggers import Event
from ocah_lib import OcahRng
from pyuvm import uvm_object

from .dtp_xtrig_ctp_shadow import DtpXtrigCtpShadow

if TYPE_CHECKING:
    from ocah_axi_vip import (
        OcahAxiLiteMasterSequence,
        OcahAxiLiteMonitor,
        OcahAxiLiteProtocolWatcher,
        OcahAxiLiteSlaveSequence,
        OcahAxiMonitor,
        OcahAxiProtocolWatcher,
        OcahAxiRefModel,
        OcahAxiScoreboard,
        OcahAxiSlaveSequence,
    )
    from ocah_checker import OcahChecker
    from ocah_jtag_vip import OcahJtagDevice, OcahJtagSlaveSequence

    from .dtp_axi_port_history import DtpAxiPortHistory
    from .dtp_tb_if import DtpTbIf
    from .dtp_xtrig_agent import DtpXtrigBfm

__all__ = ["DtpEnvCfg"]


class DtpEnvCfg(uvm_object):
    """Timing, memory sizes, per-test controls, and the runtime handles of the DTP env."""

    def __init__(self, name: str = "DtpEnvCfg") -> None:
        super().__init__(name)
        # Timing (defaults; randomize_timing() may override per run).
        self.jtag_period_ns = 100
        self.sys_clk_period_ns = 10
        self.idle_tck = 64
        # OCAH AXI RAM memory size (bytes)
        self.axi_mem_size = 2**16
        self.otp_axil_mem_size = 2**16
        # Seed of the SMC fabric responder's BUSER and RUSER draws.
        self.resp_user_seed = 0
        # Set by the base test once clocks are running and resets released, so
        # the JTAG/AXI agents start their BFMs at the right time.
        self.reset_done = Event()
        # Published by the AXI agent once the OCAH AXI RAM exists, so
        # sequences/scoreboard can backdoor-check the SMC fabric memory.
        self.axi_ram: OcahAxiSlaveSequence | None = None
        self.smc_otp_axil_ram: OcahAxiLiteSlaveSequence | None = None
        self.sep_otp_axil_ram: OcahAxiLiteSlaveSequence | None = None
        self.jtag2axi_responders: dict[str, OcahAxiSlaveSequence | OcahAxiLiteSlaveSequence] = {}
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
        self.axi_scoreboard: OcahAxiScoreboard | None = None
        self.axi_models: dict[str, OcahAxiRefModel] = {}
        self.axi_target_evidence: dict[str, OcahChecker] = {}
        self.axi_monitors: dict[str, OcahAxiMonitor | OcahAxiLiteMonitor] = {}
        self.axi_watchers: dict[str, OcahAxiProtocolWatcher | OcahAxiLiteProtocolWatcher] = {}
        self.axi_port_histories: dict[str, DtpAxiPortHistory] = {}
        self.xtrig_axil: OcahAxiLiteMasterSequence | None = None
        self.xtrig_bfm: DtpXtrigBfm | None = None
        # Programmed CTP mode/polarity, written by the XTRIG sequences and kept
        # across passes because the DUT keeps its configuration between them.
        self.xtrig_ctp_shadow = DtpXtrigCtpShadow()
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
        self.tb_if: DtpTbIf | None = None
        self.stap_ds_seq: dict[str, OcahJtagSlaveSequence] = {}
        self.stap_ds_device: dict[str, OcahJtagDevice] = {}

    def randomize_timing(self, seed: int) -> None:
        """Randomize the JTAG TCK and system-clock periods for timing variety.

        Draws an even JTAG TCK period (100-1000 ns) and an even core clock
        period (10-100 ns), so both half periods are whole nanoseconds, to
        exercise the TCK-vs-core-clock ratio. Uses a dedicated RNG seeded from
        the runner's ``RANDOM_SEED`` salted by ``timing`` so ``run_dv.py
        --seed`` reproduces the chosen periods without disturbing global
        ``random`` state.
        """
        rng = random.Random(OcahRng.salted_seed(seed, "timing"))
        self.jtag_period_ns = 2 * rng.randint(50, 500)
        self.sys_clk_period_ns = 2 * rng.randint(5, 50)
