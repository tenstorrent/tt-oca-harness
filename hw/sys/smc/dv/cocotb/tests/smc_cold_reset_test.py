# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM cold-reset test.

Brings the SMC OSS top out of cold reset (handled by ``smc_base_test``), then
dispatches one observation sequence on the SMC reset agent. The scoreboard
verifies that the top-level powergood / reset observability outputs match
their expected post-release state.

This is the PyUVM, DTP-pattern port of the legacy
``test_smc_oss_reset_sanity`` flat cocotb test. Both coexist during the
migration so regressions on one cannot mask the other.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_cold_reset_test_seq import smc_cold_reset_test_seq


@pyuvm.test()
class smc_cold_reset_test(smc_base_test):
    """Run the SMC OSS cold-reset release sanity scenario."""

    async def run_scenario(self) -> None:
        seq = smc_cold_reset_test_seq("cold_reset_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
