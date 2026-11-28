# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The first locus evaluation is forced true; the second halts with 0xF004.

The contract, stimulus and checks are in sep_rom_selfcheck_reverify_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_gate_ledger_base import CHECKS
from rom_fw.sep_rom_selfcheck_reverify_base import (
    force_true,
    manifest_addr_field,
    sep_rom_locus_flip_base,
)


@pyuvm.test()
class sep_rom_selfcheck_locus_first_eval_test(sep_rom_locus_flip_base):
    data_mask = 1 << 4
    breaks_addr = True
    halt_check = "check_locus_second"

    def target(self) -> int:
        return manifest_addr_field(self.img)

    def edits(self) -> dict[int, int]:
        return force_true(self.img, "check_locus_first")

    def extra_watch(self) -> set[int]:
        return set(self.edits())

    async def inject(self, obs) -> None:
        await super().inject(obs)
        await self.patch(self.edits())

    def grade(self, obs, chk) -> None:
        took = {f"0x{pc:08x}": len(self.retired_as(obs, pc, w)) for pc, w in self.edits().items()}
        chk.ok("FORCED-RETIRED", all(took.values()), replaced_retired=took)
        entries = {self.img.syms[n]: n for n in CHECKS}
        hits = [entries[r.pc] for r in obs.hits if r.pc in entries]
        chk.ok("FIRST-EVAL-FORCED", hits == list(CHECKS[:3]), checks_run=hits)
        super().grade(obs, chk)
