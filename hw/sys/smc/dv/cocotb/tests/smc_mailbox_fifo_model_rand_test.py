# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded mailbox FIFO model: STATUS, threshold flags, ERROR_FLAGS and flushes on drawn pairs."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_fifo_model_rand_test_seq import smc_mailbox_fifo_model_rand_test_seq
from smc_base_test import smc_base_test

# Accesses the four passes issue at the least: fills 2, 2, 0 and 0, no extra access and every
# flush at level 1. The drawn fills and extras add to it, so the count is a floor.
MIN_ACCESSES = 320


@pyuvm.test()
class smc_mailbox_fifo_model_rand_test(smc_base_test):
    """Drawn pairs, directions, fills and thresholds against a per-direction FIFO model."""

    required_evidence = (
        "CHK-MBFM-CLEAR",
        "CHK-MBFM-ERRFLAG",
        "CHK-MBFM-FLUSH",
        "CHK-MBFM-LEVEL",
        "CHK-MBFM-RESET",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_fifo_model_rand_test_seq(
            "smc_mailbox_fifo_model_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "mailbox FIFO model sequence did not complete"
        assert seq.accesses >= MIN_ACCESSES, (
            f"only {seq.accesses} SEP_IN accesses issued, want >= {MIN_ACCESSES}"
        )
        # The scoreboard tally counts every SEP_IN item of the run, the sequence's among them.
        checked = self.env.scoreboard.sys_axi_checks_seen
        assert checked >= seq.accesses, f"scoreboard checked {checked} of {seq.accesses} accesses"
