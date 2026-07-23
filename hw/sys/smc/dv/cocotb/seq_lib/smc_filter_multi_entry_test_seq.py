# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap round 2: filter multi-entry sweep.

RTL exposes 16 inbound + 16 outbound filter entries. Round-1
`smc_input_fabric_axi_wr_rd_test` only touches entry 0 of each.
This test sweeps FILTER_CONFIG (offset 0x00) of every entry to prove
each filter slot's decode is alive.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

_INBOUND_FILTER_BASE  = 0xC001_5000
_OUTBOUND_FILTER_BASE = 0xC001_6000
_FILTER_STRIDE = 0x20
_FILTER_COUNT = 16


# Every entry's FILTER_CONFIG resets to 0x0000_3000 (RTL constant, identical on
# Verilator and VCS). Asserting it makes each read verify per-slot decode AND
# reset content (functional), not merely an OKAY response.
_FILTER_CONFIG_RESET = 0x0000_3000


class smc_filter_multi_entry_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for i in range(_FILTER_COUNT):
            addr = _INBOUND_FILTER_BASE + i * _FILTER_STRIDE
            await self.csr_read(f"INBOUND_FILTER_{i}_CONFIG", addr,
                                expected=_FILTER_CONFIG_RESET)
        for i in range(_FILTER_COUNT):
            addr = _OUTBOUND_FILTER_BASE + i * _FILTER_STRIDE
            await self.csr_read(f"OUTBOUND_FILTER_{i}_CONFIG", addr,
                                expected=_FILTER_CONFIG_RESET)
        assert self.accesses == 2 * _FILTER_COUNT, "filter multi-entry sweep count mismatch"
