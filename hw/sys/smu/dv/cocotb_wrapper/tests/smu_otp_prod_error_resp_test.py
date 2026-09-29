# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_otp_prod_error_resp_test - OTP bridge error responses under PROD.

Under the PROD shadow image the SMC and SEP eFuse JTAG policies refuse OTP
bridge writes and most reads with DECERR, while JTAG_PUBLIC_IDENTITY reads on
the SMC and eFuse MMR accesses on the SEP still complete; a cool reset of the
SMC leaves its bridge answering.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_otp_prod_error_resp_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_otp_prod_error_resp_seq import smu_otp_prod_error_resp_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_otp_prod_error_resp_test(smu_base_test):
    """SMC and SEP OTP JTAG2AXI refusals under PROD; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_otp_prod_error_resp_test SEP=1 PROD posture")
        seq = smu_otp_prod_error_resp_seq(self)
        await seq.run()
        assert all(seq.steps.values()), f"OTP PROD error sweep incomplete {seq.steps}"
