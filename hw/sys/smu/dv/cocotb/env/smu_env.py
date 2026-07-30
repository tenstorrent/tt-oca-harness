# SPDX-License-Identifier: Apache-2.0
"""SMU OSS PyUVM environment."""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_env

from .smu_scoreboard import SmuScoreboard


class SmuEnv(uvm_env):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.scoreboard = SmuScoreboard("scoreboard", self)
        # Agents are created on demand by sequences (JTAG / AXI) against cocotb.top.
        self.jtag = None
        self.axi = None
