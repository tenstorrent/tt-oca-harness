# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded GPIO pad direction and interrupt configurations against drawn pad level sequences."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_pad_config_rand_test_seq import smc_gpio_pad_config_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_pad_config_rand_test(smc_base_test):
    """Drawn pads and configurations: output enable per code, interrupt per type and enable."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-PADCFG-DIR",
        "CHK-PADCFG-EDGE",
        "CHK-PADCFG-LEVEL",
        "CHK-PADCFG-RESET",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_pad_config_rand_test_seq(
            "smc_gpio_pad_config_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "GPIO pad configuration sequence did not complete"
