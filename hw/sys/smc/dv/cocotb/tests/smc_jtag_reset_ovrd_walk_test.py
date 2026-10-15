# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fuse, cold, warm and every subsystem cold/warm jtag_reset_ctrl_i override."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_jtag_reset_ovrd_walk_test_seq import smc_jtag_reset_ovrd_walk_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_reset_ovrd_walk_test(smc_base_test):
    """Every override mux smc_jtag_reset_ctrl_test leaves idle, through its reset pin."""

    required_evidence = (
        "CHK-JTAG-OVRD-WALK-BASIC",
        "CHK-JTAG-OVRD-WALK-COLD",
        "CHK-JTAG-OVRD-WALK-FUSE",
        "CHK-JTAG-OVRD-WALK-IDLE",
        "CHK-JTAG-OVRD-WALK-SS-COLD",
        "CHK-JTAG-OVRD-WALK-SS-WARM",
        "CHK-JTAG-OVRD-WALK-WARM",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_reset_ovrd_walk_test_seq("jtag_reset_ovrd_walk_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.ss_warm_ok and seq.ss_cold_ok and seq.warm_ok and seq.fuse_ok and seq.cold_ok, (
            f"jtag_reset_ovrd_walk incomplete ss_warm={seq.ss_warm_ok} "
            f"ss_cold={seq.ss_cold_ok} warm={seq.warm_ok} fuse={seq.fuse_ok} cold={seq.cold_ok}"
        )
