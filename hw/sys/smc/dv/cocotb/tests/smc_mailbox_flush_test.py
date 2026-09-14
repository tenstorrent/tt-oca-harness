# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox CTRL.wflush.

`smc_mailbox_field_sweep_test_seq` walks the port by offset and stops at IRQEN
@0x38, so CTRL @0x48 is exercised only here. It is `sw = w`, so the coverage
cannot be a readback -- it has to be the effect, which STATUS reports. See the
sequence docstring.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_flush_test_seq import smc_mailbox_flush_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_flush_test(smc_base_test):
    """CTRL.wflush empties the write FIFO a push had just filled."""

    required_evidence = (
        "CHK-MBOX-FLUSH",
        "CHK-MBOX-FLUSH-ARM",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_mailbox_flush_test_seq("mailbox_flush_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
