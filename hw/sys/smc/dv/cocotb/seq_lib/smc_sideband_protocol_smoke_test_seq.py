# SPDX-License-Identifier: Apache-2.0
"""Sideband representative CSR precheck."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Authoritative AVSBus window (PeakRDL). Status regs return OKAY; AVS_READBACK
# is still an error-slave on this SEP_IN path (SLVERR, data=0).
SIDEBAND_OKAY_READS = [
    ("AVS_DEBUG_READBACK", smc_addr(
        "SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_DEBUG_READBACK_BASE_ADDR")),
    ("AVS_NORMAL_STATUS", smc_addr(
        "SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_NORMAL_STATUS_BASE_ADDR")),
    ("AVS_SLAVE_STATUS", smc_addr(
        "SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_SLAVE_STATUS_BASE_ADDR")),
    ("AVS_FIFOS_STATUS", smc_addr(
        "SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_FIFOS_STATUS_BASE_ADDR")),
]
SIDEBAND_ERR_READS = [
    ("AVS_READBACK", smc_addr(
        "SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_READBACK_BASE_ADDR")),
]


class smc_sideband_protocol_smoke_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for n, addr in SIDEBAND_OKAY_READS:
            await self.csr_read(n, addr)
        for n, addr in SIDEBAND_ERR_READS:
            await self.csr_read_expect_error(n, addr)
        total = len(SIDEBAND_OKAY_READS) + len(SIDEBAND_ERR_READS)
        assert self.accesses == total, "sideband CSR precheck mismatch"
