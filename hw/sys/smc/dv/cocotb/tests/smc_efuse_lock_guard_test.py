# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The eFuse guard answering a software lock, on three shadow fields.

Takes the first two SPARE entries and the OCCP transport timeout through the
same four steps: write and read the field while it is unlocked, set its
write lock and show a later write does not land, show the lock cannot be
cleared by writing LOCKS with the bit clear, then set its read lock and show
the read no longer discloses the field.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_lock_guard_test_seq import smc_efuse_lock_guard_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
#   the LOCKS read that shows every bit still clear                           1
#   3 fields x 11 accesses:                                                  33
#     the unlocked write and its readback                                     2
#     the write-lock write, its readback, the refused write and the readback
#       that shows the field unchanged                                        4
#     the write-1-to-set write and its readback                               2
#     the read-lock write, its readback and the read-locked read              3
EFUSE_LOCK_GUARD_MIN_CSR_ACCESSES = 1 + 3 * 11


@pyuvm.test()
class smc_efuse_lock_guard_test(smc_base_test):
    """Establish a software lock on three shadow fields and check the guard."""

    required_evidence = (
        "CHK-EFUSE-LOCK-GUARD-PRE",
        "CHK-EFUSE-LOCK-GUARD-READ",
        "CHK-EFUSE-LOCK-GUARD-WOSET",
        "CHK-EFUSE-LOCK-GUARD-WRITE",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_lock_guard_test_seq("smc_efuse_lock_guard_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            min_csr_accesses=EFUSE_LOCK_GUARD_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.write_locks_held} write locks, {seq.read_locks_held} read locks and "
                f"{seq.woset_proofs} write-1-to-set proofs enforced"
            ),
        )
