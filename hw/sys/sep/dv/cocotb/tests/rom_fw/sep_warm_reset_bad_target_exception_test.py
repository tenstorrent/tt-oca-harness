# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Warm dispatch, ACCEPTED but NON-BOOTABLE target: the ROM must fault cleanly.

``sep_scratch_7_test`` covers the accept arm with a target that HOLDS a valid
instruction and keys off the retired PC. This covers the other case: the address
passes the range check and the target is not code, which is what a corrupted
handler slot looks like.

The trap lands in ``trap_vector_early``, not ``trap_vector``: ``_start`` points
``mtvec`` at the stack-free early handler, and the swap to the stack-using one
happens inside ``cold_boot``, which the warm path jumps away from first. That
handler writes status, ``mcause``, ``mtval``, ``mepc`` and status again into
cold_scratch[1], and the testbench samples that register every cycle, so this
test can require ``mepc == the seeded address`` -- proof that control reached
exactly the seeded handler rather than faulting on the way.

THE TARGET MUST HOLD NO INSTRUCTION, WHICH TAKES TWO THINGS. No
``+sep_iccm_word`` is passed, AND ``stage_tcm`` is off. The second is not
optional: ``sep_itcm.hex`` is the ROM's OWN .text, so pulsing ``tcm_load_i``
leaves a copy of the ROM in ICCM and the jump lands in the middle of real ROM
code, which faults for some other reason. With staging off, ICCM keeps its
default fill of 0 with valid ECC, an all-zero word is an illegal instruction in
RISC-V, and the fault is on the INSTRUCTION. The warm dispatch needs no TCM image
anyway: the ROM runs from Boot ROM and decides before DCCM is touched.
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

# In range, and not the address sep_scratch_7_test pokes an
# instruction into (0xC0000100), so a stale poke cannot make this run pass.
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
        # Self-check the stimulus: it must be ACCEPTED, or this test degenerates
        # into a second copy of the reject-arm tests.
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
        # No stop status: the trap is terminal (a wfi spin), so the whole window
        # is sampled and the sequence is complete by the end of it.
        obs = await self.sample_until(None)

        status_seq = obs["status_seq"]
        cold7_seq = obs["cold7_seq"]
        status_hex = [hex(v) for v in status_seq]
        cold7_hex = [hex(v) for v in cold7_seq]
        self.logger.info("ROM console: %s", console)

        assert obs["retired"], "core retired no instructions; the ROM never ran"

        # CHK-SEED: the deposit reached the register the ROM reads.
        assert _BAD_TARGET in cold7_seq, (
            f"cold_scratch[7] never held the seeded handler address "
            f"0x{_BAD_TARGET:08x}; observed {cold7_hex}"
        )
        self.logger.info("CHK-SEED: cold_scratch[7] held 0x%08x", _BAD_TARGET)

        # CHK-ACCEPT: the range check ACCEPTED it and announced the jump. This is
        # what separates this test from the two reject-arm ones.
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

        # CHK-EXCEPTION: the jump landed on a non-instruction and the early trap
        # handler reported it. Same status word the reference requires.
        assert STATUS_GENERAL_EXCEPTION in status_seq, (
            f"cold_scratch[1] never held 0x{STATUS_GENERAL_EXCEPTION:08x} "
            f"(STATUS_ENCODE(ERROR, SEP_MSG_GENERAL_EXCEPTION)); observed "
            f"{status_hex}. The ROM jumped to a target holding no instruction "
            f"and did not fault cleanly"
        )
        # Order matters: the announcement precedes the transfer of control, so a
        # GENERAL_EXCEPTION that arrived BEFORE the jump would be some earlier
        # fault wearing the same word.
        assert status_seq.index(STATUS_WARM_JUMP) < status_seq.index(STATUS_GENERAL_EXCEPTION), (
            f"GENERAL_EXCEPTION appears before WARM_RESET_JUMP in {status_hex}: "
            f"the fault happened before the dispatch, not because of it"
        )
        self.logger.info(
            "CHK-EXCEPTION: 0x%08x after 0x%08x", STATUS_GENERAL_EXCEPTION, STATUS_WARM_JUMP
        )

        # CHK-MEPC: control reached EXACTLY the seeded address. trap_vector_early
        # writes status, mcause, mtval, mepc, status -- so the seeded address must
        # appear in the sequence AFTER the exception status. This is the check the
        # reference's log-string match cannot make.
        after_exc = status_seq[status_seq.index(STATUS_GENERAL_EXCEPTION) :]
        assert _BAD_TARGET in after_exc, (
            f"cold_scratch[1] never carried mepc = 0x{_BAD_TARGET:08x} after the "
            f"exception status; observed {[hex(v) for v in after_exc]}. The trap "
            f"did not come from the seeded handler address"
        )
        self.logger.info("CHK-MEPC PASS: cold_scratch[1] carried 0x%08x", _BAD_TARGET)

        # CHK-MCAUSE: an illegal instruction, not an ECC or access fault. Keeps
        # the test pinned to "the target is not code" rather than to whatever
        # else could have gone wrong at that address.
        assert _MCAUSE_ILLEGAL_INSN in after_exc, (
            f"cold_scratch[1] never carried mcause = {_MCAUSE_ILLEGAL_INSN} "
            f"(illegal instruction); observed {[hex(v) for v in after_exc]}"
        )
        self.logger.info("CHK-MCAUSE: illegal instruction (%d)", _MCAUSE_ILLEGAL_INSN)

        # CHK-VERDICT-FAIL: trap_vector_early's terminal verdict. A fault that
        # reported a status but left the verdict channel untouched would look
        # like a hang to anything reading cold_scratch[0].
        verdict_seq = obs["verdict_seq"]
        assert VERDICT_FAIL in verdict_seq, (
            f"cold_scratch[0] never took 0x{VERDICT_FAIL:08x}; observed "
            f"{[hex(v) for v in verdict_seq]}. trap_vector_early writes it as its "
            f"last act, so its absence means the handler did not run to the end"
        )
        self.logger.info("CHK-VERDICT-FAIL: cold_scratch[0] = 0x%08x", VERDICT_FAIL)

        # CHK-NO-COLD-FALLTHROUGH: the ROM did not carry on into a normal boot
        # after the fault.
        assert STATUS_BOOTROM_START not in status_seq, (
            f"cold_scratch[1] held 0x{STATUS_BOOTROM_START:08x} (BOOTROM_START): "
            f"the ROM cold booted rather than dispatching. Observed {status_hex}"
        )
        assert COLD_POISON not in cold7_seq, (
            f"cold_scratch[7] held cold_boot's poison 0x{COLD_POISON:08x} "
            f"({cold7_hex}): execution reached cold_boot"
        )
        self.logger.info("CHK-NO-COLD-FALLTHROUGH: no BOOTROM_START, no poison")
