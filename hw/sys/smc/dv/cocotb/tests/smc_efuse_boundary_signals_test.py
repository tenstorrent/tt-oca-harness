# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse ext_boot_seq_done / fuse_reset_n interlock (G6)."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_efuse_boundary_signals_test_seq import (
    smc_efuse_boundary_signals_test_seq,
)


@pyuvm.test()
class smc_efuse_boundary_signals_test(smc_base_test):
    """Sense completes under ext_boot hold; delayed fuse_reset_n waits release."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_boundary_signals_test_seq("efuse_bnd_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.hold_ok and seq.map_ok and seq.release_ok, (
            f"efuse boundary incomplete hold={seq.hold_ok} "
            f"map={seq.map_ok} rel={seq.release_ok}"
        )
