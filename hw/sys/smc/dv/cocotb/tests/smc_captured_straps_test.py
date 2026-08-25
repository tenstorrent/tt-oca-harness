# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""captured_straps_i to reset_unit STRAPS_LO/HI."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_captured_straps_test_seq import smc_captured_straps_test_seq


@pyuvm.test()
class smc_captured_straps_test(smc_base_test):
    """Product strap pin; not the GPIO IRQ sibling."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_captured_straps_test_seq("captured_straps_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.idle_ok and seq.pat_a_ok and seq.pat_b_ok, (
            f"straps incomplete idle={seq.idle_ok} "
            f"a={seq.pat_a_ok} b={seq.pat_b_ok}"
        )
