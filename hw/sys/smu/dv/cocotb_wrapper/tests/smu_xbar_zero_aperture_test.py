# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xbar_zero_aperture_test - the SMU crossbar with the SEP aperture, the SMC aperture and both at size 0.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xbar_zero_aperture_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xbar_zero_aperture_test_seq import smu_xbar_zero_aperture_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xbar_zero_aperture_test(smu_base_test):
    """A zero-size aperture matches nothing and its traffic takes the miss route; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_xbar_zero_aperture_test SEP=1 zero-size apertures")
        seq = smu_xbar_zero_aperture_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok) + tuple(
            seq.steps.get(s, False) for s in ("S4", "S5", "S6", "S7", "S8")
        )
        assert all(steps), f"zero aperture incomplete s1..s8={steps}"
