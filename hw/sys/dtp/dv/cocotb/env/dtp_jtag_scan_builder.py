# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary-TAP scan reconstruction for the DTP reference models.

Runs the shared passive ``OcahJtagMasterMonitor`` on the primary TAP for the
whole test and republishes its two streams as analysis ports: ``scan_ap``
carries each reconstructed IR or DR scan, and ``event_ap`` each TCK step and
TRST edge, a scan before the step that completed it. A power-on reset moves
the TAP to Test-Logic-Reset with TCK idle, which the bus cannot show, so the
monitor is resynchronized on every power-on reset assertion. The SV-UVM twin
is ``dtp_jtag_scan_builder`` with the shared JTAG env's event port.
"""

from __future__ import annotations

from cocotb.triggers import FallingEdge
from ocah_jtag_vip import OcahJtagMasterMonitor
from pyuvm import ConfigDB, uvm_analysis_port, uvm_component

__all__ = ["DtpJtagScanBuilder"]


class DtpJtagScanBuilder(uvm_component):
    """Passive primary-TAP monitor publishing scans and per-TCK events."""

    def build_phase(self) -> None:
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.scan_ap = uvm_analysis_port("scan_ap", self)
        self.event_ap = uvm_analysis_port("event_ap", self)
        self.monitor: OcahJtagMasterMonitor | None = None

    async def run_phase(self) -> None:
        self.monitor = OcahJtagMasterMonitor(
            self.tb_if.jtag,
            name="dtp_ptap_scan_monitor",
            signal_map=self.tb_if.JTAG_SIGNAL_MAP,
        )
        self.monitor.add_item_callback(self.scan_ap.write)
        self.monitor.add_event_callback(self.event_ap.write)
        await self.monitor.start()
        while True:
            await FallingEdge(self.tb_if.por_rst_n)
            self.monitor.resync()
