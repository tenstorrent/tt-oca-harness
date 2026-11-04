# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded SYS_OUT SLVERR and DECERR injections on JTAG, DMA and zeroer traffic."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sys_out_error_inject_rand_test_seq import (
    PASSES,
    smc_sys_out_error_inject_rand_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-NONVAC",
    "CHK-SOE-DMA-RETIRES",
    "CHK-SOE-JTAG-CODE",
    "CHK-SOE-MONITOR-TALLY",
    "CHK-SOE-RECOVERY",
    "CHK-SOE-ZEROER-CONSUMED",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_sys_out_error_inject_rand_test(smc_base_test):
    """Eight drawn passes of one-shot SYS_OUT errors, each followed by an OKAY recovery."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sys_out_error_inject_rand_test_seq(
            "sys_out_error_inject_rand_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        assert seq.done_passes == PASSES, f"{seq.done_passes} passes completed"
