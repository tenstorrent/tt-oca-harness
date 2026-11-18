# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A private write queued on I3C0 and I3C1 with no target to answer it.

Both must return an address NACK carrying the command's TID, and the I3C0
controller must drive SDA low during the transfer. The I3C0 leg also samples
the wrapper's pad-enable gates: SCL is driven only low and the SDA output
enable is the push-pull select OR the inverse of the SDA level.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i3c_private_write_test_seq import smc_i3c_private_write_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i3c_private_write_test(smc_base_test):
    """Queue a private write on I3C0 and I3C1."""

    required_evidence = (
        "CHK-I3C-PRIVATE-WRITE",
        "CHK-I3C-SCL-OD-ONLY",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_private_write_test_seq("smc_i3c_private_write_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
