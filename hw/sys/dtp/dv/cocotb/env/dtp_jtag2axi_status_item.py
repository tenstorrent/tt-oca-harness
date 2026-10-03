# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Expected capture of a JTAG2AXI SINGLE_OP or SERIES_CTRL scan.

Published by ``DtpJtag2AxiStatusRefModel`` for the scoreboard to pair with
the reconstructed scan: the status field the bridge must present and, for a
completed read, the read data. ``compare=False`` pairs and drops without a
record (a scan that is not a status capture, one inside the CDC settle
window after a completion, or one ``DtpJtag2AxiModel`` exempts). The SV-UVM
twin is ``dtp_jtag2axi_status_item``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dtp_types import DtpJtag2AxiStatus

__all__ = ["DtpJtag2AxiStatusItem"]


@dataclass(frozen=True)
class DtpJtag2AxiStatusItem:
    """Expected status (and read data) of one bridge capture, or no contract."""

    compare: bool = True
    target: str = ""
    kind: str = ""
    status: DtpJtag2AxiStatus = DtpJtag2AxiStatus.SUCCESS
    # Read data is part of the contract only after a completed OKAY read.
    compare_rdata: bool = False
    rdata: int = 0
    rdata_mask: int = 0
    context: str = ""
    time_ns: float | None = None

    def describe(self) -> str:
        if not self.compare:
            return f"no-contract {self.target} {self.kind}"
        rdata = f" rdata=0x{self.rdata & self.rdata_mask:x}" if self.compare_rdata else ""
        return f"{self.target} {self.kind} status={self.status.name}{rdata}"
