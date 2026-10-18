# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_jtag2axi_caps_single_op_test — JTAG2AXI capability words and SINGLE_OP status."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_jtag2axi_caps_single_op_test_seq import (
    smu_dtp_jtag2axi_caps_single_op_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_jtag2axi_caps_single_op_test(smu_base_test):
    """Three JTAG2AXI capability words and the SMC fabric SINGLE_OP op field as status."""

    use_shared_env = True
    required_evidence = (
        "CHK-DBG-J2A-CAPS-OTP",
        "CHK-DBG-J2A-CAPS-SETUP",
        "CHK-DBG-J2A-CAPS-SMC",
        "CHK-DBG-J2A-CAPS-STABLE",
        "CHK-DBG-J2A-SINGLE-DECERR",
        "CHK-DBG-J2A-SINGLE-NOP",
        "CHK-DBG-J2A-SINGLE-OKAY",
        "CHK-DBG-J2A-SINGLE-RECOVERY",
        "CHK-DBG-J2A-SINGLE-SLVERR",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_dtp_jtag2axi_caps_single_op_test SEP=1 JTAG")
        await smu_dtp_jtag2axi_caps_single_op_test_seq(self).run()
