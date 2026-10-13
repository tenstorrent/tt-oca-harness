# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_mailbox_status_error_test — SMU_SMC_MAILBOX_WDT_007.

DV-CARD:          SMU_SMC_MAILBOX_WDT_007   ANCHOR: smu_smc_mailbox_status_error_test

Outbound mailbox 0 STATUS live flags, empty-read and full-write SLVERR with error flags,
ERROR_FLAGS clear on read, error IRQ enable/acknowledge, and SLVERR on read-only register writes.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_mailbox_status_error_test_seq import smu_smc_mailbox_status_error_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_mailbox_status_error_test(smu_base_test):
    """SMU_SMC_MAILBOX_WDT_007: mailbox 0 STATUS and access errors."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_smc_mailbox_status_error_test SMU_SMC_MAILBOX_WDT_007"
        )
        seq = smu_smc_mailbox_status_error_test_seq(self)
        await seq.run()
