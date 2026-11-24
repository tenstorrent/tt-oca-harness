# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One self-check iteration is skipped; its counter compare halts with 0xF004.

The contract, stimulus and checks are in sep_rom_selfcheck_patch_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_gate_ledger_base import jump, selfcheck_map
from rom_fw.sep_rom_selfcheck_patch_base import sep_rom_selfcheck_patch_base


@pyuvm.test()
class sep_rom_selfcheck_iter_skip_test(sep_rom_selfcheck_patch_base):
    def edits(self) -> dict[int, int]:
        m = selfcheck_map(self.img)
        return {m.loop_top: jump(m.loop_top, m.compare_start)}

    def grade(self, obs, chk) -> None:
        m = selfcheck_map(self.img)
        self.grade_patched(obs, chk)
        top = self.retired_as(obs, m.loop_top, jump(m.loop_top, m.compare_start))
        after = [r.pc for r in obs.hits if top and r.t_ps > top[0].t_ps][:1]
        chk.ok(
            "SKIPPED-EVAL",
            after == [m.compare_start]
            and not self.check_hits(obs)
            and not obs.at(m.eval_call)
            and not obs.at(m.seen_store)
            and not any(obs.at(p) for p in m.tally_branches),
            next_after_jump=[f"0x{p:08x}" for p in after],
            checks_run=self.check_hits(obs),
            eval_calls=len(obs.at(m.eval_call)),
            counter_stores=len(obs.at(m.seen_store)),
        )
        self.grade_halt(obs, chk, kind="counter")
