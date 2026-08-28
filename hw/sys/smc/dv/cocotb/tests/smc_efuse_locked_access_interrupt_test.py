# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse locked-shadow access IRQ. Not map/LC."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_efuse_locked_access_interrupt_test_seq import (
    smc_efuse_locked_access_interrupt_test_seq,
)


@pyuvm.test()
class smc_efuse_locked_access_interrupt_test(smc_base_test):
    """CHIPLET_ID unlocked write silent; locked write/read pulse bit 28."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_locked_access_interrupt_test_seq("efuse_lock_irq_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # WHERE THE TEETH ARE. The `*_ok` flags are set unconditionally after
        # their legs, and every leg either raises or compares with `expected=`,
        # so all of them are literal True at this line: the assert they used to
        # feed could not fail on anything the DUT did
        # ([NO-ALWAYS-PASS-CHECKER]).
        #
        # The fail-capable content is in the sequence: the locked read must return
        # the SPEC blocked-read signature 0xBADCAB1E
        # (hw/ip/efuse/doc/architecture.adoc:299), enforced by the
        # scoreboard, and `_count_edges_during` must see at least one edge on
        # the real interrupt net `peripheral_interrupts[28]`.
        #
        # What is kept is the one thing not implied upstream: that every leg
        # actually ran. A refactor that made a bounded wait non-raising, or a
        # leg quietly skipped, fails here.
        legs = {"unlock": seq.unlock_ok, "wrlock": seq.wrlock_ok,
                "rdlock": seq.rdlock_ok}
        missing = [k for k, v in legs.items() if not v]
        assert not missing, f"efuse lock irq legs that did not run: {missing}"
