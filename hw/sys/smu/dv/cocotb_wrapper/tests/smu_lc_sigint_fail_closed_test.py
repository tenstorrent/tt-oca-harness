# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_sigint_fail_closed_test - a broken LC_STATE pair raises lc_sigint_err_o.

The bench breaks the LC_STATE pair the SEP exports (``+lc_sigint_inject``); the SMU reports
the integrity error on ``lc_sigint_err_o`` and the SMC OTP bridge refuses every access until
the pair is legal again, while the SEP OTP bridge keeps answering.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_sigint_fail_closed_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_lc_sigint_fail_closed_seq import smu_lc_sigint_fail_closed_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_lc_sigint_fail_closed_test(smu_base_test):
    """lc_sigint_err_o and the SMC OTP refusal across a broken LC_STATE pair."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_sigint_fail_closed_test SEP=1 TEST_DEV posture, "
            "LC_STATE pair fault inject"
        )
        seq = smu_lc_sigint_fail_closed_seq(self)
        await seq.run()
        assert all(seq.steps.values()), f"LC sigint fail-closed sweep incomplete {seq.steps}"
