# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""xtrig_csr reference model: CSR readbacks return the value rebuilt from the observed writes.

Every OKAY read of a cross-trigger CSR with a readback contract (CTM
selects, CTP CONFIG and STRETCH_MULT) returns the value rebuilt from the
writes the passive monitor observed on the XTRIG AXI-Lite port, under the
register's byte strobes and implemented-bit mask, cleared on every system or
power-on reset (the TB interface reset counters). Consumes the XTRIG monitor
stream (``write``) through a ``DtpXtrigCsrModel`` and publishes one
``DtpExpectedItem`` per observed transaction so the scoreboard pairs the two
streams in lockstep. An OKAY read of a hole reads 0 across the full word;
writes, STATUS reads, unmapped accesses, and non-OKAY completions carry no
contract, and a write to a hole leaves the shadow unchanged.
``DTP_XTRIG_CSR_REF_MODEL_NEGATIVE`` flips the lowest implemented bit of
every predicted readback, so the run must fail. No comparison, no reporting.
The SV-UVM twin is ``dtp_xtrig_csr_ref_model``.
"""

from __future__ import annotations

from ocah_axi_vip import RESP_OKAY, OcahAxiItem
from ocah_lib import OcahKnobs, OcahRefModel
from pyuvm import ConfigDB

from .dtp_expected_item import DtpExpectedItem
from .dtp_xtrig_csr_model import DtpXtrigCsrModel
from .dtp_xtrig_types import DtpXtrigCsrKind, xtrig_csr_decode, xtrig_csr_default

__all__ = ["DtpXtrigCsrRefModel"]

NEGATIVE_KNOB = "DTP_XTRIG_CSR_REF_MODEL_NEGATIVE"
_WORD_MASK = 0xFFFF_FFFF


class DtpXtrigCsrRefModel(OcahRefModel):
    """XTRIG AXI-Lite items in, one expectation (or no contract) per item out."""

    def build_phase(self) -> None:
        super().build_phase()
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self._model = DtpXtrigCsrModel()
        self._resets_seen = (0, 0)
        self.negative = OcahKnobs.is_set(NEGATIVE_KNOB)
        if self.negative:
            self.logger.warning(
                "NEGATIVE VALIDATION: every predicted CSR readback is corrupted (%s)",
                NEGATIVE_KNOB,
            )

    def write(self, item: OcahAxiItem) -> None:
        """Shadow an OKAY write; predict an OKAY read from the shadow, a hole read as zero."""
        self._sync_reset()
        kind, mask = xtrig_csr_decode(item.address)
        expected = DtpExpectedItem(compare=False, time_ns=item.end_time_ns)
        context = f"{kind.name} addr=0x{item.address:03x}"
        ok = item.resp == RESP_OKAY and bool(item.data_words)
        no_contract = kind in (DtpXtrigCsrKind.UNMAPPED, DtpXtrigCsrKind.CTP_STATUS)
        if no_contract or not ok:
            self.expected_ap.write(expected)
            return
        if kind is DtpXtrigCsrKind.HOLE:
            if not item.is_write:
                expected = DtpExpectedItem(
                    expected=self._corrupt(0, _WORD_MASK),
                    mask=_WORD_MASK,
                    context=context,
                    time_ns=item.end_time_ns,
                )
        elif item.is_write:
            wstrb = item.strobes[0] if item.strobes else 0xF
            self._model.write(
                item.address,
                item.first_data & _WORD_MASK,
                wstrb=wstrb & 0xF,
                mask=mask,
                reset_value=xtrig_csr_default(kind),
            )
        else:
            expected = DtpExpectedItem(
                expected=self._corrupt(
                    self._model.read(item.address, mask=mask, reset_value=xtrig_csr_default(kind)),
                    mask,
                ),
                mask=mask,
                context=context,
                time_ns=item.end_time_ns,
            )
        self.expected_ap.write(expected)

    def _corrupt(self, value: int, mask: int) -> int:
        """``value``, with the lowest bit of ``mask`` flipped under the negative knob."""
        return value ^ (mask & -mask) if self.negative else value

    def _sync_reset(self) -> None:
        """Every system or power-on reset clears the CSR block."""
        seen = (self.tb_if.sample("sys_rst_assert_count"), self.tb_if.sample("por_assert_count"))
        if seen != self._resets_seen:
            self._resets_seen = seen
            self._model.clear()
