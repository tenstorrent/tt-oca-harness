# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Warm dispatch to an accepted but non-bootable target: the ROM must fault cleanly.

Seeds an in-range handler address in zero-filled ICCM and checks the jump status, an
illegal-instruction trap with mepc at the seeded address, and the FAIL verdict.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_warm_dispatch_base import (
    COLD_POISON,
    RANGE_BASE,
    RANGE_END,
    STATUS_BOOTROM_START,
    STATUS_GENERAL_EXCEPTION,
    STATUS_WARM_HANG,
    STATUS_WARM_JUMP,
    VERDICT_FAIL,
    sep_warm_dispatch_base,
)

# In range but not sep_scratch_7_test's poke address, so a stale poke cannot pass this.
_BAD_TARGET = 0xC000_0200
# mcause for an illegal instruction (RISC-V privileged spec). An all-zero fetch.
_MCAUSE_ILLEGAL_INSN = 0x0000_0002


@pyuvm.test()
class sep_warm_reset_bad_target_exception_test(sep_warm_dispatch_base):
    """Accept an in-range handler whose target is not code; expect a clean trap."""

    seed = _BAD_TARGET
    max_run_cycles = 200_000
    progress_every = 25_000
    # Load nothing into ICCM: the point is that the target holds no instruction.
    stage_tcm = False

    async def run_scenario(self) -> None:
        assert RANGE_BASE <= _BAD_TARGET < RANGE_END, (
            f"0x{_BAD_TARGET:08x} is outside "
            f"[0x{RANGE_BASE:08x}, 0x{RANGE_END:08x}) -- the range check would "
            f"reject it and no jump would happen"
        )
        assert _BAD_TARGET % 4 == 0, (
            f"0x{_BAD_TARGET:08x} is not 4-byte aligned; the fault would then be "
            f"a misaligned fetch rather than the illegal instruction this test "
            f"is about"
        )

        console = await self.bring_up_to_dispatch()
        # The trap ends in a wfi spin with no stop status, so sample the whole window.
        obs = await self.sample_until(None)

        status_seq = obs["status_seq"]
        cold7_seq = obs["cold7_seq"]
        status_hex = [hex(v) for v in status_seq]
        cold7_hex = [hex(v) for v in cold7_seq]
        self.logger.info("ROM console: %s", console)

        assert obs["retired"], "core retired no instructions; the ROM never ran"

        assert _BAD_TARGET in cold7_seq, (
            f"cold_scratch[7] never held the seeded handler address "
            f"0x{_BAD_TARGET:08x}; observed {cold7_hex}"
        )
        self.logger.info("CHK-SEED: cold_scratch[7] held 0x%08x", _BAD_TARGET)

        assert STATUS_WARM_JUMP in status_seq, (
            f"cold_scratch[1] never held 0x{STATUS_WARM_JUMP:08x} "
            f"(SEP_MSG_WARM_RESET_JUMP): the ROM did not accept an in-range "
            f"handler. Observed {status_hex}"
        )
        assert STATUS_WARM_HANG not in status_seq, (
            f"cold_scratch[1] held 0x{STATUS_WARM_HANG:08x} "
            f"(SEP_MSG_WARM_RESET_HANG): the ROM rejected an IN-RANGE handler. "
            f"Observed {status_hex}"
        )
        self.logger.info("CHK-ACCEPT: cold_scratch[1] = 0x%08x", STATUS_WARM_JUMP)

        assert STATUS_GENERAL_EXCEPTION in status_seq, (
            f"cold_scratch[1] never held 0x{STATUS_GENERAL_EXCEPTION:08x} "
            f"(STATUS_ENCODE(ERROR, SEP_MSG_GENERAL_EXCEPTION)); observed "
            f"{status_hex}. The ROM jumped to a target holding no instruction "
            f"and did not fault cleanly"
        )
        assert status_seq.index(STATUS_WARM_JUMP) < \
            status_seq.index(STATUS_GENERAL_EXCEPTION), (
            f"GENERAL_EXCEPTION appears before WARM_RESET_JUMP in {status_hex}: "
            f"the fault happened before the dispatch, not because of it"
        )
        self.logger.info("CHK-EXCEPTION: 0x%08x after 0x%08x",
                         STATUS_GENERAL_EXCEPTION, STATUS_WARM_JUMP)

        # trap_vector_early writes status, mcause, mtval, mepc, status in that order.
        after_exc = status_seq[status_seq.index(STATUS_GENERAL_EXCEPTION):]
        assert _BAD_TARGET in after_exc, (
            f"cold_scratch[1] never carried mepc = 0x{_BAD_TARGET:08x} after the "
            f"exception status; observed {[hex(v) for v in after_exc]}. The trap "
            f"did not come from the seeded handler address"
        )
        self.logger.info("CHK-MEPC: cold_scratch[1] carried 0x%08x", _BAD_TARGET)

        assert _MCAUSE_ILLEGAL_INSN in after_exc, (
            f"cold_scratch[1] never carried mcause = {_MCAUSE_ILLEGAL_INSN} "
            f"(illegal instruction); observed {[hex(v) for v in after_exc]}"
        )
        self.logger.info("CHK-MCAUSE: illegal instruction (%d)",
                         _MCAUSE_ILLEGAL_INSN)

        verdict_seq = obs["verdict_seq"]
        assert VERDICT_FAIL in verdict_seq, (
            f"cold_scratch[0] never took 0x{VERDICT_FAIL:08x}; observed "
            f"{[hex(v) for v in verdict_seq]}. trap_vector_early writes it as its "
            f"last act, so its absence means the handler did not run to the end"
        )
        self.logger.info("CHK-VERDICT-FAIL: cold_scratch[0] = 0x%08x", VERDICT_FAIL)

        assert STATUS_BOOTROM_START not in status_seq, (
            f"cold_scratch[1] held 0x{STATUS_BOOTROM_START:08x} (BOOTROM_START): "
            f"the ROM cold booted rather than dispatching. Observed {status_hex}"
        )
        assert COLD_POISON not in cold7_seq, (
            f"cold_scratch[7] held cold_boot's poison 0x{COLD_POISON:08x} "
            f"({cold7_hex}): execution reached cold_boot"
        )
        self.logger.info("CHK-NO-COLD-FALLTHROUGH: no BOOTROM_START, no poison")
