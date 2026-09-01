# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Locked-shadow IRQ on tb_efuse_locked_access_irq. Default hex read-locks CHIPLET_ID."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import smc_addr, smc_efuse_map_u32
from .smc_csr_seq_utils import SmcCsrSeq

LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
CHIPLET_ID = smc_addr("SMC_TOP_SMC_EFUSE_MAP_CHIPLET_ID_BASE_ADDR")
WRITE_LOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__CHIPLET_ID_WRITE_LOCK_bm")
READ_LOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__CHIPLET_ID_READ_LOCK_bm")
READ_LOCKED_VALUE = 0xBADCAB1E
_UNLOCKED_PAT = 0xCAFE0001
_DRAIN = 8


class smc_efuse_locked_access_interrupt_test_seq(SmcCsrSeq):
    """CHIPLET_ID lock IRQ via lifted peripheral_interrupts[28]."""

    def __init__(self, name: str = "smc_efuse_locked_access_interrupt_test_seq") -> None:
        super().__init__(name)
        self.unlock_ok = False
        self.wrlock_ok = False
        self.rdlock_ok = False

    def _irq(self):
        pin = getattr(cocotb.top, "tb_efuse_locked_access_irq", None)
        if pin is None:
            raise AssertionError("tb_efuse_locked_access_irq missing on OSS tb_top")
        return pin

    async def _count_edges_during(self, coro) -> int:
        edges = 0

        async def _watch() -> None:
            nonlocal edges
            pin = self._irq()
            while True:
                await RisingEdge(pin)
                edges += 1

        task = cocotb.start_soon(_watch())
        try:
            await coro
            await ClockCycles(cocotb.top.clk_periph_i, _DRAIN)
        finally:
            task.kill()
        return edges

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        locks = await self.csr_read("LOCKS_PRE", LOCKS)
        assert (locks & WRITE_LOCK) == 0, f"CHIPLET_ID write-lock already set: LOCKS=0x{locks:08x}"
        assert (locks & READ_LOCK) != 0, (
            f"default hex must read-lock CHIPLET_ID: LOCKS=0x{locks:08x}"
        )
        cocotb.log.info("CHK-EFUSE-LOCK-PRE: LOCKS=0x%x wr=0 rd=1", locks)

        async def _unlocked_write() -> None:
            await self.csr_write("CHIPLET_ID_UNLOCK_WR", CHIPLET_ID, _UNLOCKED_PAT)

        unlock_edges = await self._count_edges_during(_unlocked_write())
        assert unlock_edges == 0, f"unlocked CHIPLET_ID write pulsed IRQ {unlock_edges} time(s)"
        self.unlock_ok = True
        cocotb.log.info("CHK-EFUSE-LOCK-IRQ-UNLOCK: unlocked write edges=%d", unlock_edges)

        await self.csr_write("LOCKS_WOSSET_WR", LOCKS, locks | WRITE_LOCK)
        locks2 = await self.csr_read("LOCKS_WR", LOCKS)
        assert (locks2 & WRITE_LOCK) != 0, (
            f"CHIPLET_ID write-lock did not stick: LOCKS=0x{locks2:08x}"
        )

        async def _locked_write() -> None:
            await self.csr_write("CHIPLET_ID_LOCK_WR", CHIPLET_ID, _UNLOCKED_PAT ^ 0xA5A55A5A)

        wr_edges = await self._count_edges_during(_locked_write())
        assert wr_edges >= 1, f"write-locked CHIPLET_ID write produced {wr_edges} IRQ edges"
        self.wrlock_ok = True
        cocotb.log.info("CHK-EFUSE-LOCK-IRQ-WR: write-locked write edges=%d", wr_edges)

        async def _locked_read() -> None:
            got = await self.csr_read("CHIPLET_ID_LOCK_RD", CHIPLET_ID, expected=READ_LOCKED_VALUE)
            assert got == READ_LOCKED_VALUE

        rd_edges = await self._count_edges_during(_locked_read())
        assert rd_edges >= 1, f"read-locked CHIPLET_ID read produced {rd_edges} IRQ edges"
        self.rdlock_ok = True
        cocotb.log.info(
            "CHK-EFUSE-LOCK-IRQ-RD: read-locked read edges=%d data=0x%x",
            rd_edges,
            READ_LOCKED_VALUE,
        )
        cocotb.log.info(
            "CHK-EFUSE-LOCK-IRQ-BASIC: unlock=%s wr=%s rd=%s",
            self.unlock_ok,
            self.wrlock_ok,
            self.rdlock_ok,
        )
