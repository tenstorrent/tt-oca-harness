# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG boot-stall override of GPIO pad57 sticky."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_jtag_boot_stall_sanity_test_seq import (
    smc_jtag_boot_stall_sanity_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_boot_stall_sanity_test(smc_base_test):
    """JTAG boot-stall override clears sticky while pad 57 is held."""

    required_evidence = (
        "CHK-JTAG-BOOT-STALL-BASIC",
        "CHK-JTAG-BOOT-STALL-HOLD",
        "CHK-JTAG-BOOT-STALL-LOCK",
        "CHK-JTAG-BOOT-STALL-OVRD",
        "CHK-JTAG-BOOT-STALL-WARM",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_boot_stall_sanity_test_seq("jtag_boot_stall_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.held_ok and seq.override_ok and seq.lockout_ok, (
            f"jtag boot stall incomplete hold={seq.held_ok} "
            f"ovrd={seq.override_ok} lock={seq.lockout_ok}"
        )
