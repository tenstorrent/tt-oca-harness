# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""xtrig_decode reference model: every CSR access completes with its word's mapped response.

Every access to the cross-trigger CSR port completes with the response the
network memory map gives its word (``xtrig_csr_decode``): DECERR for an
unmapped word, OKAY for a register or a hole. Consumes the XTRIG AXI-Lite
monitor stream (``write``) and publishes one ``DtpExpectedItem`` per
observed transaction so the scoreboard pairs the two streams in lockstep.
``DTP_XTRIG_DECODE_REF_MODEL_NEGATIVE`` flips bit 0 of every predicted
response, so the run must fail. No comparison, no reporting. The SV-UVM twin
is ``dtp_xtrig_decode_ref_model``.
"""

from __future__ import annotations

from ocah_axi_vip import RESP_DECERR, RESP_OKAY, OcahAxiItem
from ocah_lib import OcahKnobs, OcahRefModel

from .dtp_expected_item import DtpExpectedItem
from .dtp_xtrig_types import DtpXtrigCsrKind, xtrig_csr_decode

__all__ = ["DtpXtrigDecodeRefModel"]

NEGATIVE_KNOB = "DTP_XTRIG_DECODE_REF_MODEL_NEGATIVE"


class DtpXtrigDecodeRefModel(OcahRefModel):
    """XTRIG AXI-Lite items in, one expected response code per item out."""

    def build_phase(self) -> None:
        super().build_phase()
        self.negative = OcahKnobs.is_set(NEGATIVE_KNOB)
        if self.negative:
            self.logger.warning(
                "NEGATIVE VALIDATION: every predicted response code is corrupted (%s)",
                NEGATIVE_KNOB,
            )

    def write(self, item: OcahAxiItem) -> None:
        """Predict DECERR for an unmapped word and OKAY for every other access."""
        kind, _ = xtrig_csr_decode(item.address)
        resp = RESP_DECERR if kind is DtpXtrigCsrKind.UNMAPPED else RESP_OKAY
        self.expected_ap.write(
            DtpExpectedItem(
                expected=resp ^ int(self.negative),
                mask=0x3,
                context=f"{item.direction} {kind.name} addr=0x{item.address:03x}",
                time_ns=item.end_time_ns,
            )
        )
