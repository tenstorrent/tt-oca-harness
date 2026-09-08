# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SS_COLD_RESET_LOCK write-one-to-set and reset masking.

Covers a register no enrolled testcase read. Written natively rather than
ported from `fw/tests/cold_reset_lock_sanity`, because SEP_IN AXI already
reaches the reset unit and a firmware image would add a dependency for nothing.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cold_reset_lock_test_seq import smc_cold_reset_lock_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cold_reset_lock_test(smc_base_test):
    """The cold-reset lock sets once and gates the reset register."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cold_reset_lock_test_seq("cold_reset_lock_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the emitted tokens rather than on a boolean the sequence set:
        # each leg raises on failure, so a relayed flag could only ever report
        # that the line was reached.
        required = (
            "CHK-COLD-RESET-LOCK-ARM",
            "CHK-COLD-RESET-LOCK-WOSET",
            "CHK-COLD-RESET-LOCK-MASKS-WRITE",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
