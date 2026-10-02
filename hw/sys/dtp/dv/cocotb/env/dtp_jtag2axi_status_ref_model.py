# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""jtag2axi_status reference model: each bridge capture shows the outcome of its transactions.

The status a SINGLE_OP or SERIES_CTRL scan captures is the outcome of the
bridge's completed AXI transactions (SUCCESS, SLVERR, DECERR, or BUSY_OR_FULL
while one is pending), and the data a SINGLE_OP capture returns after a
completed OKAY read is the word the bus returned. Consumes the reconstructed
scan stream (``write``) and the per-TCK event stream (``event_export``)
through a ``DtpJtagIrModel``, applies every bridge-register DR scan and every
observed bridge completion (``axi_export``) to a ``DtpJtag2AxiModel``, and
publishes one ``DtpJtag2AxiStatusItem`` per scan item so the scoreboard pairs
the two streams in lockstep; scans that are not a bridge capture, captures
while the PTAP 3DCR select is set, captures inside the CDC settle window
after a completion, and the captures the bridge model exempts carry no
contract. Series-data captures (the pipelined read FIFO) are not predicted.
No comparison, no reporting. The SV-UVM twin is
``dtp_jtag2axi_status_ref_model``.
"""

from __future__ import annotations

from cocotb.utils import get_sim_time
from ocah_axi_vip import OcahAxiItem
from ocah_jtag_vip import OcahJtagEvent, OcahJtagScanItem
from ocah_lib import OcahRefModel
from pyuvm import ConfigDB

from .dtp_expected_item import DtpAnalysisImp
from .dtp_jtag2axi_model import DtpJ2aScanKind, DtpJtag2AxiModel
from .dtp_jtag2axi_status_item import DtpJtag2AxiStatusItem
from .dtp_jtag_ir_model import DtpJtagIrModel
from .dtp_types import DTP_J2A_STATUS_SETTLE_TCK, JTAG2AXI_TARGETS

__all__ = ["DtpJtag2AxiStatusRefModel"]

_CAPTURES = (DtpJ2aScanKind.SINGLE_OP, DtpJ2aScanKind.SERIES_CTRL)


class DtpJtag2AxiStatusRefModel(OcahRefModel):
    """Scans in, one expected capture (or no contract) per scan out."""

    def build_phase(self) -> None:
        super().build_phase()
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.event_export = DtpAnalysisImp("event_export", self, self.write_event)
        self.axi_export = DtpAnalysisImp("axi_export", self, self.write_axi)
        self._ir = DtpJtagIrModel()
        # CDC window after a completion during which a capture is not checkable.
        self._bridge = DtpJtag2AxiModel(
            settle_window_ns=DTP_J2A_STATUS_SETTLE_TCK * self.cfg.jtag_period_ns
        )
        self._target_by_source: dict[str, str] = {}
        self._sys_rst_seen = 0

    def bind_port(self, target: str, source: str) -> None:
        """Name the monitor whose items carry a bridge's transactions."""
        self._target_by_source[source] = target

    def write(self, item: OcahJtagScanItem) -> None:
        """One expected capture per scan item, predicted at its Capture-DR, then its Update-DR."""
        expected = DtpJtag2AxiStatusItem(compare=False, time_ns=item.end_time_ns)
        self._sync_reset()
        if item.is_ir:
            self._ir.on_ir_scan(item)
            self.expected_ap.write(expected)
            return
        self._ir.on_dr_scan(item)
        kind, target, request = (
            self._bridge.decode(self._ir.ir(), item)
            if self._ir.ir_known()
            else (DtpJ2aScanKind.NONE, None, None)
        )
        if kind is not DtpJ2aScanKind.NONE and target is not None and request is not None:
            if kind in _CAPTURES and self._ir.ptap_select_clear():
                expected = self._bridge.predict_capture(
                    target,
                    kind,
                    item.start_time_ns or 0.0,
                    context=f"{target.name} {kind.name} bits={item.bit_count}",
                )
            if self.tb_if.dbg_field(target.dbg_disable_bit):
                self._bridge.gated(target.name)
            else:
                self._bridge.update(target, request, item.end_time_ns or 0.0)
        self.expected_ap.write(expected)

    def write_event(self, item: OcahJtagEvent) -> None:
        self._sync_reset()
        self._ir.on_event(item)
        self._consume_tap_reset()

    def write_axi(self, item: OcahAxiItem) -> None:
        target = self._target_by_source.get(item.source)
        if target is None:
            raise RuntimeError(f"AXI item from unbound port `{item.source}`")
        disabled = bool(self.tb_if.dbg_field(JTAG2AXI_TARGETS[target].dbg_disable_bit))
        self._bridge.complete(target, item, disabled)

    def _sync_reset(self) -> None:
        self._ir.sync_power_on_reset(self.tb_if.sample("por_assert_count"))
        self._consume_tap_reset()
        sys_rst = self.tb_if.sample("sys_rst_assert_count")
        if sys_rst != self._sys_rst_seen:
            self._sys_rst_seen = sys_rst
            self._bridge.abort_in_flight(float(get_sim_time("ns")))

    def _consume_tap_reset(self) -> None:
        """The bridges' JTAG-side registers reset whenever the TAP is in Test-Logic-Reset."""
        if self._ir.take_tap_reset():
            self._bridge.reset()
