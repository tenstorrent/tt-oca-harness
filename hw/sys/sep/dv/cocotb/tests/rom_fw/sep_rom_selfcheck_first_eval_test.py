# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The first lock evaluation is forced true; the second halts with 0xF004.

The contract, stimulus and checks are in sep_rom_selfcheck_patch_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_gate_ledger_base import CHECKS
from rom_fw.sep_rom_selfcheck_patch_base import sep_rom_selfcheck_patch_base
from rom_fw.sep_rom_selfcheck_reverify_base import force_true, lock_fault_edits


@pyuvm.test()
class sep_rom_selfcheck_first_eval_test(sep_rom_selfcheck_patch_base):
    def edits(self) -> dict[int, int]:
        return lock_fault_edits(self.img) | force_true(self.img, "check_locks_first")

    def grade(self, obs, chk) -> None:
        self.grade_patched(obs, chk)
        unset = obs.line_t("FUSE_SECRETS_NOT_LOCKED")
        chk.ctrl("LOCKS-UNSET", unset is not None, s26_not_locked_ps=unset if unset else -1)
        chk.ok(
            "FIRST-EVAL-FORCED",
            self.check_hits(obs) == list(CHECKS),
            checks_run=self.check_hits(obs),
        )
        self.grade_halt(obs, chk, kind="eval", check="check_locks_second")
