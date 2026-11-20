# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""jtag2axi_status reference model: each bridge capture shows the bridge's DMI state.

A DMI capture presents the address and data of the last DMI update, the read
response after a read, and the sticky DMI status; a DTMCS capture presents
the bridge's fixed DTM fields and the same status. Consumes the reconstructed
scan stream (``write``), the per-TCK event stream (``event_export``) and the
transactions observed on the three bridge ports (``axi_export``) through a
``DtpJtag2AxiTracker`` and publishes one ``DtpJtag2AxiStatusItem`` per scan
item, so the scoreboard pairs the two streams in lockstep; scans that are not
a bridge capture, and captures while the PTAP 3DCR select is set, carry no
contract. No comparison, no reporting. The SV-UVM twin is
``dtp_jtag2axi_status_ref_model``.
"""

from __future__ import annotations

from ocah_axi_vip import OcahAxiItem
from ocah_jtag_vip import OcahJtagEvent, OcahJtagScanItem
from ocah_lib import OcahRefModel
from pyuvm import ConfigDB

from .dtp_expected_item import DtpAnalysisImp
from .dtp_jtag2axi_model import DtpJtag2AxiTracker

__all__ = ["DtpJtag2AxiStatusRefModel"]


class DtpJtag2AxiStatusRefModel(OcahRefModel):
    """Scans in, one expected capture (or no contract) per scan out."""

    def build_phase(self) -> None:
        super().build_phase()
        self.event_export = DtpAnalysisImp("event_export", self, self.write_event)
        self.axi_export = DtpAnalysisImp("axi_export", self, self.write_axi)
        self._tracker = DtpJtag2AxiTracker(ConfigDB().get(self, "", "tb_if"))

    def bind_port(self, target: str, source: str) -> None:
        """Name the monitor whose items carry a bridge's transactions."""
        self._tracker.bind_port(target, source)

    def write(self, item: OcahJtagScanItem) -> None:
        self.expected_ap.write(self._tracker.on_scan(item))

    def write_event(self, item: OcahJtagEvent) -> None:
        self._tracker.on_event(item)

    def write_axi(self, item: OcahAxiItem) -> None:
        self._tracker.on_axi(item)
