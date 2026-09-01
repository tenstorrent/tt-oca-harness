# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS sideband CSR smoke."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sideband_protocol_smoke_test_seq import (
    smc_sideband_protocol_smoke_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sideband_protocol_smoke_test(smc_base_test):
    """Run the AVSBus sideband CSR representative precheck."""

    async def run_scenario(self) -> None:
        seq = smc_sideband_protocol_smoke_test_seq("sideband_protocol_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
