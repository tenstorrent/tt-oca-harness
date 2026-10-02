# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP UVM environment: agents, the primary-TAP scan builder, reference models, scoreboards."""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_env

from .dtp_axi_agent import DtpAxiAgent
from .dtp_axi_scoreboard import DtpAxiScoreboard
from .dtp_bypass_ref_model import DtpBypassRefModel
from .dtp_idcode_ref_model import DtpIdcodeRefModel
from .dtp_ir_decode_ref_model import DtpIrDecodeRefModel
from .dtp_jtag_agent import DtpJtagAgent
from .dtp_jtag_scan_builder import DtpJtagScanBuilder
from .dtp_scoreboard import DtpScoreboard
from .dtp_stap_ds_agent import DtpStapDsAgent
from .dtp_types import DTP_FEATURE_BYPASS, DTP_FEATURE_IDCODE
from .dtp_xtrig_agent import DtpXtrigAgent


class DtpEnv(uvm_env):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.jtag_agent = DtpJtagAgent("jtag_agent", self)
        self.axi_agent = DtpAxiAgent("axi_agent", self)
        self.xtrig_agent = DtpXtrigAgent("xtrig_agent", self)
        # Downstream STAP TAPs (attached per test via cfg.stap_ds_attach).
        self.stap_ds_agent = DtpStapDsAgent("stap_ds_agent", self)
        self.scan_builder = DtpJtagScanBuilder("scan_builder", self)
        self.ir_decode_ref_model = DtpIrDecodeRefModel("ir_decode_ref_model", self)
        self.idcode_ref_model = DtpIdcodeRefModel("idcode_ref_model", self)
        self.bypass_ref_model = DtpBypassRefModel("bypass_ref_model", self)
        self.scoreboard = DtpScoreboard("scoreboard", self)
        # Shared-VIP AXI scoreboard (opt-in; inert unless the test enables it).
        self.axi_scoreboard = DtpAxiScoreboard("axi_scoreboard", self)

    def connect_phase(self) -> None:
        scans = self.scan_builder.scan_ap
        events = self.scan_builder.event_ap
        sb = self.scoreboard
        sb.scan_builder = self.scan_builder
        # Driver-broadcast completed operations.
        self.jtag_agent.ap.connect(sb.op_export)
        events.connect(self.ir_decode_ref_model.analysis_export)
        scans.connect(self.ir_decode_ref_model.scan_export)
        self.ir_decode_ref_model.expected_ap.connect(sb.ir_decode_expected_export)
        for feature, model in (
            (DTP_FEATURE_IDCODE, self.idcode_ref_model),
            (DTP_FEATURE_BYPASS, self.bypass_ref_model),
        ):
            scans.connect(model.analysis_export)
            events.connect(model.event_export)
            model.expected_ap.connect(sb.expected_export(feature))
            scans.connect(sb.observed_export(feature))
