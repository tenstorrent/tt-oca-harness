# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_mailbox_aperture_layout_test - mailbox register behaviour.

Register offsets within a mailbox aperture, the 0x1000 stride, per-mailbox independence of WIRQT
and IRQEN, the inbound aperture of pair 0, SMC_ATTRIBUTES, and the response above the registers.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_mailbox_aperture_layout_test_seq import (
    smu_smc_mailbox_aperture_layout_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_mailbox_aperture_layout_test(smu_base_test):
    """Mailbox aperture layout over the SMC fabric JTAG2AXI bridge."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_mailbox_aperture_layout_test")
        seq = smu_smc_mailbox_aperture_layout_test_seq(self)
        await seq.run()
