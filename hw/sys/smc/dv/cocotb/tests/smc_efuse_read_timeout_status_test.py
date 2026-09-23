# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse READ_STATUS on a timed-out read.

A timed-out eFuse read must set EFUSE_READ_CTRL.READ_STATUS. The bit is proven
clear on an arming read first, so the set observed after the timeout is a
transition and not a stale value.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_efuse_read_timeout_status_test_seq import (
    smc_efuse_read_timeout_status_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_read_timeout_status_test(smc_base_test):
    """A timed-out eFuse read must set EFUSE_READ_CTRL.READ_STATUS."""

    required_evidence = (
        "CHK-EFUSE-TMO-RD-STATUS-ARM",
        "CHK-EFUSE-TMO-RD-STATUS-SET",
    )
    min_evidence = 2

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
