# SPDX-License-Identifier: Apache-2.0
"""SYS hang-detector stall timeout. Not SEP or irq_test."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_hang_detector_sys_timeout_test_seq import (
    smc_hang_detector_sys_timeout_test_seq,
)


@pyuvm.test()
class smc_hang_detector_sys_timeout_test(smc_base_test):
    """SYS_IN outstanding stall → timeout irq; unique vs SEP timeout."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_sys_timeout_test_seq("hang_detector_sys_timeout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.fire_ok and seq.drop_ok and seq.disable_ok, (
            f"SYS hang timeout incomplete fire={seq.fire_ok} "
            f"drop={seq.drop_ok} disable={seq.disable_ok}"
        )
