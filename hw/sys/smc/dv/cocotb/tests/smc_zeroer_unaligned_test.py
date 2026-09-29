# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer jobs whose unaligned start makes the final beat partial, inside one page.

Both jobs stay inside a single 4 KB page, so the design keeps them in one burst
and the burst length and final-beat strobe follow from `DEST_ADDR[2:0]` together
with `SIZE`, not from `SIZE` alone. A job that starts partway into a beat has a
tail that spills into a further beat, and a small job can still straddle two
beats; getting either wrong leaves bytes inside the range poisoned or clears
bytes past the range.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_zeroer_unaligned_test_seq import smc_zeroer_unaligned_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_zeroer_unaligned_test(smc_base_test):
    """Unaligned in-page jobs whose final beat is partial."""

    required_evidence = (
        "CHK-ZEROER-UNALIGNED-TAIL",
        "CHK-ZEROER-UNALIGNED-SPAN",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_unaligned_test_seq("smc_zeroer_unaligned_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
