# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""ROM/BL1 terminal verdict, read from SEP cold_scratch[0].

The firmware reports its final outcome by writing one word to cold_scratch[0]:
``TEST_PASS_CODE`` or ``TEST_FAIL_CODE``. Those constants and that register are
the reference firmware's convention; see
``bootrom/prod/include/errors.h`` (``VERDICT_OUT``, ``rom_test_fail``),
``bootrom/prod/src/vector.S:663-665``, and
``dv/fw/tests/bl1_pass_test/bl1_pass_test.c``.

cold_scratch is a SEP-internal register, writable from the first instruction.
The mailbox at 0x8000_0000 sits behind the AXI outbound filter, which blocks by
default, so it cannot report a failure that happens before ``vector.S`` opens
it.

``tb_top.sv`` exports ``scratch_cold_probe_o [255:0]``, with cold_scratch[i] at
bits ``32*i +: 32``. ``sep_rom_console.py`` reads index 2 through the same bus.

``sep_base_test.verdict_source`` defaults to ``"mailbox"``: spi/km/cpu firmware
reports through the outbound mailbox. ROM and BL1 set ``"scratch0"``.
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
