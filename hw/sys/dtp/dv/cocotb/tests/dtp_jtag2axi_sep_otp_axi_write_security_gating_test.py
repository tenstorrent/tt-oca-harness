# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_sep_otp_axi_write_security_gating_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_otp_axi_test_seq import dtp_jtag2axi_otp_axi_test_seq


@pyuvm.test()
class dtp_jtag2axi_sep_otp_axi_write_security_gating_test(dtp_base_test):
    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_otp_axi_test_seq,
            "sep_otp_write_security_gating",
            specific_env="DTP_JTAG2AXI_SEP_OTP_AXI_WRITE_SECURITY_GATING_TEST_LOOPS",
            default_loops=1,
            group_env="DTP_JTAG2AXI_TEST_LOOPS",
            target="sep_otp",
            scenario="write_security_gating",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"sep_otp write_security_gating status {DtpJtag2AxiStatus(seq.status).name}"
            )
