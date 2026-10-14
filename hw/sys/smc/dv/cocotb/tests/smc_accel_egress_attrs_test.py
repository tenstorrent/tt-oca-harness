# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Burst, cache, protection and user attributes of DMA and zeroer requests at SYS_OUT."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_accel_egress_attrs_test_seq import smc_accel_egress_attrs_test_seq
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-ACCEL-EGRESS-CACHE",
    "CHK-ACCEL-EGRESS-INCR",
    "CHK-ACCEL-EGRESS-PROT-USER",
    "CHK-NONVAC",
)


@pyuvm.test()
class smc_accel_egress_attrs_test(smc_base_test):
    """DMA and zeroer requests carry INCR bursts and constant cache, prot and user values."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_accel_egress_attrs_test_seq("smc_accel_egress_attrs_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
