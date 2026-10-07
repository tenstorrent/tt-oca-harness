# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP environment: agents, the primary-TAP scan builder, reference models, scoreboards.

Builds the JTAG, bridge-port, XTRIG and downstream-STAP agents, the scan
builder that reconstructs primary-TAP scans from the pins, one reference model
per scoreboard feature, the always-on ``DtpScoreboard`` and the opt-in shared
AXI scoreboard, and wires every monitor and reference-model stream in
``connect_phase``. The SV-UVM twin is ``dtp_env``.
"""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_env

from .dtp_axi_agent import DtpAxiAgent
from .dtp_axi_scoreboard import DtpAxiScoreboard
from .dtp_bypass_ref_model import DtpBypassRefModel
from .dtp_idcode_ref_model import DtpIdcodeRefModel
from .dtp_ir_decode_ref_model import DtpIrDecodeRefModel
from .dtp_jtag2axi_req_ref_model import DtpJtag2AxiReqRefModel
from .dtp_jtag2axi_status_ref_model import DtpJtag2AxiStatusRefModel
from .dtp_jtag_agent import DtpJtagAgent
from .dtp_jtag_scan_builder import DtpJtagScanBuilder
from .dtp_scoreboard import DtpScoreboard
from .dtp_stap_ds_agent import DtpStapDsAgent
from .dtp_types import (
    DTP_FEATURE_BYPASS,
    DTP_FEATURE_IDCODE,
    DTP_FEATURE_JTAG2AXI_STATUS,
    DTP_FEATURE_XTRIG_CSR,
    DTP_FEATURE_XTRIG_DECODE,
    JTAG2AXI_TARGETS,
)
from .dtp_xtrig_agent import DtpXtrigAgent
from .dtp_xtrig_csr_ref_model import DtpXtrigCsrRefModel
from .dtp_xtrig_decode_ref_model import DtpXtrigDecodeRefModel

__all__ = ["DtpEnv"]


class DtpEnv(uvm_env):
    """The DTP agents, reference models and scoreboards, and their connections."""

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
        self.xtrig_csr_ref_model = DtpXtrigCsrRefModel("xtrig_csr_ref_model", self)
        self.xtrig_decode_ref_model = DtpXtrigDecodeRefModel("xtrig_decode_ref_model", self)
        self.jtag2axi_req_ref_model = DtpJtag2AxiReqRefModel("jtag2axi_req_ref_model", self)
        self.jtag2axi_status_ref_model = DtpJtag2AxiStatusRefModel(
            "jtag2axi_status_ref_model", self
        )
        self.scoreboard = DtpScoreboard("scoreboard", self)
        # Shared-VIP AXI scoreboard (opt-in; inert unless the test enables it).
        self.axi_scoreboard = DtpAxiScoreboard("axi_scoreboard", self)

    def connect_phase(self) -> None:
        scans = self.scan_builder.scan_ap
        events = self.scan_builder.event_ap
        sb = self.scoreboard
        sb.scan_builder = self.scan_builder
        sb.xtrig_agent = self.xtrig_agent
        sb.axi_agent = self.axi_agent
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
        xtrig = self.xtrig_agent.item_ap
        for feature, model in (
            (DTP_FEATURE_XTRIG_CSR, self.xtrig_csr_ref_model),
            (DTP_FEATURE_XTRIG_DECODE, self.xtrig_decode_ref_model),
        ):
            xtrig.connect(model.analysis_export)
            model.expected_ap.connect(sb.expected_export(feature))
            xtrig.connect(sb.observed_export(feature))
        req = self.jtag2axi_req_ref_model
        status = self.jtag2axi_status_ref_model
        scans.connect(req.analysis_export)
        events.connect(req.event_export)
        req.expected_ap.connect(sb.jtag2axi_req_expected_export)
        scans.connect(status.analysis_export)
        events.connect(status.event_export)
        status.expected_ap.connect(sb.expected_export(DTP_FEATURE_JTAG2AXI_STATUS))
        scans.connect(sb.observed_export(DTP_FEATURE_JTAG2AXI_STATUS))
        for target, target_cfg in JTAG2AXI_TARGETS.items():
            source = target_cfg.monitor_name
            req.bind_port(target, source)
            status.bind_port(target, source)
            sb.bind_port(target, source)
            port = self.axi_agent.port_aps[target]
            port.connect(req.axi_export)
            port.connect(status.axi_export)
            port.connect(sb.jtag2axi_req_observed_export)
