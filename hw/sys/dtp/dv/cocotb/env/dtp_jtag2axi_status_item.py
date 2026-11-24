# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Expected capture of a JTAG2AXI DTMCS or DMI scan.

Published by ``DtpJtag2AxiStatusRefModel`` for the scoreboard to pair with
the reconstructed scan: the captured value on the bits of ``mask``, or
``alternate`` on those bits when it is set. ``compare=False`` pairs and drops
without a record (a scan that is not a
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
    alternate: int | None = None
    context: str = ""
    time_ns: float | None = None

    def accepts(self, captured: int) -> bool:
        """Whether ``captured`` equals ``expected``, or ``alternate`` when set, on ``mask``."""
        values = [self.expected] if self.alternate is None else [self.expected, self.alternate]
        return any(captured & self.mask == value & self.mask for value in values)

    def describe(self) -> str:
        if not self.compare:
            return f"no-contract {self.target} {self.kind}"
        text = f"{self.target} {self.kind} 0x{self.expected & self.mask:x}"
        if self.alternate is not None:
            text += f" or 0x{self.alternate & self.mask:x}"
        return f"{text}/0x{self.mask:x}"
