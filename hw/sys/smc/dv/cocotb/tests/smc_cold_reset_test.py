# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM cold-reset test.

DV-CARD:          SMC_001   ANCHOR: smc_cold_reset_test
DV-CARD-REVISION: 2   RECORD-SHA256: a6539636377899cdcc508a3eb757eb5c746a96f1516cb74ded8324033091cc4f
DV-CARD-SOURCE:   hw/sys/smc/dv/tb/SMC_VPLAN_DETAIL.md @ artifact_revision 1   ENV: cocotb

Brings the SMC OSS top out of cold reset (handled by ``smc_base_test``), then
runs the SMC_001 checkbox sequence on the reset + clk agents and emits exact
``CHK-*`` evidence lines required by the approved card.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_cold_reset_test_seq import smc_cold_reset_test_seq


@pyuvm.test()
class smc_cold_reset_test(smc_base_test):
    """Run the SMC OSS cold-reset / POR / cool SMC_001 scenario."""

    async def run_scenario(self) -> None:
        seq = smc_cold_reset_test_seq("cold_reset_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
