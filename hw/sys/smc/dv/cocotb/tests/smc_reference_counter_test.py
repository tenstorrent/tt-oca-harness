# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL REFERENCE_COUNTER advances on refclk."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_reference_counter_test_seq import smc_reference_counter_test_seq


@pyuvm.test()
class smc_reference_counter_test(smc_base_test):
    """64-bit refclk counter must increase; not the OCTS timer."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reference_counter_test_seq("ref_count_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.advance_ok, "REFERENCE_COUNTER did not advance"
