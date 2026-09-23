# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM repeated cold-reset re-assert test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cold_reset_repeated_test_seq import smc_cold_reset_repeated_test_seq
from seq_lib.smc_isolate_pin_utils import smc_isolate_req_pinen_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cold_reset_repeated_test(smc_base_test):
    """Run the SMC OSS repeated cold-reset re-assert scenario."""

    required_evidence = (
        "CHK-MID-ASSERT-HOLD",
        "CHK-SENSE-DONE-REPAIR-ENABLED",
        "CHK-SKIP-MEM-REPAIR-PIN",
    )
    min_evidence = 3

    async def run_scenario(self) -> None:
        # Pin-based isolation is the isolate pin gated by ISOLATE_REQ_PINEN_REG
        # (clk_rst.adoc); enable it before the reset sequence drives the pin.
        pinen = smc_isolate_req_pinen_seq("isolate_req_pinen_seq", enable=True)
        await self.start_seq(pinen, self.env.sys_axi_agent.sequencer)
        seq = smc_cold_reset_repeated_test_seq("cold_reset_repeated_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
