# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus status CSR depth proxy test."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Authoritative AVSBus window (PeakRDL). Status regs return OKAY; AVS_READBACK
# is an error-slave on this SEP_IN path (SLVERR, data=0).
AVSBUS_STATUS_OKAY_READS = [
    ("AVS_DEBUG_READBACK", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_DEBUG_READBACK_BASE_ADDR")),
    ("AVS_NORMAL_STATUS", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_NORMAL_STATUS_BASE_ADDR")),
    ("AVS_SLAVE_STATUS", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_SLAVE_STATUS_BASE_ADDR")),
    ("AVS_FIFOS_STATUS", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_FIFOS_STATUS_BASE_ADDR")),
]
AVSBUS_STATUS_ERR_READS = [
    ("AVS_READBACK", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_READBACK_BASE_ADDR")),
]


class smc_avsbus_status_depth_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for n, addr in AVSBUS_STATUS_OKAY_READS:
            await self.csr_read(n, addr)
        for n, addr in AVSBUS_STATUS_ERR_READS:
            await self.csr_read_expect_error(n, addr)
        total = len(AVSBUS_STATUS_OKAY_READS) + len(AVSBUS_STATUS_ERR_READS)
        assert self.accesses == total, "AVSBus status depth mismatch"
