# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ss_reset_complete_i CSR and SS0 warm_reset_n. No firmware."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ss_reset_complete_test_seq import (
    SS_COMPLETE_ALL_ONE,
    SS_COMPLETE_DROP_0_31,
    SS_WARM_RESET_VALUE,
    smc_ss_reset_complete_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ss_reset_complete_test(smc_base_test):
    """Pin→CSR complete + SW warm SS0; not the FW handshake binary."""

    required_evidence = (
        "CHK-SS-COMPLETE-DROP",
        "CHK-SS-COMPLETE-IDLE",
        "CHK-SS-COMPLETE-RESTORE",
        "CHK-SS-COMPLETE-SCRATCH-RW",
        "CHK-SS-WARM-SS0",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ss_reset_complete_test_seq("ss_reset_complete_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # "A wrong CSR word or a wrong pin level fails here even if every step
        # ran" holds for only one of the three gates below
        # ([NO-ALWAYS-PASS-CHECKER]):
        #
        #   * `idle_csr` / `drop_csr` / `restore_csr` are returned by
        #     `_await_csr`, which RAISES unless the value equals what is being
        #     waited for. By the time this line runs they cannot hold anything
        #     else, so comparing them adds no failure mode. Same for
        #     `warm_pins` via `_await_warm_pin`. Both gates only guard against a
        #     refactor that makes those helpers non-raising -- they are NOT this
        #     testcase's proof; the sequence's bounded waits are.
        #
        #   * `warm_csr` IS a real gate: those three words come from plain
        #     `csr_read` with no `expected=`, and the sequence asserts only bit
        #     0 of the asserted/released reads, so this full-word compare covers
        #     the remaining 31 bits and fails on a wrong word.
        assert (seq.idle_csr, seq.drop_csr, seq.restore_csr) == (
            SS_COMPLETE_ALL_ONE,
            SS_COMPLETE_DROP_0_31,
            SS_COMPLETE_ALL_ONE,
        ), (
            f"ss_reset_complete_i -> CSR mirror wrong: idle=0x{seq.idle_csr:x} "
            f"drop=0x{seq.drop_csr:x} restore=0x{seq.restore_csr:x}, expected "
            f"0x{SS_COMPLETE_ALL_ONE:x}/0x{SS_COMPLETE_DROP_0_31:x}/0x{SS_COMPLETE_ALL_ONE:x}"
        )
        assert seq.warm_pins == (1, 0, 1), (
            f"ss_reset_ctrl[0].warm_reset_n did not follow the SW bit 1->0->1: {seq.warm_pins}"
        )
        assert seq.warm_csr == (
            SS_WARM_RESET_VALUE,
            SS_WARM_RESET_VALUE & ~0x1,
            SS_WARM_RESET_VALUE,
        ), (
            f"SS_WARM_RESET_N readbacks {seq.warm_csr} do not match the "
            f"programmed sequence around reset value 0x{SS_WARM_RESET_VALUE:x}"
        )
