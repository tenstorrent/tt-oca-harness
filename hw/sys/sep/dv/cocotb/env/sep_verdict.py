# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""ROM/BL1 terminal verdict, read from SEP cold_scratch[0].

The firmware reports its final outcome by writing one word to cold_scratch[0]:
``TEST_PASS_CODE`` or ``TEST_FAIL_CODE``.  Those constants and that register are
the reference firmware's convention (``sep_common.h``), which this ROM
adopted -- see ``bootrom/prod/include/errors.h`` (``VERDICT_OUT``,
``rom_test_fail``), ``bootrom/prod/src/vector.S:663-665``, and
``dv/fw/tests/bl1_pass_test/bl1_pass_test.c``.

Why this channel and not the outbound mailbox the ROM used to write:
cold_scratch is a SEP-internal register, writable from the first instruction.
The mailbox at 0x8000_0000 sits behind the AXI outbound filter, which blocks by
default, so it does not work until ``vector.S`` opens it.  A verdict
channel that only works late cannot report an early failure.

Observation needs no new RTL: ``tb_top.sv`` already exports
``scratch_cold_probe_o [255:0]``, with cold_scratch[i] at bits ``32*i +: 32``
.  ``sep_rom_console.py`` reads index 2 through the same bus.

The outbound mailbox itself is untouched and still in use: the 19 spi/km/cpu
firmware tests report through it, and ``sep_base_test.verdict_source`` defaults
to ``"mailbox"`` for exactly that reason.  Only ROM and BL1 moved.

History: the migration ran in two phases, with the firmware writing BOTH
channels in phase 1 and a ``VerdictWatcher`` asserting they agreed -- 65 rom_fw
tests, 61 with both channels reporting, zero disagreements.  That watcher is
gone with phase 2; see dv/docs/rom_verdict_scratch0_migration.md.
"""

from __future__ import annotations

# Must equal bootrom/prod/include/errors.h TEST_PASS_CODE / TEST_FAIL_CODE and
# dv/fw/tests/bl1_pass_test/bl1_pass_test.c's copies of the same two names.
TEST_PASS_CODE = 0xACAFACA1
TEST_FAIL_CODE = 0xDEADBEEF

# cold_scratch[i] lives at bits 32*i of scratch_cold_probe_o; the verdict is i=0.
_SCRATCH0_SHIFT = 0
_WORD_MASK = 0xFFFF_FFFF


def decode_verdict(probe: int) -> tuple[bool, int] | None:
    """Decode cold_scratch[0] out of a ``scratch_cold_probe_o`` sample.

    Returns ``(done, passed)`` once the firmware has written a verdict word, or
    ``None`` while the register holds anything else.  Any other value means "no
    verdict yet", not "fail" -- the register comes out of reset at 0, and
    treating 0 as a verdict would make every test fail before it started.
    """
    word = (probe >> _SCRATCH0_SHIFT) & _WORD_MASK
    if word == TEST_PASS_CODE:
        return (True, 1)
    if word == TEST_FAIL_CODE:
        return (True, 0)
    return None
