# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_mailbox_int_test — SMU_ALL_004.

DV-CARD:          SMU_ALL_004   ANCHOR: smu_smc_mailbox_int_test

DECODE of ``ext_mailbox_interrupts``:
width == NUM_MAILBOXES (32), and mailbox 0 / 31 IRQs raised over J2A move
bits 0 / 31.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_mailbox_int_test_seq import smu_smc_mailbox_int_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_mailbox_int_test(smu_base_test):
    """SMU_ALL_004: SMC external mailbox IRQ width DECODE."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_mailbox_int_test SMU_ALL_004 EXT.S2 width DECODE")
        seq = smu_smc_mailbox_int_test_seq(self)
        await seq.run()
