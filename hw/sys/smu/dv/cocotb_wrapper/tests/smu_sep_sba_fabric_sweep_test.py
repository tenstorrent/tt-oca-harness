# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_sba_fabric_sweep_test - SEP debug system bus over the paths that leave the SEP.

The SMU aperture, the alias remap to every high address bit, responder errors,
the SMC window and the external and TRNG apertures, each driven through the
SEP debug module's system bus on the SEP=1 wrapper.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_sba_fabric_sweep_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import smu_sep_sba_fabric_sweep_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_sba_fabric_sweep_test(smu_base_test):
    """SEP outbound, SMC, external and TRNG paths from the debug system bus; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_sep_sba_fabric_sweep_test SEP=1 SEP DM SBA sweep")
        seq = smu_sep_sba_fabric_sweep_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok, *seq.steps.values())
        assert all(steps), f"sep_sba_sweep incomplete s1..s8={steps}"
