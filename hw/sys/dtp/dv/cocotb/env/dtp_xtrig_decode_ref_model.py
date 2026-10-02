# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""xtrig_decode reference model: every CSR access completes with its word's mapped response.

Every access to the cross-trigger CSR port completes with the response the
network memory map gives its word (``xtrig_csr_decode``): DECERR for an
unmapped word, OKAY for a register or a hole. Consumes the XTRIG AXI-Lite
monitor stream (``write``) and publishes one ``DtpExpectedItem`` per
observed transaction so the scoreboard pairs the two streams in lockstep.
Stateless, no comparison, no reporting. The SV-UVM twin is
``dtp_xtrig_decode_ref_model``.
"""

from __future__ import annotations

from ocah_axi_vip import OcahAxiItem
from ocah_lib import OcahRefModel

from .dtp_expected_item import DtpExpectedItem
from .dtp_xtrig_types import DtpXtrigCsrKind, xtrig_csr_decode

__all__ = ["DtpXtrigDecodeRefModel"]

AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3


class DtpXtrigDecodeRefModel(OcahRefModel):
    """XTRIG AXI-Lite items in, one expected response code per item out."""

    def write(self, item: OcahAxiItem) -> None:
        kind, _ = xtrig_csr_decode(item.address)
        self.expected_ap.write(
            DtpExpectedItem(
                expected=AXI_RESP_DECERR if kind is DtpXtrigCsrKind.UNMAPPED else AXI_RESP_OKAY,
                mask=0x3,
                context=f"{item.direction} {kind.name} addr=0x{item.address:03x}",
                time_ns=item.end_time_ns,
            )
        )
