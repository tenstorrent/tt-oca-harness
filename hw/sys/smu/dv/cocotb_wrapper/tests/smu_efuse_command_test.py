# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_efuse_command_test - SEP and SMC eFuse read and program commands.

The SEP debug module's system bus drives the SEP and SMC efuse_interface_ctrl
blocks: a read at every fuse address bit, programs of the middle fuse word with
and without read-back, and out-of-range commands with their sticky errors.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_efuse_command_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_efuse_command_test_seq import smu_efuse_command_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_efuse_command_test(smu_base_test):
    """eFuse fuse-command ports of the SEP and SMC; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_efuse_command_test SEP=1 SEP DM SBA eFuse commands")
        seq = smu_efuse_command_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok, *seq.steps.values())
        assert all(steps), f"efuse_command incomplete s1..s3,sep,smc={steps}"
