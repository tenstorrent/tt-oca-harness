# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctm_self_loop_test - a CT_SRC mask selecting its own wire-OR CTP lane.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xtrig_ctm_self_loop_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xtrig_ctm_self_loop_test_seq import smu_xtrig_ctm_self_loop_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_ctm_self_loop_test(smu_base_test):
    """A self-selecting mask re-triggers a wire-OR CTP lane until the mask is cleared."""

    use_shared_env = True
    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-XT-SELFLOOP-ALIVE",
        "CHK-XT-SELFLOOP-CONTROL",
        "CHK-XT-SELFLOOP-READBACK",
        "CHK-XT-SELFLOOP-RETRIGGER",
        "CHK-XT-SELFLOOP-STOP",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_xtrig_ctm_self_loop_test SEP=1 JTAG")
        seq = smu_xtrig_ctm_self_loop_test_seq(self)
        await seq.run()
        assert seq.done, "self-loop sequence incomplete"
