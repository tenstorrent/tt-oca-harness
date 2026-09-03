# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP UVM environment: JTAG agent + AXI memory agent + scoreboard."""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_env

from .dtp_axi_agent import DtpAxiAgent
from .dtp_axi_scoreboard import DtpAxiScoreboard
from .dtp_jtag_agent import DtpJtagAgent
from .dtp_scoreboard import DtpScoreboard
from .dtp_stap_ds_agent import DtpStapDsAgent
from .dtp_xtrig_agent import DtpXtrigAgent


class DtpEnv(uvm_env):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.jtag_agent = DtpJtagAgent("jtag_agent", self)
        self.axi_agent = DtpAxiAgent("axi_agent", self)
        self.xtrig_agent = DtpXtrigAgent("xtrig_agent", self)
        # Downstream STAP TAPs (attached per test via cfg.stap_ds_attach).
        self.stap_ds_agent = DtpStapDsAgent("stap_ds_agent", self)
        self.scoreboard = DtpScoreboard("scoreboard", self)
        # Shared-VIP AXI scoreboard (opt-in; inert unless the test enables it).
        self.axi_scoreboard = DtpAxiScoreboard("axi_scoreboard", self)

    def connect_phase(self) -> None:
        # Driver-broadcast completed transactions -> scoreboard.
        self.jtag_agent.ap.connect(self.scoreboard.analysis_export)
