# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The self-check loop ends early; the final tally halts with 0xF004.

The contract, stimulus and checks are in sep_rom_selfcheck_patch_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_gate_ledger_base import CHECKS, INSN_NOP, selfcheck_map
from rom_fw.sep_rom_selfcheck_patch_base import sep_rom_selfcheck_patch_base


@pyuvm.test()
class sep_rom_selfcheck_early_exit_test(sep_rom_selfcheck_patch_base):
    def edits(self) -> dict[int, int]:
        m = selfcheck_map(self.img)
        return {m.back_edge: INSN_NOP}

    def grade(self, obs, chk) -> None:
        m = selfcheck_map(self.img)
        self.grade_patched(obs, chk)
        compares = obs.at(m.counter_branch)
        passed = [
            r
            for r in compares
            if any(h.pc == m.counter_branch + 4 and h.t_ps > r.t_ps for h in obs.hits)
        ]
        chk.ok(
            "COMPLETED-ITERATIONS-PASSED",
            self.check_hits(obs) == [CHECKS[0]] and len(compares) == 1 and len(passed) == 1,
            checks_run=self.check_hits(obs),
            counter_compares=len(compares),
            counter_compares_passed=len(passed),
        )
        self.grade_halt(obs, chk, kind="tally")
