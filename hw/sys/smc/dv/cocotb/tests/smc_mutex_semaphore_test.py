# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL MUTEX[0]/MUTEX[1] take-deny-release and SEMA[0] signed accumulate."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mutex_semaphore_test_seq import (
    EXPECTED_VALUE_CHECKS,
    MUTEX_FREE,
    MUTEX_TAKEN,
    SEMA_RESET,
    SEMA_STEP,
    smc_mutex_semaphore_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mutex_semaphore_test(smc_base_test):
    """CPU_CTRL MUTEX/SEMA over SEP_IN AXI (expectations from cpu_ctrl.rdl)."""

    required_evidence = (
        "CHK-MUTEX-BASIC",
        "CHK-MUTEX-HELD",
        "CHK-MUTEX-NEIGHBOUR-FREE",
        "CHK-MUTEX-NEIGHBOUR-HOLD",
        "CHK-MUTEX-REL",
        "CHK-MUTEX-TAKE",
        "CHK-SEMA-ACCUMULATE",
    )
    min_evidence = 7

    async def run_scenario(self) -> None:
        seq = smc_mutex_semaphore_test_seq("mutex_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Re-derive the verdict from the DUT words the sequence measured, not
        # from booleans the sequence set itself: if a compare inside body() is
        # ever demoted to a log line, these still fail.
        assert (seq.take, seq.deny, seq.free_after_release) == (
            MUTEX_FREE,
            MUTEX_TAKEN,
            MUTEX_FREE,
        ), (
            f"MUTEX[0] take/deny/release wrong: take=0x{seq.take:x} "
            f"deny=0x{seq.deny:x} free=0x{seq.free_after_release:x} "
            f"(expected 0x{MUTEX_FREE:x}/0x{MUTEX_TAKEN:x}/0x{MUTEX_FREE:x})"
        )
        assert (
            seq.nbr_free_while_held,
            seq.nbr_held_after_release,
            seq.nbr_free_after_own_release,
        ) == (MUTEX_FREE, MUTEX_TAKEN, MUTEX_FREE), (
            f"MUTEX[1] is not independent of MUTEX[0]: "
            f"free_while_m0_held=0x{seq.nbr_free_while_held:x} "
            f"held_after_m0_rel=0x{seq.nbr_held_after_release:x} "
            f"free=0x{seq.nbr_free_after_own_release:x}"
        )
        assert (seq.sema_reset, seq.sema_inc, seq.sema_dec) == (
            SEMA_RESET,
            SEMA_RESET + SEMA_STEP,
            SEMA_RESET,
        ), (
            f"SEMA[0] signed accumulate wrong: reset=0x{seq.sema_reset:x} "
            f"inc=0x{seq.sema_inc:x} dec=0x{seq.sema_dec:x}"
        )
        # Independent-observer floor: the scoreboard's own per-value tally.
        assert seq.value_checks >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {seq.value_checks} value-checked reads, "
            f"expected >= {EXPECTED_VALUE_CHECKS}"
        )
