# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Expected capture of a JTAG2AXI DTMCS or DMI scan.

Published by ``DtpJtag2AxiStatusRefModel`` for the scoreboard to pair with
the reconstructed scan: the captured value on the bits of ``mask``.
``compare=False`` pairs and drops without a record (a scan that is not a
bridge capture, or one taken through the PTAP 3DCR select). The SV-UVM twin
is ``dtp_jtag2axi_status_item``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DtpJtag2AxiStatusItem"]


@dataclass(frozen=True)
class DtpJtag2AxiStatusItem:
    """Expected value of one bridge capture on the bits of ``mask``, or no contract."""

    compare: bool = True
    target: str = ""
    kind: str = ""
    expected: int = 0
    mask: int = 0
    context: str = ""
    time_ns: float | None = None

    def describe(self) -> str:
        if not self.compare:
            return f"no-contract {self.target} {self.kind}"
        return f"{self.target} {self.kind} 0x{self.expected & self.mask:x}/0x{self.mask:x}"
