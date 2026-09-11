# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP DEMOTE_1 consumer plus the SMC PVT-arm image.

Success parks in `sep_smu_lc_handoff_pass_loop` after DEMOTE_1 writes.
Bring-up, PVT_EN wait, or a non-PROD LC state parks in the fail loop.
"""

from __future__ import annotations

import os
import re

import cocotb

from seq_lib.sep_fw_common import load_syms
from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq

LC_HANDOFF_SMC_ENTRY = 0xC006_01B2
LC_HANDOFF_SMC_IMAGE_FIRST_WORD = 0x4101_4081
SMC_ENTRY_SYM = "smu_sep_lc_handoff_entry"


class SmuSepLcHandoffSeq(SepTerminalLoopSeq):
    NAME = "sep_lc_handoff"
    PASS_SYM = "sep_smu_lc_handoff_pass_loop"
    FAIL_SYMS = {"handoff": "sep_smu_lc_handoff_fail_loop"}
    SYM_DEFAULT = "sep_smu_lc_handoff.tcm.sym"

    def _check_smc_image_contract(self) -> None:
        sym_path = str(cocotb.plusargs.get("smc_sym", "smu_sep_lc_handoff.sram.sym"))
        syms = load_syms(sym_path)
        if not syms:
            self.log.warning("no SMC symbol table at %s -- entry reconciliation skipped", sym_path)
            return
        entry = next((a for a, n in syms if n == SMC_ENTRY_SYM), None)
        assert entry is not None, f"{SMC_ENTRY_SYM} not in the SMC image symbol table {sym_path}"
        assert entry == LC_HANDOFF_SMC_ENTRY, (
            f"SMC image entry 0x{entry:08x} != LC_HANDOFF_SMC_ENTRY 0x{LC_HANDOFF_SMC_ENTRY:08x}"
        )
        preload = str(cocotb.plusargs.get("smc_scratch_ram_hex", ""))
        if preload and os.path.exists(preload):
            with open(preload, "r", encoding="ascii", errors="replace") as stream:
                first = next(
                    (ln.strip() for ln in stream if ln.strip() and not ln.strip().startswith("@")),
                    "",
                )
            assert re.fullmatch(r"[0-9a-fA-F]+", first), f"unreadable first word in {preload!r}"
            got = int(first, 16) & 0xFFFF_FFFF
            assert got == LC_HANDOFF_SMC_IMAGE_FIRST_WORD, (
                f"SMC SRAM preload first word 0x{got:08x} != cookie "
                f"0x{LC_HANDOFF_SMC_IMAGE_FIRST_WORD:08x}"
            )

    async def run(self) -> None:
        self._check_smc_image_contract()
        await super().run()
