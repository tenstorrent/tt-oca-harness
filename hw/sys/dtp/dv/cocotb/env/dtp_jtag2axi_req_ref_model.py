# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""jtag2axi_req reference model: every bridge transaction is the one its DMI accesses asked for.

Every AXI transaction a JTAG2AXI bridge launches is the system bus access its
Debug Module registers describe when the triggering DMI operation reaches it,
and no access reaches the port while the bridge's lifecycle disable is
asserted. Consumes the reconstructed scan stream (``write``), the per-TCK
event stream (``event_export``) and the transactions observed on the three
bridge ports (``axi_export``) through a ``DtpJtag2AxiTracker``, and publishes
one expected ``OcahAxiItem`` (direction, address, size, strobes, data) per
launched access on the lane of the port that will carry it. The scoreboard
pairs those in order with the observed transactions of the same port.
``DTP_J2A_REF_MODEL_NEGATIVE`` corrupts every predicted address so the pairing
must fail. No comparison, no reporting. The SV-UVM twin is
``dtp_jtag2axi_req_ref_model``.
"""

from __future__ import annotations

from dataclasses import replace

from ocah_axi_vip import OcahAxiItem
from ocah_jtag_vip import OcahJtagEvent, OcahJtagScanItem
from ocah_lib import OcahKnobs, OcahRefModel
from pyuvm import ConfigDB

from .dtp_expected_item import DtpAnalysisImp
from .dtp_jtag2axi_model import DtpJtag2AxiTracker

__all__ = ["DtpJtag2AxiReqRefModel"]

NEGATIVE_KNOB = "DTP_J2A_REF_MODEL_NEGATIVE"


class DtpJtag2AxiReqRefModel(OcahRefModel):
    """Scans in, one expected AXI item per launched bridge access out."""

    def build_phase(self) -> None:
        super().build_phase()
        self.event_export = DtpAnalysisImp("event_export", self, self.write_event)
        self.axi_export = DtpAnalysisImp("axi_export", self, self.write_axi)
        self.negative = OcahKnobs.is_set(NEGATIVE_KNOB)
        if self.negative:
            self.logger.warning(
                "NEGATIVE VALIDATION: every predicted bridge address is corrupted (%s)",
                NEGATIVE_KNOB,
            )
        self._tracker = DtpJtag2AxiTracker(ConfigDB().get(self, "", "tb_if"))
        # Bridge name -> the monitor publishing its port (the item `source`).
        self._source: dict[str, str] = {}

    def bind_port(self, target: str, source: str) -> None:
        """Name the monitor whose items carry a bridge's transactions."""
        self._source[target] = source
        self._tracker.bind_port(target, source)

    def write(self, item: OcahJtagScanItem) -> None:
        self._tracker.on_scan(item)

    def write_event(self, item: OcahJtagEvent) -> None:
        launched = self._tracker.on_event(item)
        if launched is None:
            return
        target, access = launched
        if target not in self._source:
            raise RuntimeError(f"bridge `{target}` has no bound port")
        when = int(item.time_ns or 0)
        self.expected_ap.write(
            replace(
                access,
                source=self._source[target],
                start_time_ns=when,
                end_time_ns=when,
                address=access.address ^ 0x4 if self.negative else access.address,
            )
        )

    def write_axi(self, item: OcahAxiItem) -> None:
        self._tracker.on_axi(item)
