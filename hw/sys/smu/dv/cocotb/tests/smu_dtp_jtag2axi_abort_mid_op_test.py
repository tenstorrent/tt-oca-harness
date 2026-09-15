# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_jtag2axi_abort_mid_op_test — TAP and fabric survive an outstanding OTP op."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_jtag2axi_abort_mid_op_test_seq import (
    smu_dtp_jtag2axi_abort_mid_op_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_jtag2axi_abort_mid_op_test(smu_base_test):
    """IR+TRST taken mid-BUSY: IDCODE still reads and the fabric bridge still serves.

    The name is the stimulus. No abort is claimed -- see the sequence docstring.
    """

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_dtp_jtag2axi_abort_mid_op_test TierC JTAG2AXI-ABORT SEP=0 JTAG"
        )
        seq = smu_dtp_jtag2axi_abort_mid_op_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"jtag2axi_abort incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok} s4={seq.s4_ok}"
        )
