# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""idcode reference model: every DR scan under IDCODE shifts out the device identification.

Every DR scan while IDCODE is the active instruction (after Test-Logic-Reset
by TRST or TMS, or an explicit load) shifts out the DTP device identification
(``DTP_DEFAULT_IDCODE``) in its low 32 bits. Consumes the reconstructed scan
stream (``write``) and the per-TCK event stream (``event_export``) through a
``DtpJtagIrModel``, re-baselines on power-on reset through the TB
interface, and publishes one ``DtpExpectedItem`` per scan item so the
scoreboard pairs the two streams in lockstep: IR scans, scans under another
instruction, scans under an unknown instruction, and scans while the PTAP
3DCR select is set, when the STAP chain follows the identification register,
carry no contract. No comparison, no reporting. The SV-UVM twin is
``dtp_idcode_ref_model``.
"""

from __future__ import annotations

from ocah_jtag_vip import OcahJtagEvent, OcahJtagScanItem
from ocah_lib import OcahRefModel
from pyuvm import ConfigDB

from .dtp_expected_item import DtpAnalysisImp, DtpExpectedItem
from .dtp_jtag_ir_model import DtpJtagIrModel
from .dtp_tap_device import DTP_DEFAULT_IDCODE
from .dtp_types import DtpJtagInstr

__all__ = ["DtpIdcodeRefModel"]

IDCODE_WIDTH = 32


class DtpIdcodeRefModel(OcahRefModel):
    """Reconstructed scans in, one expectation (or no contract) per scan out."""

    def build_phase(self) -> None:
        super().build_phase()
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.event_export = DtpAnalysisImp("event_export", self, self.write_event)
        # Device identification the model predicts (IEEE 1149.1 layout).
        self.expected_idcode = DTP_DEFAULT_IDCODE
        self._model = DtpJtagIrModel()

    def write(self, item: OcahJtagScanItem) -> None:
        """Track IR scans; predict the IDCODE bits of a DR scan under a known IDCODE instruction."""
        self._model.sync_power_on_reset(self.tb_if.sample("por_assert_count"))
        expected = DtpExpectedItem(compare=False, time_ns=item.end_time_ns)
        if item.is_ir:
            self._model.on_ir_scan(item)
        else:
            self._model.on_dr_scan(item)
            model = self._model
            if (
                model.ir_known()
                and item.bit_count != 0
                and model.ir() == int(DtpJtagInstr.IDCODE)
                and model.ptap_select_clear()
            ):
                mask = (1 << min(item.bit_count, IDCODE_WIDTH)) - 1
                expected = DtpExpectedItem(
                    expected=self.expected_idcode & mask,
                    mask=mask,
                    context=f"ir=0x{model.ir():02x} bits={item.bit_count}",
                    time_ns=item.end_time_ns,
                )
        self.expected_ap.write(expected)

    def write_event(self, item: OcahJtagEvent) -> None:
        self._model.sync_power_on_reset(self.tb_if.sample("por_assert_count"))
        self._model.on_event(item)
