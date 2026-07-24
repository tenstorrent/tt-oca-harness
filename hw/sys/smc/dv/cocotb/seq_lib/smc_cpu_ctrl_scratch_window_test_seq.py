# SPDX-License-Identifier: Apache-2.0
"""CPU-control scratch-window write/readback depth test."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# SMC_CPU_CTRL_SCRATCH_n at 0xC0039080 + n*8 (CPU_CTRL block moved from the old
# 0xC0010100 base to 0xC0039080; stride is 8 bytes).
SCRATCH_WRITES = [
    ("CPU_CTRL_SCRATCH_0", 0xC003_9080, 0xC0A0_0000),
    ("CPU_CTRL_SCRATCH_7", 0xC003_90B8, 0xC0A0_0007),
    ("CPU_CTRL_SCRATCH_15", 0xC003_90F8, 0xC0A0_0015),
]


class smc_cpu_ctrl_scratch_window_test_seq(SmcCsrSeq):
    """Exercise first/middle/last CPU scratch registers and restore them."""

    def __init__(self, name: str = "smc_cpu_ctrl_scratch_window_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        saved = []
        for name, addr, pattern in SCRATCH_WRITES:
            old_value = await self.csr_read(f"{name}_SAVE", addr)
            saved.append((name, addr, old_value))
            await self.csr_write_readback(name, addr, pattern)

        for name, addr, value in reversed(saved):
            await self.csr_restore(name, addr, value)

        assert self.accesses == len(SCRATCH_WRITES) * 5, "CPU scratch depth mismatch"
