# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Small DTP-local scan-chain model for basic JTAG scenarios.

The OSS DTP top loops the BSR scan input back from the DUT scan output. This
model captures the expected public behavior at the scenario level.

The zero-length external chain returns TDI through the DUT's IEEE 1149.1
falling-edge TDO retimer (jtag_ptap `tdo_retimed`), so the observed DR stream
is the shifted-in pattern delayed by one TCK — the same one-bit-delay
convention as ``DtpBypassRefModel``. Bit 0 of the observation is the retimer
content at scan entry, which is 0 because the driver holds TDI low while
navigating the TAP state machine.
"""

from __future__ import annotations


class DtpScanModel:
    """Reference helpers for compact DTP-local scan chains."""

    def __init__(self, width: int = 8) -> None:
        self.width = width
        self.last_pattern = 0

    @property
    def mask(self) -> int:
        return (1 << self.width) - 1

    def preload(self, pattern: int) -> int:
        """Record and return the model-visible preloaded pattern."""
        self.last_pattern = pattern & self.mask
        return self.last_pattern

    def loopback_expected(self, pattern: int) -> int:
        """Return expected loopback data: the pattern retimed by one TCK.

        TDI reaches TDO through the falling-edge retimer, so observed bit i is
        pattern bit i-1 and observed bit 0 is the retimer's scan-entry content
        (0, flushed by TDI=0 during TAP navigation).
        """
        self.last_pattern = pattern & self.mask
        return (self.last_pattern << 1) & self.mask

    def assert_loopback(self, observed: int, pattern: int, context: str) -> None:
        """Check observed scan data against the expected loopback pattern."""
        expected = self.loopback_expected(pattern)
        got = observed & self.mask
        assert got == expected, (
            f"{context} loopback mismatch: expected 0x{expected:0{(self.width + 3) // 4}x}, "
            f"got 0x{got:0{(self.width + 3) // 4}x}"
        )
