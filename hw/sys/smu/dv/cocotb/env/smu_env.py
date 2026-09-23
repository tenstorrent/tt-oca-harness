# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMU OSS PyUVM environment."""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_env

from .smu_scoreboard import SmuScoreboard


class SmuEnv(uvm_env):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.scoreboard = SmuScoreboard("scoreboard", self)
        # Agents are created on demand by sequences (JTAG / AXI) against cocotb.top;
        # the outbound SMN responder is the exception and lives on cfg.axi_out_mem.
        self.jtag = None
        self.axi = None
