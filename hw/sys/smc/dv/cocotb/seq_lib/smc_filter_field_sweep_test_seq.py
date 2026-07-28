# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap round 3: per-filter field sweep.

Round 1/2 only touched FILTER_CONFIG. Each filter entry exposes 3
CSR fields: FILTER_CONFIG (offset 0x00), START_ADDR (0x08), END_ADDR
(0x10). This test reads all 3 fields of entries 0-3 in both
directions (inbound + outbound) = 24 reads.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

_INBOUND_FILTER_BASE  = 0xC001_5000
_OUTBOUND_FILTER_BASE = 0xC001_6000
_FILTER_STRIDE = 0x20

# Per-field reset values (RTL constants, identical on Verilator and VCS):
#   FILTER_CONFIG resets to 0x0000_3000, START_ADDR to 0x0, END_ADDR to 0x7.
# Asserting them makes every read verify field decode AND reset content
# (functional), not merely an OKAY response.
_FIELD_OFFSETS = [
    ("FILTER_CONFIG", 0x00, 0x0000_3000),
    ("START_ADDR",    0x08, 0x0),
    ("END_ADDR",      0x10, 0x7),
]

_ENTRY_COUNT = 4


class smc_filter_field_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for i in range(_ENTRY_COUNT):
            for name, off, exp in _FIELD_OFFSETS:
                addr = _INBOUND_FILTER_BASE + i * _FILTER_STRIDE + off
                await self.csr_read(f"IN_FILTER_{i}_{name}", addr, expected=exp)
        for i in range(_ENTRY_COUNT):
            for name, off, exp in _FIELD_OFFSETS:
                addr = _OUTBOUND_FILTER_BASE + i * _FILTER_STRIDE + off
                await self.csr_read(f"OUT_FILTER_{i}_{name}", addr, expected=exp)
        expected = 2 * _ENTRY_COUNT * len(_FIELD_OFFSETS)
        assert self.accesses == expected, "filter field sweep count mismatch"
