# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_mailbox_int_test — SMU_ALL_004 rev 8.

DV-CARD:          SMU_ALL_004   ANCHOR: smc_mailbox_int_test
DV-CARD-REVISION: 8   RECORD-SHA256: f670f76181726330279f56dc04dc653ae5a882cc3531164ebf572168d950d862
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md @ artifact_revision 8   ENV: cocotb

Bare ``tb_top`` / ``smu_uvm_top`` SEP=0 — passive DECODE of
``ext_mailbox_interrupts`` width == NUM_MAILBOXES (32).
"""

from __future__ import annotations

import pyuvm

from seq_lib.smc_mailbox_int_test_seq import smc_mailbox_int_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smc_mailbox_int_test(smu_base_test):
    """SMU_ALL_004 r8: SMC external mailbox IRQ width DECODE (SEP=0)."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smc_mailbox_int_test SMU_ALL_004 r8 SEP=0 "
            "EXT.S2 width DECODE"
        )
        seq = smc_mailbox_int_test_seq(self)
        await seq.run()
