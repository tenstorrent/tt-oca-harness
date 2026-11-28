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

from rom_fw.sep_rom_gate_ledger_base import AFTER_S17_LINE, CHECKS, sep_rom_gate_ledger_base


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
