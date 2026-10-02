# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ir_decode reference model: the decoded-instruction one-hot follows each instruction load.

Once a plain 6-bit instruction becomes active (the TCK cycle leaving
Update-IR), the DUT's one-hot decoded-instruction observable must equal
``1 << instruction``. Consumes the per-TCK event stream (``write``) and the
reconstructed IR scans (``scan_export``) through a ``DtpJtagIrModel``,
re-baselines on power-on reset through the TB interface, and publishes one
``DtpExpectedItem`` per instruction load; the scoreboard samples
``jtag_ptap_inst_decoded`` when the item arrives, in the same time step. No
comparison, no reporting. The SV-UVM twin is ``dtp_ir_decode_ref_model``.
"""

from __future__ import annotations

from ocah_jtag_vip import OcahJtagEvent, OcahJtagScanItem
from ocah_lib import OcahRefModel
from pyuvm import ConfigDB

from .dtp_expected_item import DtpAnalysisImp, DtpExpectedItem
from .dtp_jtag_ir_model import DtpJtagIrModel

__all__ = ["DtpIrDecodeRefModel"]


class DtpIrDecodeRefModel(OcahRefModel):
    """Per-TCK events in, one expected one-hot per committed instruction out."""

    def build_phase(self) -> None:
        super().build_phase()
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.scan_export = DtpAnalysisImp("scan_export", self, self.write_scan)
        self._model = DtpJtagIrModel()

    def write(self, item: OcahJtagEvent) -> None:
        """Per-TCK events: the instruction commits on the cycle leaving Update-IR."""
        self._model.sync_power_on_reset(self.tb_if.sample("por_assert_count"))
        if not self._model.on_event(item):
            return
        ir = self._model.ir()
        self.expected_ap.write(
            DtpExpectedItem(
                expected=1 << ir,
                context=f"ir=0x{ir:02x} load={self._model.ir_loads()}",
                time_ns=item.time_ns,
            )
        )

    def write_scan(self, item: OcahJtagScanItem) -> None:
        """Reconstructed scans: IR scans feed the pending instruction."""
        self._model.sync_power_on_reset(self.tb_if.sample("por_assert_count"))
        if item.is_ir:
            self._model.on_ir_scan(item)
