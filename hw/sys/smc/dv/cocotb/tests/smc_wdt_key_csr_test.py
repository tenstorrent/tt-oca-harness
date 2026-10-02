# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS cluster WDT key protocol, COUNT_HI re-lock and write widths, all four cores."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_wdt_key_csr_test_seq import (
    WDT_CORES,
    smc_wdt_key_csr_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_key_csr_test(smc_base_test):
    """WDT writes are gated by the KEY magic value, COUNT_HI re-locks, and narrow writes are dropped, proven per core."""

    required_evidence = (
        "CHK-WDT-COUNTHI-RELOCK",
        "CHK-WDT-KEY-PROTOCOL",
        "CHK-WDT-WRITE-WIDTH",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_key_csr_test_seq("wdt_key_csr_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The only gate worth stating here that the sequence does not already
        # enforce: every core must have completed every leg. A run that proved
        # the key gate on one core and silently skipped the rest would satisfy
        # the sequence's own per-core compares.
        for proven, leg in (
            (seq.cores_proven, "WDT key protocol"),
            (seq.count_hi_proven, "WDT COUNT_HI re-lock"),
            (seq.width_proven, "WDT write width"),
        ):
            assert proven == list(WDT_CORES), (
                f"{leg} proven on cores {proven}, expected all of {list(WDT_CORES)}"
            )
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Booked as an activity stamp, not a check. The sequence's access
            # count is fixed by construction and `assert_all_reachable` has
            # already compared it exactly, so a floor here is a relation no RTL
            # behaviour can falsify. The proof is the per-access scoreboard
            # compares and the per-leg core asserts above.
            auto_evidence=True,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "Cluster WDT KEY-gated CMP write: locked write dropped (CMP "
                "stays at generated reset 0x1000), same write after "
                "KEY=0x51F15E accepted exactly, and KEY re-reads locked after "
                "the single write. COUNT_HI reads 0 and a 32-bit write to it "
                "re-locks. A 1-byte CMP write is dropped without re-locking, a "
                "2-byte CMP write and a 1-byte CTRL write act. Expectations "
                "from the wdt.rdl text plus generated reset values; wdt.rdl is "
                "map-only, so no generated register block backs them"
            ),
        )
