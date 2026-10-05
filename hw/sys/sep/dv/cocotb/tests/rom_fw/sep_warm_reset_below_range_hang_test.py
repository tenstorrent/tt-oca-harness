# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Warm dispatch lower-bound reject: a handler address below the ICCM base must hang.

This is leg B of the warm dispatch in ``vector.S``. ``sep_warm_reset_invalid_hang_test``
drives only the upper bound. The seed is ``RANGE_BASE - 4``, the last word below
``WARM_HANDLER_ICCM_BASE``. It is also above ``WARM_HANDLER_SRAM_END``, so neither window
accepts it and the ROM must reach ``warm_reset_hang``. Both bound legs end at that label,
so ``CHK-SEED`` shows the register held an address below the ICCM base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_warm_dispatch_base import (
    COLD_POISON,
    RANGE_BASE,
    RANGE_END,
    STATUS_BOOTROM_START,
    STATUS_PRESTART_DONE,
    STATUS_WARM_HANG,
    STATUS_WARM_JUMP,
    sep_warm_dispatch_base,
)

# The largest address the lower bound rejects.
_BELOW_RANGE_HANDLER = RANGE_BASE - 4


@pyuvm.test()
class sep_warm_reset_below_range_hang_test(sep_warm_dispatch_base):
    """Seed a handler just below ICCM base; the ROM must hang, not jump."""

    seed = _BELOW_RANGE_HANDLER

    async def run_scenario(self) -> None:
        # Self-check the stimulus shape so a future edit cannot turn it into a
        # value that reaches the hang for a different reason.
        assert _BELOW_RANGE_HANDLER != 0, (
            "a zero handler is the beqz early-out to cold_boot, not the reject arm"
        )
        assert _BELOW_RANGE_HANDLER < RANGE_BASE, (
            f"0x{_BELOW_RANGE_HANDLER:08x} is not below the base "
            f"0x{RANGE_BASE:08x}; this test would then be driving some other leg"
        )
        assert _BELOW_RANGE_HANDLER == RANGE_BASE - 4, (
            f"0x{_BELOW_RANGE_HANDLER:08x} is not the boundary value; only "
            f"0x{RANGE_BASE - 4:08x} distinguishes the ROM's `bltu` from a "
            f"mistaken `bleu`, which would accept the last word below ICCM"
        )

        console = await self.bring_up_to_dispatch()
        obs = await self.sample_until(STATUS_WARM_HANG)
        quiesce = await self.observe_quiesce(STATUS_WARM_HANG)

        status_seq = obs["status_seq"]
        cold7_seq = obs["cold7_seq"]
        status_hex = [hex(v) for v in status_seq]
        cold7_hex = [hex(v) for v in cold7_seq]
        self.logger.info("ROM console: %s", console)

        assert obs["retired"], "core retired no instructions; the ROM never ran"

        # CHK-SEED: the deposit reached the register the ROM reads. Everything
        # below is vacuous without it.
        assert _BELOW_RANGE_HANDLER in cold7_seq, (
            f"cold_scratch[7] never held the seeded handler address "
            f"0x{_BELOW_RANGE_HANDLER:08x}; observed {cold7_hex}. The tb deposit "
            f"did not take, so this run says nothing about the lower bound"
        )
        self.logger.info("CHK-SEED: cold_scratch[7] held 0x%08x", _BELOW_RANGE_HANDLER)

        # CHK-WARM-REJECT-LOW: the lower bound rejected it and said so.
        assert obs["stopped"] and STATUS_WARM_HANG in status_seq, (
            f"cold_scratch[1] never reached 0x{STATUS_WARM_HANG:08x} "
            f"(STATUS_ENCODE(ERROR, SEP_MSG_WARM_RESET_HANG)); observed "
            f"{status_hex}"
        )
        self.logger.info("CHK-WARM-REJECT-LOW PASS: cold_scratch[1] = 0x%08x", STATUS_WARM_HANG)

        # CHK-NO-JUMP: the accept arm did not run. The ROM announces the jump in
        # cold_scratch[1] BEFORE transferring control, so its absence is what
        # rules out a jump below ICCM.
        assert STATUS_WARM_JUMP not in status_seq, (
            f"cold_scratch[1] held 0x{STATUS_WARM_JUMP:08x} "
            f"(SEP_MSG_WARM_RESET_JUMP): the ROM accepted a handler below ICCM "
            f"base and jumped to it. Observed {status_hex}"
        )
        self.logger.info("CHK-NO-JUMP: 0x%08x absent from cold_scratch[1]", STATUS_WARM_JUMP)

        # CHK-NO-COLD-FALLTHROUGH: it did not quietly fall into a normal boot.
        # The reject arm sits ABOVE cold_boot, so these words being absent places
        # execution on the hang; the missing -1 poison is the second witness,
        # written by a different instruction in a different block.
        for word, name in (
            (STATUS_BOOTROM_START, "BOOTROM_START"),
            (STATUS_PRESTART_DONE, "BOOTROM_PRESTART_DONE"),
        ):
            assert word not in status_seq, (
                f"cold_scratch[1] held 0x{word:08x} ({name}), which cold_boot "
                f"writes: the ROM fell through the dispatch into a normal boot. "
                f"Observed {status_hex}"
            )
        assert COLD_POISON not in cold7_seq, (
            f"cold_scratch[7] held cold_boot's poison 0x{COLD_POISON:08x} "
            f"({cold7_hex}): execution reached cold_boot"
        )
        self.logger.info(
            "CHK-NO-COLD-FALLTHROUGH: no cold_boot status word and no 0x%08x poison", COLD_POISON
        )

        # CHK-PRE-C: the dispatch stopped the ROM before the C runtime. The
        # virtual console is simputs(), and simputs() needs C.
        assert not console, (
            f"ROM printed {console}; the warm dispatch runs before the C runtime, "
            f"so any console output means execution continued into cold_boot"
        )
        self.logger.info("CHK-PRE-C: console silent, so the hang preceded C")

        self.assert_hung(quiesce, STATUS_WARM_HANG)

        # Belt and braces: the upper bound must not be what stopped this run.
        assert _BELOW_RANGE_HANDLER < RANGE_END, (
            "seed is also above RANGE_END; the upper bound could have produced "
            "this same verdict and the lower bound would still be unverified"
        )
