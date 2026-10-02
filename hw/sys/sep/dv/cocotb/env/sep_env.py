# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP UVM environment: AXI master agents (CPU-LSU + SMN-inbound) + scoreboard."""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_env

from .sep_axi_agent import SepAxiAgent
from .sep_axi_monitor import SepAxiMonitor
from .sep_scoreboard import SepScoreboard


class SepEnv(uvm_env):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        # Primary stimulus: CPU-LSU master (prefix s_axi, no inbound filter).
        self.axi_agent = SepAxiAgent("axi_agent", self)
        # Secondary: SMN-inbound external master (prefix m_axi), idle unless a test
        # drives it. Its path crosses the inbound filter, which blocks by default unless
        # sep_debug=1. axi_prefix must be set before the agent's build_phase runs.
        self.ext_axi_agent = SepAxiAgent("ext_axi_agent", self)
        self.ext_axi_agent.axi_prefix = "m_axi"
        self.scoreboard = SepScoreboard("scoreboard", self)
        # Passive raw-pin protocol/integrity monitors (independent of the agents;
        # the in-tb substitute for the Verilator-disabled RTL assertions). One per
        # AXI bus. The CPU-LSU bus has no inbound filter, so a DECERR there is a
        # real decode bug (fail). The external SMN-inbound bus' inbound filter
        # routes blocked accesses to DECERR (the gating test asserts
        # that), so the external monitor tallies DECERR without failing -- it still
        # catches all-X data on a *successful* external read.
        self.axi_monitor = SepAxiMonitor("axi_monitor", self)
        self.axi_monitor.bus_prefix = "s_axi"
        self.axi_monitor.fail_decerr = True
        self.ext_axi_monitor = SepAxiMonitor("ext_axi_monitor", self)
        self.ext_axi_monitor.bus_prefix = "m_axi"
        self.ext_axi_monitor.fail_decerr = False

    def connect_phase(self) -> None:
        # Driver-broadcast completed transactions -> value scoreboard. Only the
        # CPU-LSU agent feeds the scoreboard's expected-value check; the external
        # probe results (intentional DECERR/timeout when blocked) are inspected
        # inline by the inbound-filter-gating test, not value-checked here.
        self.axi_agent.ap.connect(self.scoreboard.analysis_export)
