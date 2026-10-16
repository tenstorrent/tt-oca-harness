# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""jtag2axi_req reference model: every bridge transaction is the one its JTAG request asked for.

Every AXI transaction a JTAG2AXI bridge launches is the one its JTAG request
asked for, and a request never reaches the bus while the bridge's lifecycle
disable is asserted. Consumes the reconstructed scan stream (``write``) and
the per-TCK event stream (``event_export``) through a ``DtpJtagIrModel`` to
know the active instruction, decodes every DR scan that addresses a bridge
register through a ``DtpJtag2AxiModel``, feeds that model the completions
observed on the three bridge ports (``axi_export``) so its series address and
busy state follow the DUT, and publishes one expected ``OcahAxiItem``
(direction, address, size, strobes, data) per launched transaction on the
lane of the port that will carry it. A scan takes effect on the TCK cycle
that leaves Update-DR, which a scan held in Pause-DR delays. The scoreboard
pairs those in order with the observed transactions of the same port. Gating
is read from the TB interface's debug disables at that cycle and at each
completion, which drops the requests queued behind it while the bridge is
disabled; a TAP reset (TRST, TMS, power-on) resets the bridge model, and a
system reset aborts its in-flight transactions. ``DTP_J2A_REF_MODEL_NEGATIVE``
corrupts every predicted address so the pairing must fail. No comparison, no
reporting. The SV-UVM twin is ``dtp_jtag2axi_req_ref_model``.
"""

from __future__ import annotations

from dataclasses import replace

from ocah_axi_vip import OcahAxiItem
from ocah_jtag_vip import OcahJtagEvent, OcahJtagScanItem, OcahJtagState
from ocah_lib import OcahKnobs, OcahRefModel
from pyuvm import ConfigDB

from .dtp_expected_item import DtpAnalysisImp
from .dtp_jtag2axi_model import DtpJ2aRequest, DtpJ2aScanKind, DtpJtag2AxiModel
from .dtp_jtag_ir_model import DtpJtagIrModel
from .dtp_types import JTAG2AXI_TARGETS, DtpJtag2AxiTargetCfg

__all__ = ["DtpJtag2AxiReqRefModel"]

NEGATIVE_KNOB = "DTP_J2A_REF_MODEL_NEGATIVE"


class DtpJtag2AxiReqRefModel(OcahRefModel):
    """Scans in, one expected AXI item per launched bridge transaction out."""

    def build_phase(self) -> None:
        super().build_phase()
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.event_export = DtpAnalysisImp("event_export", self, self.write_event)
        self.axi_export = DtpAnalysisImp("axi_export", self, self.write_axi)
        # Negative validation: predict a wrong address on every request.
        self.negative = OcahKnobs.is_set(NEGATIVE_KNOB)
        if self.negative:
            self.logger.warning(
                "NEGATIVE VALIDATION: every predicted bridge address is corrupted (%s)",
                NEGATIVE_KNOB,
            )
        self._ir = DtpJtagIrModel()
        self._bridge = DtpJtag2AxiModel()
        # Bridge name <-> the monitor publishing its port (the item `source`).
        self._source: dict[str, str] = {}
        self._target_by_source: dict[str, str] = {}
        self._sys_rst_seen = 0
        # The bridge scan waiting for the TAP to leave Update-DR.
        self._pending: tuple[DtpJtag2AxiTargetCfg, DtpJ2aRequest] | None = None

    def bind_port(self, target: str, source: str) -> None:
        """Name the monitor whose items carry a bridge's transactions."""
        self._source[target] = source
        self._target_by_source[source] = target

    def write(self, item: OcahJtagScanItem) -> None:
        """Reconstructed scans: IR scans track the instruction; bridge DR scans are applied."""
        self._sync_reset()
        if item.is_ir:
            self._ir.on_ir_scan(item)
            return
        if not self._ir.ir_known():
            return
        kind, target, request = self._bridge.decode(self._ir.ir(), item)
        if kind is DtpJ2aScanKind.NONE or target is None or request is None:
            return
        self._pending = (target, request)

    def _apply_update(
        self, target: DtpJtag2AxiTargetCfg, request: DtpJ2aRequest, end: float
    ) -> None:
        """The pending scan's Update-DR, on the TCK cycle that leaves it."""
        if self.tb_if.dbg_field(target.dbg_disable_bit):
            self._bridge.gated(target.name)
            return
        expected = self._bridge.update(target, request, end)
        if expected is None or self._bridge.abort_pending:
            return
        if target.name not in self._source:
            raise RuntimeError(f"bridge `{target.name}` has no bound port")
        address = expected.address ^ 0x4 if self.negative else expected.address
        self.expected_ap.write(
            replace(
                expected,
                source=self._source[target.name],
                start_time_ns=int(end),
                end_time_ns=int(end),
                address=address,
            )
        )

    def write_event(self, item: OcahJtagEvent) -> None:
        self._sync_reset()
        if item.kind == "STEP" and item.trst_n:
            self._bridge.tck_step(item.time_ns or 0.0)
        if (
            self._pending is not None
            and item.kind == "STEP"
            and item.trst_n
            and self._ir.tap_state() is OcahJtagState.UPDATE_DR
        ):
            self._apply_update(*self._pending, item.time_ns or 0.0)
            self._pending = None
        self._ir.on_event(item)
        self._consume_tap_reset()

    def write_axi(self, item: OcahAxiItem) -> None:
        target = self._target_by_source.get(item.source)
        if target is None:
            raise RuntimeError(f"AXI item from unbound port `{item.source}`")
        disabled = bool(self.tb_if.dbg_field(JTAG2AXI_TARGETS[target].dbg_disable_bit))
        self._bridge.complete(target, item, disabled=disabled)

    def _sync_reset(self) -> None:
        """Power-on reset resets the TAP and every bridge; a system reset aborts the AXI side."""
        self._ir.sync_power_on_reset(self.tb_if.sample("por_assert_count"))
        self._consume_tap_reset()
        sys_rst = self.tb_if.sample("sys_rst_assert_count")
        if sys_rst != self._sys_rst_seen:
            self._sys_rst_seen = sys_rst
            self._bridge.system_reset()

    def _consume_tap_reset(self) -> None:
        """The bridges' JTAG-side registers reset whenever the TAP is in Test-Logic-Reset."""
        if self._ir.take_tap_reset():
            self._pending = None
            self._bridge.reset()
