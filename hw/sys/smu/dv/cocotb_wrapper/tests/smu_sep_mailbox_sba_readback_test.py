# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_mailbox_sba_readback_test - WIRQT readback of the sixteen SEP mailbox ports.

Spec: hw/sys/sep/doc/mailbox.adoc:28-30, axil_mailbox.rdl WIRQT, axil_mailbox_sep_wrap.rdl.

From the SEP debug system bus: WIRQT of every outbound and inbound mailbox port reads 0, takes a
value below the FIFO depth and reads it back.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_mailbox_sba_readback_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_mailbox_sba_readback_test_seq import smu_sep_mailbox_sba_readback_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_mailbox_sba_readback_test(smu_base_test):
    """SEP mailbox WIRQT write-readback over the SEP debug system bus; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_sep_mailbox_sba_readback_test SEP=1 SEP DM SBA")
        seq = smu_sep_mailbox_sba_readback_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok, seq.done)
        assert all(steps), f"sep_mailbox_sba_readback incomplete {steps}"
