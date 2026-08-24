# SPDX-License-Identifier: Apache-2.0
"""GPIO ACCESS_FILTER AxPROT."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_gpio_filter_access_sep_test_seq import (
    smc_gpio_filter_access_sep_test_seq,
)


@pyuvm.test()
class smc_gpio_filter_access_sep_test(smc_base_test):
    """GPIO0/1 ACCESS_FILTER: AxPROT=1 allow, AxPROT=0 error-slave."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_filter_access_sep_test_seq("gpio_filter_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.pre_ok and seq.priv_ok and seq.unpriv_ok and seq.gpio1_ok, (
            f"gpio filter incomplete pre={seq.pre_ok} priv={seq.priv_ok} "
            f"unpriv={seq.unpriv_ok} gpio1={seq.gpio1_ok}"
        )
