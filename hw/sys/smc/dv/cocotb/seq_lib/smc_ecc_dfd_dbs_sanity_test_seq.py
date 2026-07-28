# SPDX-License-Identifier: Apache-2.0
"""ECC/RAS and DFD/DBS diagnostic representative precheck."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# Diagnostic reads, identical on Verilator and VCS. Traceability is mixed:
#   * RAS_BANK_INFO (chip_config.rdl) and NDMRESET_PROCESS (ndm_reset.rdl)
#     reset to 0x0 per RDL -> G3 spec-anchored.
#   * NDMRESET_CLUSTER_COUNT=0x4 is a REGRESSION-LOCK: RDL reset is 0x0; the 4
#     is a tied HW "#clusters" input (hw=w), not a spec reset constant.
#   * CPU_DEBUG_CTRL/BUS_MUX @0xC001_0208/0210: SUSPECT -- no RDL register
#     exists at these addresses; the same-named regs in dfx_ctrl_status.rdl are
#     at 0xC000_F808/F810 and reset 0x0. The observed 0xC000_0000/0x0100_0000
#     are the cluster black-box "magic" constants. Kept as reachability
#     regression-locks pending OWNER REVIEW of the intended addresses.
#     [audit: F1 C2, see smcoss_audit.md -- do not re-baseline silently]
DIAGNOSTIC_READS = [
    ("CHIP_CONFIG_RAS_BANK_INFO", 0xC000_2910, 0x0),
    ("NDMRESET_PROCESS", 0xC000_2A04, 0x0),
    ("NDMRESET_CLUSTER_COUNT", 0xC000_2A08, 0x4),          # regression-lock (tied HW, RDL=0)
    ("CPU_DEBUG_CTRL", 0xC001_0208, 0xC000_0000),          # SUSPECT addr (F1 C2)
    ("CPU_DEBUG_BUS_MUX", 0xC001_0210, 0x0100_0000),       # SUSPECT addr (F1 C2)
]


class smc_ecc_dfd_dbs_sanity_test_seq(SmcCsrSeq):
    """Use safe RAS/debug CSRs as the diagnostic representative."""

    def __init__(self, name: str = "smc_ecc_dfd_dbs_sanity_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(DIAGNOSTIC_READS)
        assert self.accesses == len(DIAGNOSTIC_READS), "diagnostic CSR precheck mismatch"
