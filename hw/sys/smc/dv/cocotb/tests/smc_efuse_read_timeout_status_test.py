# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse READ_STATUS-on-timeout reproducer for issue #1603.

EXPECTED TO FAIL against current RTL. Enrolled in the `rtl_issue` group only --
no `ci` tag, not in `smoke`. When #1603 is fixed this belongs in the eFuse
testlist with the `ci` tag; until then it holds the evidence in runnable form.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_efuse_read_timeout_status_test_seq import (
    smc_efuse_read_timeout_status_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_read_timeout_status_test(smc_base_test):
    """#1603: a timed-out eFuse read must set EFUSE_READ_CTRL.READ_STATUS."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_read_timeout_status_test_seq("efuse_read_tmo_status_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the emitted tokens, not on a flag the sequence set: each leg
        # raises on failure, so a relayed boolean could only report that the
        # line was reached.
        required = (
            "CHK-EFUSE-TMO-RD-STATUS-ARM",
            "CHK-EFUSE-TMO-RD-STATUS-SET",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
