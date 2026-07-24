# SPDX-License-Identifier: Apache-2.0
"""CPU-control to SEP-facing CSR reachability precheck."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

CPU_CTRL_READS = [
    ("RESET_VECTOR_0", 0xC001_0000, None),
    ("RESET_CTRL", 0xC001_0020, None),
    ("CLOCK_GATE_CONTROL", 0xC001_0018, None),  # offset 0x18 (was 0x30 before HANG_DET_* added)
    ("GLOBAL_BASE", 0xC001_0040, None),
    ("LOCAL_BASE", 0xC001_0048, None),
    ("REGION_SIZE", 0xC001_0050, None),
]
CPU_CTRL_SCRATCH_0 = 0xC001_0100
CPU_PATTERN = 0xC511_0001


class smc_cpu_to_sep_axi_test_seq(SmcCsrSeq):
    """Precheck CPU-control CSR path until a CPU/firmware source is available."""

    def __init__(self, name: str = "smc_cpu_to_sep_axi_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(CPU_CTRL_READS)
        await self.csr_write_readback("CPU_CTRL_SCRATCH_0", CPU_CTRL_SCRATCH_0,
                                      CPU_PATTERN)
        await self.csr_restore("CPU_CTRL_SCRATCH_0", CPU_CTRL_SCRATCH_0)
        assert self.accesses == len(CPU_CTRL_READS) + 4, "CPU CSR precheck mismatch"
