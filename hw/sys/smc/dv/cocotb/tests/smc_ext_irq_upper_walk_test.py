# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""External inputs 17..255 raised and lowered one at a time, then together, at the raw vector.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_ext_irq_upper_walk_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ext_irq_upper_walk_test_seq import (
    CHECKERS,
    smc_ext_irq_upper_walk_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ext_irq_upper_walk_test(smc_base_test):
    """Walk inputs 17..255 through the synchroniser to the raw cpu_interrupts bits."""

    required_evidence = CHECKERS
    min_evidence = len(CHECKERS)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ext_irq_upper_walk_test_seq("ext_irq_upper_walk_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "the sequence did not finish the walk over inputs 17..255"
        assert seq.accesses == 1, f"{seq.accesses} SEP_IN accesses issued, want 1 (scratch read)"
        missing = [n for n in CHECKERS if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
