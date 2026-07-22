# SPDX-License-Identifier: Apache-2.0
"""Small DTP-local scan-chain model for basic JTAG scenarios.

The OSS DTP top loops BSR/iJTAG scan inputs back from DUT scan outputs. This
model captures the expected public behavior at the scenario level without
introducing a reusable protocol VIP.
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
        """Return expected loopback data for the compact OSS scan model."""
        self.last_pattern = pattern & self.mask
        return self.last_pattern

    def assert_loopback(self, observed: int, pattern: int, context: str) -> None:
        """Check observed scan data against the expected loopback pattern."""
        expected = self.loopback_expected(pattern)
        got = observed & self.mask
        assert got == expected, (
            f"{context} loopback mismatch: expected 0x{expected:0{(self.width + 3) // 4}x}, "
            f"got 0x{got:0{(self.width + 3) // 4}x}"
        )
