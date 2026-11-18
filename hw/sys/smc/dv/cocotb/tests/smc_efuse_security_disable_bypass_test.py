# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse sense bypass with sep_security_disable_i held at 1 from time 0 over a non-zero image."""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_efuse_image_pattern_test_seq import load_image
from seq_lib.smc_efuse_security_disable_bypass_test_seq import (
    BypassSampler,
    smc_efuse_security_disable_bypass_test_seq,
)
from smc_base_test import smc_base_test
from smc_efuse_image_pattern_base import write_image


@pyuvm.test()
class smc_efuse_security_disable_bypass_test(smc_base_test):
    """No bank read, all-zero shadow reads at three drawn times, no wait for sense done."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SDB-ACCESS-NO-WAIT",
        "CHK-SDB-HOOK-LEVEL",
        "CHK-SDB-IMAGE-NONZERO",
        "CHK-SDB-NO-BANK-READ",
        "CHK-SDB-SHADOW-ZERO",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    run_written_file_plusargs = ("smc_efuse_hex",)

    def build_phase(self) -> None:
        super().build_phase()
        assert cocotb.plusargs.get("smc_sep_security_disable") is not None, (
            "the testlist entry must carry +smc_sep_security_disable"
        )
        self.image = load_image(write_image("random", self.random_seed()))
        self.sampler = BypassSampler()
        cocotb.start_soon(self.sampler.run())

    async def run_scenario(self) -> None:
        seq = smc_efuse_security_disable_bypass_test_seq(
            "smc_efuse_security_disable_bypass_test_seq",
            seed=self.random_seed(),
            image=self.image,
            sampler=self.sampler,
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "security-disable bypass sequence did not complete"
