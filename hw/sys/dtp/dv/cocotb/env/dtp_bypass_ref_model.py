# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""bypass reference model: scans under a bypass-class instruction return delayed TDI.

Every DR scan of at most 64 bits while a bypass-class instruction is active
and the PTAP 3DCR select is clear returns TDI delayed by one TCK (the
one-bit bypass register: both IEEE encodings and the undefined opcodes
0x0F and 0x2D-0x3C), INV_BYPASS the inverted delayed image behind a
captured 1, and ZERO_LENGTH_BYPASS TDI itself. Consumes the reconstructed
scan stream (``write``) and the per-TCK event stream (``event_export``)
through a ``DtpJtagIrModel``, re-baselines on power-on reset through the TB
interface, and publishes one ``DtpExpectedItem`` per scan item so the
scoreboard pairs the two streams in lockstep; scans outside the contract
carry none. No comparison, no reporting. The SV-UVM twin is
``dtp_bypass_ref_model``.
"""

from __future__ import annotations

from ocah_jtag_vip import OcahJtagEvent, OcahJtagScanItem, OcahJtagTapRefModel
from ocah_lib import OcahRefModel
from pyuvm import ConfigDB

from .dtp_expected_item import DtpAnalysisImp, DtpExpectedItem
from .dtp_jtag_ir_model import DtpJtagIrModel
from .dtp_types import DtpJtagInstr

__all__ = ["DtpBypassRefModel"]

MAX_SCAN_BITS = 64

# The one-bit bypass register: both IEEE encodings and the opcodes neither
# instruction table defines past the JTAG2AXI TDRs.
_ONE_BIT_BYPASS = frozenset(
    [int(DtpJtagInstr.BYPASS_00), int(DtpJtagInstr.BYPASS_3F), 0x0F, *range(0x2D, 0x3D)]
)


class DtpBypassRefModel(OcahRefModel):
    """Reconstructed scans in, one expectation (or no contract) per scan out."""

    def build_phase(self) -> None:
        super().build_phase()
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.event_export = DtpAnalysisImp("event_export", self, self.write_event)
        self._model = DtpJtagIrModel()

    def write(self, item: OcahJtagScanItem) -> None:
        self._model.sync_power_on_reset(self.tb_if.sample("por_assert_count"))
        expected = DtpExpectedItem(compare=False, time_ns=item.end_time_ns)
        if item.is_ir:
            self._model.on_ir_scan(item)
        else:
            self._model.on_dr_scan(item)
            expected = self._predict_dr_scan(item) or expected
        self.expected_ap.write(expected)

    def write_event(self, item: OcahJtagEvent) -> None:
        self._model.sync_power_on_reset(self.tb_if.sample("por_assert_count"))
        self._model.on_event(item)

    def _predict_dr_scan(self, item: OcahJtagScanItem) -> DtpExpectedItem | None:
        model = self._model
        width = item.bit_count
        if (
            not model.ir_known()
            or not model.ptap_select_clear()
            or width == 0
            or width > MAX_SCAN_BITS
        ):
            return None
        ir = model.ir()
        if ir in _ONE_BIT_BYPASS:
            value = OcahJtagTapRefModel.predict_bypass_tdo(item.tdi_value, width)
        elif ir == int(DtpJtagInstr.INV_BYPASS):
            inverted = ~item.tdi_value & ((1 << (width - 1)) - 1)
            value = 0x1 | (inverted << 1)
        elif ir == int(DtpJtagInstr.ZERO_LENGTH_BYPASS):
            value = item.tdi_value
        else:
            return None
        mask = (1 << width) - 1
        return DtpExpectedItem(
            expected=value & mask,
            mask=mask,
            context=f"ir=0x{ir:02x} bits={width}",
            time_ns=item.end_time_ns,
        )
