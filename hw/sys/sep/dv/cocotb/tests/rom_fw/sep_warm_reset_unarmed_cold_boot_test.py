# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Warm dispatch unarmed: cold_scratch[7] == 0 must take the ``beqz`` early-out to cold boot.

This is leg A of the warm dispatch in ``vector.S`` (``beqz t1, cold_boot``). Other rom_fw
tests pass through this branch but do not assert on it. A cold boot is the default
outcome, so the evidence is ``cold_boot``'s ``-1`` poison of cold_scratch[7]: one
instruction on one path writes it. The absence of WARM_RESET_JUMP and WARM_RESET_HANG is
the second witness. The poison is -1, not 0, so a repeating watchdog with no handler fails
the range check instead of cold booting forever. CHK-POISON asserts the value.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_warm_dispatch_base import (
    COLD_POISON,
    STATUS_BOOTROM_START,
    STATUS_PRESTART_DONE,
    STATUS_WARM_HANG,
    STATUS_WARM_JUMP,
    sep_warm_dispatch_base,
)


@pyuvm.test()
class sep_warm_reset_unarmed_cold_boot_test(sep_warm_dispatch_base):
    """Leave cold_scratch[7] at its reset value; the ROM must cold boot."""

    # None means "must NOT be armed" -- the base asserts +sep_cold_scratch7 is
    # absent, because a deposit would silently move this run onto another leg.
    seed = None
    # The early-out and cold_boot's first stores are within the first few hundred
    # instructions; nothing here waits on a transport.
    max_run_cycles = 200_000
    progress_every = 25_000

    async def run_scenario(self) -> None:
        console = await self.bring_up_to_dispatch()
        obs = await self.sample_until(STATUS_PRESTART_DONE)

        status_seq = obs["status_seq"]
        cold7_seq = obs["cold7_seq"]
        status_hex = [hex(v) for v in status_seq]
        cold7_hex = [hex(v) for v in cold7_seq]
        self.logger.info("ROM console: %s", console)

        assert obs["retired"], "core retired no instructions; the ROM never ran"

        # CHK-UNARMED: the register really was 0 when the ROM read it. Without
        # this the run could have been driven by a stale deposit from elsewhere
        # and every check below would describe a different leg.
        assert cold7_seq and cold7_seq[0] == 0, (
            f"cold_scratch[7] did not start at 0; observed {cold7_hex}. The beqz "
            f"early-out is not what this run exercised"
        )
        self.logger.info("CHK-UNARMED: cold_scratch[7] read 0 at the dispatch")

        # CHK-POISON: cold_boot ran, and wrote the value the spec asks for. This
        # is the one word that places execution on the early-out.
        assert COLD_POISON in cold7_seq, (
            f"cold_scratch[7] never took cold_boot's 0x{COLD_POISON:08x} poison; "
            f"observed {cold7_hex}. Either the beqz did not reach cold_boot, or "
            f"cold_boot poisons with some other value -- writing 0 there would "
            f"make an unarmed warm reset indistinguishable from an armed one"
        )
        self.logger.info("CHK-POISON: cold_scratch[7] took 0x%08x", COLD_POISON)

        # CHK-COLD-PROGRESS: it went on to boot rather than stopping at the
        # dispatch. Two words from two different points in cold_boot.
        assert STATUS_BOOTROM_START in status_seq, (
            f"cold_scratch[1] never held 0x{STATUS_BOOTROM_START:08x} "
            f"(BOOTROM_START); observed {status_hex}"
        )
        assert obs["stopped"] and STATUS_PRESTART_DONE in status_seq, (
            f"cold_scratch[1] never reached 0x{STATUS_PRESTART_DONE:08x} "
            f"(BOOTROM_PRESTART_DONE) within {self.max_run_cycles} cycles; "
            f"observed {status_hex}"
        )
        self.logger.info("CHK-COLD-PROGRESS PASS: BOOTROM_START then PRESTART_DONE")

        # CHK-NO-WARM-DECISION: neither warm arm was taken. A ROM that jumped to
        # address 0, or that treated 0 as out-of-range and hung, would leave one
        # of these behind.
        assert STATUS_WARM_JUMP not in status_seq, (
            f"cold_scratch[1] held 0x{STATUS_WARM_JUMP:08x} "
            f"(SEP_MSG_WARM_RESET_JUMP): the ROM treated an unarmed slot as a "
            f"valid handler and jumped to address 0. Observed {status_hex}"
        )
        assert STATUS_WARM_HANG not in status_seq, (
            f"cold_scratch[1] held 0x{STATUS_WARM_HANG:08x} "
            f"(SEP_MSG_WARM_RESET_HANG): the ROM ran the zero slot into the range "
            f"check and hung instead of cold booting. Observed {status_hex}"
        )
        self.logger.info(
            "CHK-NO-WARM-DECISION: neither 0x%08x nor 0x%08x present",
            STATUS_WARM_JUMP,
            STATUS_WARM_HANG,
        )
