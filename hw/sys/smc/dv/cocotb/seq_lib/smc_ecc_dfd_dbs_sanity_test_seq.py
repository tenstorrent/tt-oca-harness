# SPDX-License-Identifier: Apache-2.0
"""ECC/RAS and DFD/DBS diagnostic representative precheck."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Diagnostic reads, identical on Verilator and VCS. Traceability is mixed:
#   * RAS_BANK_INFO / NDMRESET_PROCESS: RDL reset 0x0 -> G3 spec-anchored.
#   * NDMRESET_CLUSTER_COUNT=0x4 is a REGRESSION-LOCK: RDL reset is 0x0; the 4
#     is a tied HW "#clusters" input (hw=w), not a spec reset constant.
#   * DFX DEBUG_CTRL / DEBUG_BUS_MUX: PeakRDL symbols at 0xC000_B808/B810,
#     RDL reset 0x0 (do not use the old false-identity window 0xC001_0208/0210).
DIAGNOSTIC_READS = [
    ("CHIP_CONFIG_RAS_BANK_INFO", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_RAS_BANK_INFO_BASE_ADDR"), 0x0),
    ("NDMRESET_PROCESS", smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR"), 0x0),
    ("NDMRESET_CLUSTER_COUNT", smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR"), 0x4),  # regression-lock (tied HW, RDL=0)
    ("DFX_DEBUG_CTRL", smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR"), 0x0),
    ("DFX_DEBUG_BUS_MUX", smc_addr("SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR"), 0x0),
]


class smc_ecc_dfd_dbs_sanity_test_seq(SmcCsrSeq):
    """Use safe RAS/debug CSRs as the diagnostic representative."""

    def __init__(self, name: str = "smc_ecc_dfd_dbs_sanity_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(DIAGNOSTIC_READS)
        assert self.accesses == len(DIAGNOSTIC_READS), "diagnostic CSR precheck mismatch"
