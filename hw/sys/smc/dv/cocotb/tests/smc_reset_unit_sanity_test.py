# SPDX-License-Identifier: Apache-2.0
"""COLD vs COLD_WARM across SEP WDT."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_reset_unit_sanity_test_seq import smc_reset_unit_sanity_test_seq


@pyuvm.test()
class smc_reset_unit_sanity_test(smc_base_test):
    """COLD scratch persists a SEP WDT pulse; COLD_WARM does not."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reset_unit_sanity_test_seq("reset_unit_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.pre_ok and seq.cold_ok and seq.warm_ok, (
            f"reset unit incomplete pre={seq.pre_ok} cold={seq.cold_ok} "
            f"warm={seq.warm_ok}"
        )
