# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The self-check's iteration counter, final tally and second evaluation each halt their fault.

rom.adoc, Pre-Hand-off Self-Check (Gate Ledger), SEP-ROM-HOFF-050:

* "twice each over independently evaluated (optimizer-opaque) operands"
* "The checks are evaluated fail-fast (halt on the first false entry), an independent
  iteration counter is confirmed to equal `i+1` on every iteration, and a final tally
  re-confirms both counters equal the number of checks. Any shortfall or disagreement is
  fatal (`ROM_ERR_HANDOFF_SELFCHECK_FAILED`, `0xF004`)."

Each leaf replaces self-check instructions once DMA_INIT_OK ([S20], after the [S17]
self-hash) is on the console. The branches come from the structure of
rom_handoff_selfcheck: the indirect call through the check table and the branch on its
result, the store of the independent counter, the branch on the counter compare, the loop
back-edge and the tally compares after it.

* Iteration skip: the first instruction of the loop body jumps to the counter compare, so
  one iteration's evaluation and its counter increment are skipped while its compare runs.
* Early exit: the back-edge becomes a nop, so the loop ends after its first iteration.
* First evaluation: the [S25] lock write and the [S26] branch are replaced as in
  sep_rom_selfcheck_locks_unset_test, and check_locks_first returns true at once.

Checks: CHK-FAULT-TOOK-EFFECT, a leaf-specific trace check (CHK-SKIPPED-EVAL,
CHK-COMPLETED-ITERATIONS-PASSED or CHK-FIRST-EVAL-FORCED), and the halt contract with the halt
at the counter compare, at a tally compare, or at the second lock evaluation.
"""

from __future__ import annotations

import pyuvm
from env import sep_rv32_asm as asm
from rom_fw.sep_rom_gate_ledger_base import (
    AFTER_S17_LINE,
    CHECKS,
    INSN_NOP,
    jump,
    selfcheck_map,
    sep_rom_gate_ledger_base,
)
from rom_fw.sep_rom_selfcheck_reverify_test import lock_fault_edits

INSN_LI_A0_1 = asm.addi(asm.A0, asm.ZERO, 1)
INSN_RET = asm.jalr(asm.ZERO, asm.RA, 0)


class sep_rom_selfcheck_patch_base(sep_rom_gate_ledger_base):
    def edits(self) -> dict[int, int]:
        raise NotImplementedError

    def extra_watch(self) -> set[int]:
        return set(self.edits())

    async def inject(self, obs) -> None:
        await self.wait_line(obs, AFTER_S17_LINE)
        await self.patch(self.edits())

    def grade_patched(self, obs, chk) -> None:
        took = {f"0x{pc:08x}": len(self.retired_as(obs, pc, w)) for pc, w in self.edits().items()}
        chk.ok("FAULT-TOOK-EFFECT", all(took.values()), replaced_retired=took)

    def check_hits(self, obs) -> list[str]:
        entries = {self.img.syms[n]: n for n in CHECKS}
        return [entries[r.pc] for r in obs.hits if r.pc in entries]


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


@pyuvm.test()
class sep_rom_selfcheck_first_eval_test(sep_rom_selfcheck_patch_base):
    def edits(self) -> dict[int, int]:
        entry = self.img.syms["check_locks_first"]
        edits = lock_fault_edits(self.img)
        edits.update({entry: INSN_LI_A0_1, entry + 4: INSN_RET})
        return edits

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
