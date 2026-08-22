# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_BASE_CONFIG (CPU address-map + hang-detector) reset-value precheck.

The block at smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR") is SMC_BASE_CONFIG
(hw/smc/smc_misc/data/registers/rdl/smc_base_config.rdl), reached over real
SEP_IN AXI. Each expected below is the register's RDL reset constant (cited
per line), so every read verifies decode AND spec-defined reset content (G3),
not merely an OKAY response.
"""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Register names and reset values traced to smc_base_config.rdl. (An earlier
# revision mislabelled these as RESET_VECTOR_*/GLOBAL_BASE/LOCAL_BASE/REGION_SIZE
# -- the audit corrected them to the real RDL register identities.)
CPU_MAP_READS = [
    ("GLOBAL_BASE",                          smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR"), 0x4000_0000),  # rdl base=0x4000_0000
    ("LOCAL_BASE",                           smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR"), smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR")),  # rdl base=smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR")
    ("HANG_DET_DATA_ACCEL_CTRL",             smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR") + 0x40, 0x0),          # enable/irq_en/irq_test=0
    ("HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD", smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR") + 0x48, 0x0000_1000), # rdl value[19:0]=0x1000
    # 0xC001_0050 has no register in smc_base_config.rdl (last reg ends at 0x48);
    # it reads back 0x0 as reserved/open-bus space within the block window --
    # kept as a decode-reachability read, not a spec register value.
    ("SMC_BASE_CONFIG_RSVD_0x50",            0xC001_0050, 0x0),
]


class smc_cpu_ctrl_map_depth_test_seq(SmcCsrSeq):
    """Cover SMC_BASE_CONFIG map/hang-detector CSRs until firmware traffic is public."""

    def __init__(self, name: str = "smc_cpu_ctrl_map_depth_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(CPU_MAP_READS)
        assert self.accesses == len(CPU_MAP_READS), "CPU map depth mismatch"
