# SPDX-License-Identifier: Apache-2.0
"""Sideband representative CSR precheck."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# Sideband/AVSBus status window: AVS_READBACK is an error-slave window (SLVERR,
# data=0) on this SEP_IN path until a sideband responder exists; the rest decode
# and return OKAY with real data. Gate each read deterministically on its
# expected response so a decode regression (OKAY<->error) fails the test.
SIDEBAND_OKAY_READS = [
    ("AVS_DEBUG_READBACK", 0xC000_8008),
    ("AVS_NORMAL_STATUS", 0xC000_8020),
    ("AVS_SLAVE_STATUS", 0xC000_8024),
    ("AVS_FIFOS_STATUS", 0xC000_8028),
]
SIDEBAND_ERR_READS = [
    ("AVS_READBACK", 0xC000_8004),
]


class smc_sideband_protocol_smoke_test_seq(SmcCsrSeq):
    """Exercise one OSS-safe sideband CSR window before adding a BFM."""

    def __init__(self, name: str = "smc_sideband_protocol_smoke_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        for name, addr in SIDEBAND_OKAY_READS:
            await self.csr_read(name, addr)
        for name, addr in SIDEBAND_ERR_READS:
            await self.csr_read_expect_error(name, addr)
        total = len(SIDEBAND_OKAY_READS) + len(SIDEBAND_ERR_READS)
        assert self.accesses == total, "sideband CSR precheck mismatch"
