# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL MUTEX[0] take/release. Semaphore has no PeakRDL export."""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

MUTEX0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR", 0)


class smc_mutex_semaphore_test_seq(SmcCsrSeq):
    """MUTEX[0] available->taken->released via SEP_IN AXI."""

    def __init__(self, name: str = "smc_mutex_semaphore_test_seq") -> None:
        super().__init__(name)
        self.take_ok = False
        self.held_ok = False
        self.release_ok = False

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        got = await self.csr_read("MUTEX0_TAKE", MUTEX0, expected=1)
        self.take_ok = True
        cocotb.log.info("CHK-MUTEX-TAKE: MUTEX[0] read 0x%x (available, now taken)", got)

        got = await self.csr_read("MUTEX0_HELD", MUTEX0, expected=0)
        self.held_ok = True
        cocotb.log.info("CHK-MUTEX-HELD: MUTEX[0] read 0x%x while taken", got)

        await self.csr_write("MUTEX0_RELEASE", MUTEX0, 1)
        got = await self.csr_read("MUTEX0_FREE", MUTEX0, expected=1)
        self.release_ok = True
        cocotb.log.info("CHK-MUTEX-REL: write released MUTEX[0], read 0x%x", got)
        cocotb.log.info(
            "CHK-MUTEX-BASIC: take=%s held=%s rel=%s",
            self.take_ok,
            self.held_ok,
            self.release_ok,
        )
