# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The fuse-secret locks stay unset past [S25]/[S26]; the self-check halts with 0xF004.

The contract, stimulus and checks are in sep_rom_selfcheck_reverify_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_gate_ledger_base import AFTER_S17_LINE, GATES, sep_rom_gate_ledger_base
from rom_fw.sep_rom_selfcheck_reverify_base import lock_fault_edits


@pyuvm.test()
class sep_rom_selfcheck_locks_unset_test(sep_rom_gate_ledger_base):
    def extra_watch(self) -> set[int]:
        return set(lock_fault_edits(self.img))

    async def inject(self, obs) -> None:
        await self.wait_line(obs, AFTER_S17_LINE)
        await self.patch(lock_fault_edits(self.img))

    def grade(self, obs, chk) -> None:
        edits = lock_fault_edits(self.img)
        took = {f"0x{pc:08x}": len(self.retired_as(obs, pc, w)) for pc, w in edits.items()}
        unset = obs.line_t("FUSE_SECRETS_NOT_LOCKED")
        chk.ok(
            "FAULT-TOOK-EFFECT",
            all(took.values()) and unset is not None,
            replaced_retired=took,
            s26_not_locked_ps=unset if unset is not None else -1,
        )
        reset_t = self.last_reset_t(obs)
        stamps = {g: self.stamps_retired(obs, g, reset_t) for g in GATES}
        chk.ok("ALL-STAMPS", all(stamps.values()), **stamps)
        self.grade_halt(obs, chk, kind="eval", check="check_locks_first")
