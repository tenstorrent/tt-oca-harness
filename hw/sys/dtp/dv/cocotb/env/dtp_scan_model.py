# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Small DTP-local scan-chain model for basic JTAG scenarios.

``tb_top`` loops the BSR scan input back from the DUT scan output; this model
predicts that loopback per scenario.

The zero-length external chain returns TDI through the DUT's IEEE 1149.1
falling-edge TDO retimer (jtag_ptap `tdo_retimed`), so the observed DR stream
is the shifted-in pattern delayed by one TCK — the same one-bit-delay
convention as ``DtpJtagBypassModel``. Bit 0 of the observation is the retimer
content at scan entry, which is 0 because the driver holds TDI low while
navigating the TAP state machine.
"""

from __future__ import annotations

__all__ = ["DtpScanModel"]


class DtpScanModel:
    """Reference helpers for compact DTP-local scan chains."""

    def __init__(self, width: int = 8) -> None:
        self.width = width

    @property
    def mask(self) -> int:
        return (1 << self.width) - 1

    def loopback_expected(self, pattern: int) -> int:
        """Return expected loopback data: the pattern retimed by one TCK.

        TDI reaches TDO through the falling-edge retimer, so observed bit i is
        pattern bit i-1 and observed bit 0 is the retimer's scan-entry content
        (0, flushed by TDI=0 during TAP navigation).
        """
        return (pattern << 1) & self.mask
