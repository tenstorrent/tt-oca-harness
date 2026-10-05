# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each unlocked spare field programs, and each write-locked spare rejects a program.

RAND-REP. Every seed walks both cells on SPARE0..SPARE8 (never LC_STATE):

  * unlocked: program a seed-selected bit, prove it in OTP and after resense
  * write-locked: program the spare's write-lock, resense, reject a second
    bit, prove OTP and the post-resense shadow match the independent golden
    (lock bit set, rejected bit still 0)

Spares are walked in order, so a lock of spare k that also locks spare k+1
fails the next unlocked-program cell. The seed selects only the bit offsets
inside each spare.

Real fuse sense. The program sequence clears EFUSE_PROGRAM_CTRL after each
program completion.
"""

from __future__ import annotations

import pyuvm
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_TEST_DEV
from env.sep_locked_field_irq import spare_zero_pins
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_direct_read_seq import sep_efuse_direct_read_seq
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_seq
from seq_lib.sep_efuse_program_lock_seq import SepEfuseProgramLockCfg
from seq_lib.sep_efuse_shadow_check_seq import sep_efuse_shadow_check_seq

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_efuse_program_lock_matrix_test(sep_base_test):
    """Unlocked spare programs; write-locked spare rejects; resense matches golden."""

    async def _direct_word(self, word: int) -> int:
        rd = sep_efuse_direct_read_seq(word)
        await self.start_seq(rd)
        assert rd.rdata is not None
        return rd.rdata & 0xFFFF_FFFF

    async def run_scenario(self) -> None:
        cfg = SepEfuseProgramLockCfg(self.random_seed())
        self.logger.info("efuse program-lock matrix: %s", cfg.summary())

        # t=0 OTP load is staged by cocotb/dv_sim_prestage.py with these kwargs.
        img = self.select_efuse_image(lc_raw=LC_TEST_DEV, fixed=spare_zero_pins())
        for cell in cfg.cells:
            assert img.field_int(cell.field) == 0
        assert img.field_int("LOCKS") == 0 and img.field_int("LOCKS_SPARE") == 0
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(img, fields=cfg.fields + ["LOCKS_SPARE"]))

        golden = SepEfuseImage()
        golden.words = list(img.words)

        # Every spare, in order. Spare k+1 is programmed only after spare k has
        # been write-locked, so a lock bit that reaches past its own slot fails
        # the next iteration's unlocked-program cell rather than going unnoticed.
        for cell in cfg.cells:
            await self._walk_spare(cell, golden)

        self.logger.info(
            "CHK-SPARE-LOCK-SLOTS PASS: all %d spares programmed while unlocked and "
            "rejected once locked; a lock of spare k must not block spare k+1",
            len(cfg.cells),
        )

    async def _walk_spare(self, cell, golden: SepEfuseImage) -> None:
        """One spare: program unlocked, set its write-lock, prove the reject."""
        await self.start_seq(sep_efuse_otp_program_seq(cell.program_addr))
        golden.words[cell.program_addr // 32] |= 1 << (cell.program_addr % 32)
        got = await self._direct_word(cell.program_addr // 32)
        assert got == golden.words[cell.program_addr // 32], (
            f"unlocked program: OTP word {cell.program_addr // 32} = 0x{got:08x} "
            f"!= 0x{golden.words[cell.program_addr // 32]:08x}"
        )
        self.write_efuse_image(golden)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(golden, fields=[cell.field]))
        self.logger.info(
            "CHK-UNLOCK-PROGRAM PASS: %s bit %d programmed and read back (OTP + resense shadow)",
            cell.field,
            cell.program_bit,
        )

        await self.start_seq(sep_efuse_otp_program_seq(cell.lock_bit))
        # Read the lock bit straight out of OTP before the image is re-staged.
        # Every shadow compare below runs against an image this test wrote into
        # the fuse preload, so on its own it cannot separate a bit the DUT burned
        # from a bit the testbench placed. This one read is the lock bit's own
        # evidence, and it is taken from the device.
        lock_word = await self._direct_word(cell.lock_bit // 32)
        assert ((lock_word >> (cell.lock_bit % 32)) & 1) == 1, (
            f"{cell.field} write-lock bit {cell.lock_bit} did not burn in OTP "
            f"(word=0x{lock_word:08x}); the reject leg below would then be "
            "asserting about a lock that was never set"
        )
        golden.words[cell.lock_bit // 32] |= 1 << (cell.lock_bit % 32)
        self.write_efuse_image(golden)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(golden, fields=["LOCKS_SPARE"]))

        locked = sep_efuse_otp_program_seq(cell.reject_addr, expect_err=True)
        await self.start_seq(locked)
        assert locked.saw_err, "write-lock reject did not observe PROGRAM_ERR"
        got = await self._direct_word(cell.reject_addr // 32)
        assert ((got >> (cell.reject_addr % 32)) & 1) == 0, (
            f"write-locked {cell.field} bit {cell.reject_bit} burned (OTP word=0x{got:08x})"
        )
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(golden, fields=[cell.field, "LOCKS_SPARE"]))
        self.logger.info(
            "CHK-LOCK-REJECT PASS: write-locked %s rejected bit %d; "
            "OTP and resense golden unchanged for that bit",
            cell.field,
            cell.reject_bit,
        )
