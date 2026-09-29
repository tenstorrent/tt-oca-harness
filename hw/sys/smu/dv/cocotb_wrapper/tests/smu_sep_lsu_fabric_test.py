# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_lsu_fabric_test - SEP load/store traffic on the paths that leave the SEP.

The debug module runs a short ICCM probe (assets/gen_sep_lsu_probe_itcm.py)
against the SMU aperture under responder backpressure, with and without the
region's side-effect bit, against the SEP view of the SMC SPM, and against the
external aperture's DECERR slave.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_lsu_fabric_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_lsu_fabric_test_seq import smu_sep_lsu_fabric_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_lsu_fabric_test(smu_base_test):
    """SEP load/store unit traffic to the SMU, SMC and external apertures; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_sep_lsu_fabric_test SEP=1 SEP DM LSU probe")
        seq = smu_sep_lsu_fabric_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok, *seq.steps.values())
        assert all(steps), f"sep_lsu_fabric incomplete s1..s8={steps}"
