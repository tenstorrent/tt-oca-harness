# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Packed jtag_reset_ctrl_i cool and SS0 warm override."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_jtag_reset_ctrl_test_seq import smc_jtag_reset_ctrl_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_reset_ctrl_test(smc_base_test):
    """Struct pin mux; not boot-stall JTAG, FLR, or rst_cool_ni proxy."""

    required_evidence = (
        "CHK-JTAG-RST-BASIC",
        "CHK-JTAG-RST-COOL",
        "CHK-JTAG-RST-IDLE",
        "CHK-JTAG-RST-SS0",
        "CHK-JTAG-RST-WARM-SCRATCH",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_reset_ctrl_test_seq("jtag_reset_ctrl_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.cool_ok and seq.ss0_ok, (
            f"jtag_reset_ctrl incomplete cool={seq.cool_ok} ss0={seq.ss0_ok}"
        )
