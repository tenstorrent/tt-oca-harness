# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_sba_peripheral_test - SEP peripherals whose outputs cross the SMU.

From the SEP debug system bus: every SEP-to-SMC mailbox interrupt, the SPI host
in quad mode with its watermark trigger and event interrupt, the
security-disable token match and mismatch, and a watchdog bite.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_sba_peripheral_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_sba_peripheral_test_seq import smu_sep_sba_peripheral_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_sba_peripheral_test(smu_base_test):
    """SEP mailbox, SPI host, security-disable and watchdog outputs; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_sep_sba_peripheral_test SEP=1 SEP DM SBA")
        seq = smu_sep_sba_peripheral_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok, *seq.steps.values())
        assert all(steps), f"sep_sba_peripheral incomplete {steps}"
