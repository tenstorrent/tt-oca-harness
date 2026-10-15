# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cluster WDT magic-key unlock protocol and write-width rules, per core.

Every access is a frontdoor SEP_IN AXI CSR access.

``hw/sys/smc/regs/blocks/wdt/wdt.rdl`` specifies that the magic key
``0x51F15E`` must be written to ``KEY`` before a write to ANY other register in
the block, that the block re-locks after that one write, and that reading
``KEY`` returns 1 while unlocked and 0 once locked again.

With the block locked (its reset state) a write is DROPPED and the read returns
the RESET value, so a lone write/readback of ``CMP`` passes without exercising
the key. The two halves therefore run as a same-run pair that differ in exactly
one variable, the key:

* **negative leg** -- write ``CMP`` with the block LOCKED; ``CMP`` must still
  read its generated reset ``0x1000``;
* **positive leg** -- write ``KEY = 0x51F15E``, confirm ``KEY`` reads 1, write
  the same ``CMP`` probe, and require the exact probe back.

A DUT that ignored the key entirely fails the negative leg; a DUT whose CMP was
dead or unmapped fails the positive leg. Neither leg can carry the test alone.

The re-lock is checked too: after the single unlocked write, ``KEY`` must read 0
again without anything else being written.

* **COUNT_HI leg** -- ``COUNT_HI`` at 0xC reads 0. With the block unlocked, a
  32-bit write to it leaves ``COUNT`` at 0 and makes ``KEY`` read 0.
* **write-width leg** -- with the block unlocked, a 1-byte write of the probe's
  low byte to ``CMP`` answers OKAY, leaves ``CMP`` at reset and ``KEY`` at 1; a
  2-byte write of the probe then reads back exactly and re-locks. The two writes
  differ only in width. A 1-byte write to ``CTRL`` byte 0 sets ``wdogscale``
  alone and re-locks, since ``CTRL`` takes each byte on its own.

``wdt.rdl`` is map-only (no generated register block), so the expectations here
come from the RDL text and the generated reset values.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

WDT_MAGIC_KEY = 0x51F15E
# The one non-zero reset in the block, which is what lets the negative leg tell
# "write rejected" apart from "register reads zero anyway".
WDT_CMP_RESET = 0x1000
# `CMP` is a SINGLE 16-bit field, `wdogcmp0[15:0]`, not a 32-bit register; a
# wider probe reads back truncated to the field. The probe stays inside the
# field: alternating bits, and distinct from the 0x1000 reset, so neither a
# stuck register nor a dropped write can produce it. Its low byte differs from
# the reset's, so a 1-byte write that took effect would show in `CMP`.
WDT_CMP_MASK = 0xFFFF
WDT_CMP_PROBE = 0xA5A5
WDT_KEY_UNLOCKED = 0x1
WDT_KEY_LOCKED = 0x0
# CTRL and COUNT reset to 0, and with `wdogenalways` and `wdogcoreawake` clear
# the counter does not run, so COUNT holds 0 for the whole sequence.
WDT_CTRL_RESET = 0x0
WDT_COUNT_RESET = 0x0
# `wdogscale` is CTRL[3:0]; any non-zero value fits in byte 0.
WDT_CTRL_SCALE_PROBE = 0x5
WDT_COUNT_HI_READ = 0x0
WDT_COUNT_HI_PROBE = 0x7FFF_FFFF

WDT_CORES = (0, 1, 2, 3)
WDT_KEY_ACCESSES_PER_CORE = 12
WDT_COUNT_HI_ACCESSES_PER_CORE = 7
WDT_WIDTH_ACCESSES_PER_CORE = 18


class smc_wdt_key_csr_test_seq(SmcCsrSeq):
    """Per-core WDT key gate, COUNT_HI re-lock and write-width rules."""

    def __init__(self, name: str = "smc_wdt_key_csr_test_seq") -> None:
        super().__init__(name)
        #: cores whose negative AND positive legs both held
        self.cores_proven: list[int] = []
        #: cores whose COUNT_HI leg held
        self.count_hi_proven: list[int] = []
        #: cores whose write-width leg held
        self.width_proven: list[int] = []

    def _reg(self, core: int, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_{reg}_BASE_ADDR")

    async def _unlock(self, label: str, core: int) -> None:
        await self.csr_write(label, self._reg(core, "KEY"), WDT_MAGIC_KEY)

    async def _key_protocol(self, core: int) -> None:
        key = self._reg(core, "KEY")
        cmp_ = self._reg(core, "CMP")

        # Entry state: block locked, CMP at its non-zero generated reset.
        await self.csr_read(f"WDT{core}_KEY_LOCKED", key, expected=WDT_KEY_LOCKED)
        await self.csr_read(f"WDT{core}_CMP_RESET", cmp_, expected=WDT_CMP_RESET)

        # NEGATIVE LEG -- write with the block locked. The write must be
        # dropped, so CMP must still read its reset.
        await self.csr_write(f"WDT{core}_CMP_WR_LOCKED", cmp_, WDT_CMP_PROBE)
        await self.csr_read(f"WDT{core}_CMP_STILL_RESET", cmp_, expected=WDT_CMP_RESET)

        # POSITIVE LEG -- same write, one variable changed: the key.
        await self._unlock(f"WDT{core}_KEY_WR", core)
        await self.csr_read(f"WDT{core}_KEY_UNLOCKED", key, expected=WDT_KEY_UNLOCKED)
        await self.csr_write(f"WDT{core}_CMP_WR_UNLOCKED", cmp_, WDT_CMP_PROBE)
        await self.csr_read(f"WDT{core}_CMP_PROBE_RB", cmp_, expected=WDT_CMP_PROBE)

        # The block must have re-locked on that single write, with nothing
        # else written in between.
        await self.csr_read(f"WDT{core}_KEY_RELOCKED", key, expected=WDT_KEY_LOCKED)

        # Restore needs its own unlock: the block re-locked on the probe write.
        await self._unlock(f"WDT{core}_KEY_WR_RESTORE", core)
        await self.csr_write(f"WDT{core}_CMP_RESTORE", cmp_, WDT_CMP_RESET)
        await self.csr_read(f"WDT{core}_CMP_RESTORE_RB", cmp_, expected=WDT_CMP_RESET)
        self.cores_proven.append(core)

    async def _count_hi(self, core: int) -> None:
        key = self._reg(core, "KEY")
        count = self._reg(core, "COUNT")
        count_hi = self._reg(core, "COUNT_HI")

        await self.csr_read(f"WDT{core}_COUNT_HI_RD", count_hi, expected=WDT_COUNT_HI_READ)
        await self.csr_read(f"WDT{core}_COUNT_BEFORE", count, expected=WDT_COUNT_RESET)
        await self._unlock(f"WDT{core}_KEY_WR_COUNT_HI", core)
        await self.csr_read(f"WDT{core}_KEY_UNLOCKED_COUNT_HI", key, expected=WDT_KEY_UNLOCKED)
        await self.csr_write(f"WDT{core}_COUNT_HI_WR", count_hi, WDT_COUNT_HI_PROBE)
        await self.csr_read(f"WDT{core}_KEY_RELOCKED_COUNT_HI", key, expected=WDT_KEY_LOCKED)
        await self.csr_read(f"WDT{core}_COUNT_AFTER", count, expected=WDT_COUNT_RESET)
        self.count_hi_proven.append(core)

    async def _write_width(self, core: int) -> None:
        key = self._reg(core, "KEY")
        cmp_ = self._reg(core, "CMP")
        ctrl = self._reg(core, "CTRL")

        # CMP: a 1-byte write is dropped without re-locking, a 2-byte write acts.
        await self._unlock(f"WDT{core}_KEY_WR_WIDTH", core)
        await self.csr_read(f"WDT{core}_KEY_UNLOCKED_WIDTH", key, expected=WDT_KEY_UNLOCKED)
        await self.csr_write(f"WDT{core}_CMP_WR_BYTE", cmp_, WDT_CMP_PROBE & 0xFF, length=1)
        await self.csr_read(f"WDT{core}_CMP_BYTE_DROPPED", cmp_, expected=WDT_CMP_RESET)
        await self.csr_read(f"WDT{core}_KEY_STILL_UNLOCKED", key, expected=WDT_KEY_UNLOCKED)
        await self.csr_write(f"WDT{core}_CMP_WR_HALF", cmp_, WDT_CMP_PROBE, length=2)
        await self.csr_read(f"WDT{core}_CMP_HALF_RB", cmp_, expected=WDT_CMP_PROBE)
        await self.csr_read(f"WDT{core}_KEY_RELOCKED_HALF", key, expected=WDT_KEY_LOCKED)
        await self._unlock(f"WDT{core}_KEY_WR_CMP_RESTORE", core)
        await self.csr_write(f"WDT{core}_CMP_RESTORE_WIDTH", cmp_, WDT_CMP_RESET)
        await self.csr_read(f"WDT{core}_CMP_RESTORE_WIDTH_RB", cmp_, expected=WDT_CMP_RESET)

        # CTRL: a 1-byte write to byte 0 acts and re-locks.
        await self._unlock(f"WDT{core}_KEY_WR_CTRL", core)
        await self.csr_write(f"WDT{core}_CTRL_WR_BYTE", ctrl, WDT_CTRL_SCALE_PROBE, length=1)
        await self.csr_read(f"WDT{core}_CTRL_BYTE_RB", ctrl, expected=WDT_CTRL_SCALE_PROBE)
        await self.csr_read(f"WDT{core}_KEY_RELOCKED_CTRL", key, expected=WDT_KEY_LOCKED)
        await self._unlock(f"WDT{core}_KEY_WR_CTRL_RESTORE", core)
        await self.csr_write(f"WDT{core}_CTRL_RESTORE", ctrl, WDT_CTRL_RESET, length=1)
        await self.csr_read(f"WDT{core}_CTRL_RESTORE_RB", ctrl, expected=WDT_CTRL_RESET)
        self.width_proven.append(core)

    async def body(self) -> None:
        for core in WDT_CORES:
            await self._key_protocol(core)
            await self._count_hi(core)
            await self._write_width(core)

        for proven, leg in (
            (self.cores_proven, "WDT key protocol"),
            (self.count_hi_proven, "WDT COUNT_HI re-lock"),
            (self.width_proven, "WDT write width"),
        ):
            assert proven == list(WDT_CORES), (
                f"{leg} proven on cores {proven}, expected one pass per core {list(WDT_CORES)}"
            )
        self.assert_all_reachable(
            len(WDT_CORES)
            * (
                WDT_KEY_ACCESSES_PER_CORE
                + WDT_COUNT_HI_ACCESSES_PER_CORE
                + WDT_WIDTH_ACCESSES_PER_CORE
            ),
            "WDT_KEY_CSR",
        )
        cocotb.log.info(
            "CHK-WDT-KEY-PROTOCOL: on each of %d cores, a CMP write with the "
            "block LOCKED left CMP at its generated reset 0x%04x, and the SAME "
            "write after KEY=0x%06x took 0x%08x back -- the two legs differ "
            "only in the key, so neither the key gate nor the CMP storage is "
            "assumed. KEY read 0x%x unlocked and 0x%x again after the single "
            "write, so the re-lock is observed too.",
            len(self.cores_proven),
            WDT_CMP_RESET,
            WDT_MAGIC_KEY,
            WDT_CMP_PROBE,
            WDT_KEY_UNLOCKED,
            WDT_KEY_LOCKED,
        )
        cocotb.log.info(
            "CHK-WDT-COUNTHI-RELOCK: on each of %d cores, COUNT_HI read 0x%x; "
            "with KEY reading 0x%x, a 32-bit write of 0x%08x to COUNT_HI made "
            "KEY read 0x%x with no other write in between, and COUNT read 0x%x "
            "before and after.",
            len(self.count_hi_proven),
            WDT_COUNT_HI_READ,
            WDT_KEY_UNLOCKED,
            WDT_COUNT_HI_PROBE,
            WDT_KEY_LOCKED,
            WDT_COUNT_RESET,
        )
        cocotb.log.info(
            "CHK-WDT-WRITE-WIDTH: on each of %d cores, with the block unlocked a "
            "1-byte CMP write of 0x%02x answered OKAY, left CMP at 0x%04x and "
            "KEY at 0x%x; a 2-byte CMP write of 0x%04x read back exactly and "
            "re-locked. A 1-byte CTRL write of 0x%x read back as 0x%x and "
            "re-locked.",
            len(self.width_proven),
            WDT_CMP_PROBE & 0xFF,
            WDT_CMP_RESET,
            WDT_KEY_UNLOCKED,
            WDT_CMP_PROBE,
            WDT_CTRL_SCALE_PROBE,
            WDT_CTRL_SCALE_PROBE,
        )
