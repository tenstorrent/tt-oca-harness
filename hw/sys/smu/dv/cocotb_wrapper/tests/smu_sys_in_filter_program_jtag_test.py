# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sys_in_filter_program_jtag_test — inbound0 program then SMN OKAY."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sys_in_filter_program_jtag_test_seq import (
    smu_sys_in_filter_program_jtag_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sys_in_filter_program_jtag_test(smu_base_test):
    """J2A programs inbound0; SMN VERSION_LO OKAY; WDT still DECERR."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_sys_in_filter_program_jtag_test TierA SYS-IN program SEP=1 J2A+s_axi"
        )
        seq = smu_sys_in_filter_program_jtag_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok and seq.s5_ok, (
            f"filter_program incomplete s1={seq.s1_ok} s2={seq.s2_ok} "
            f"s3={seq.s3_ok} s4={seq.s4_ok} s5={seq.s5_ok}"
        )
