# SPDX-License-Identifier: Apache-2.0
"""AVSBus status CSR depth proxy test."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# AVSBus status window: most registers decode and return OKAY with real data
# here (AVS_DEBUG_READBACK=0xDEADBEEF, NORMAL/FIFOS carry status); AVS_READBACK
# is an error-slave window (SLVERR, data=0) on this SEP_IN path until a sideband
# responder exists. Each read is gated deterministically on its expected
# response, so a broken decode (OKAY->error or error->OKAY) fails the test.
AVSBUS_STATUS_OKAY_READS = [
    ("AVS_DEBUG_READBACK", 0xC000_8008),
    ("AVS_NORMAL_STATUS", 0xC000_8020),
    ("AVS_SLAVE_STATUS", 0xC000_8024),
    ("AVS_FIFOS_STATUS", 0xC000_8028),
]
AVSBUS_STATUS_ERR_READS = [
    ("AVS_READBACK", 0xC000_8004),
]


class smc_avsbus_status_depth_test_seq(SmcCsrSeq):
    """Exercise status-side AVSBus decode until sideband BFM support exists."""

    def __init__(self, name: str = "smc_avsbus_status_depth_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        for name, addr in AVSBUS_STATUS_OKAY_READS:
            await self.csr_read(name, addr)
        for name, addr in AVSBUS_STATUS_ERR_READS:
            await self.csr_read_expect_error(name, addr)
        total = len(AVSBUS_STATUS_OKAY_READS) + len(AVSBUS_STATUS_ERR_READS)
        assert self.accesses == total, "AVSBus status depth mismatch"
