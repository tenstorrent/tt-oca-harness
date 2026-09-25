# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A private write queued on I3C0 and I3C1 with no target to answer it.

Both must return an address NACK carrying the command's TID, and the I3C0
controller must drive SDA low during the transfer.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i3c_private_write_test_seq import smc_i3c_private_write_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i3c_private_write_test(smc_base_test):
    """Queue a private write on I3C0 and I3C1."""

    required_evidence = ("CHK-I3C-PRIVATE-WRITE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_private_write_test_seq("smc_i3c_private_write_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
