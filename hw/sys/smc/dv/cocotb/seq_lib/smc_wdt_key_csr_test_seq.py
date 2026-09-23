# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cluster WDT magic-key unlock protocol, per core. No Force, no firmware.

``hw/sys/smc/regs/blocks/wdt/wdt.rdl:105-111`` specifies that the magic key
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

``wdt.rdl`` is map-only (no generated register block), so the expectations here
come from the RDL text and the generated reset values.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# wdt.rdl:109 -- "Magic key (0x51F15E) must be written to this register before a
# write to any other register in this addrmap."
WDT_MAGIC_KEY = 0x51F15E
# wdt.rdl CMP reset. The one non-zero reset in the block, which is what lets the
# negative leg tell "write rejected" apart from "register reads zero anyway".
WDT_CMP_RESET = 0x1000
# `CMP` is a SINGLE 16-bit field, `wdogcmp0[15:0]` (wdt.rdl), not a 32-bit
# register; a wider probe reads back truncated to the field. The probe stays
# inside the field: alternating bits, and distinct from the 0x1000 reset, so
# neither a stuck register nor a dropped write can produce it.
WDT_CMP_MASK = 0xFFFF
WDT_CMP_PROBE = 0xA5A5
# KEY reads 1 while unlocked, 0 once the block has re-locked (wdt.rdl:109-110).
WDT_KEY_UNLOCKED = 0x1
WDT_KEY_LOCKED = 0x0

WDT_CORES = (0, 1, 2, 3)


class smc_wdt_key_csr_test_seq(SmcCsrSeq):
    """Per-core WDT key-gated write, with the locked write as its own control."""

    def __init__(self, name: str = "smc_wdt_key_csr_test_seq") -> None:
        super().__init__(name)
        #: cores whose negative AND positive legs both held
        self.cores_proven: list[int] = []

    def _reg(self, core: int, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_{reg}_BASE_ADDR")

    async def body(self) -> None:
        for core in WDT_CORES:
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
            await self.csr_write(f"WDT{core}_KEY_WR", key, WDT_MAGIC_KEY)
            await self.csr_read(f"WDT{core}_KEY_UNLOCKED", key, expected=WDT_KEY_UNLOCKED)
            await self.csr_write(f"WDT{core}_CMP_WR_UNLOCKED", cmp_, WDT_CMP_PROBE)
            await self.csr_read(f"WDT{core}_CMP_PROBE_RB", cmp_, expected=WDT_CMP_PROBE)

            # The block must have re-locked on that single write, with nothing
            # else written in between.
            await self.csr_read(f"WDT{core}_KEY_RELOCKED", key, expected=WDT_KEY_LOCKED)

            # Restore: needs its own unlock, which is itself further evidence
            # that the key is required for every write.
            await self.csr_write(f"WDT{core}_KEY_WR_RESTORE", key, WDT_MAGIC_KEY)
            await self.csr_write(f"WDT{core}_CMP_RESTORE", cmp_, WDT_CMP_RESET)
            await self.csr_read(f"WDT{core}_CMP_RESTORE_RB", cmp_, expected=WDT_CMP_RESET)
            self.cores_proven.append(core)

        assert self.cores_proven == list(WDT_CORES), (
            f"WDT key protocol proven on cores {self.cores_proven}, expected "
            f"one pass per core {list(WDT_CORES)}"
        )
        self.assert_all_reachable(len(WDT_CORES) * 12, "WDT_KEY_CSR")
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
