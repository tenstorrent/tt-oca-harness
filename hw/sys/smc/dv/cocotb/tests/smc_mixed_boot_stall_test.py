# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO pad57 stall then JTAG override."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mixed_boot_stall_test_seq import smc_mixed_boot_stall_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mixed_boot_stall_test(smc_base_test):
    """GPIO gates fuse_reset; JTAG ovrd releases; val=1 cannot re-stall."""

    required_evidence = (
        "CHK-MIXED-BOOT-STALL-BASIC",
        "CHK-MIXED-BOOT-STALL-DROP",
        "CHK-MIXED-BOOT-STALL-GPIO",
        "CHK-MIXED-BOOT-STALL-OVRD",
        "CHK-MIXED-BOOT-STALL-VAL1",
        "CHK-MIXED-BOOT-STALL-WARM",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mixed_boot_stall_test_seq("mixed_boot_stall_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert (
            seq.gpio_gate_ok and seq.ovrd_release_ok and seq.val1_lockout_ok and seq.ovrd_drop_ok
        ), (
            f"mixed boot stall incomplete gpio={seq.gpio_gate_ok} "
            f"ovrd={seq.ovrd_release_ok} val1={seq.val1_lockout_ok} "
            f"drop={seq.ovrd_drop_ok}"
        )
