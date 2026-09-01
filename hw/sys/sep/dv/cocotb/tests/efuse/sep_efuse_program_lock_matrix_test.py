# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse program x write-lock matrix on a legal spare field.

RAND-REP. Every seed walks both cells on one SPARE0..SPARE7 field (never
LC_STATE):

  * unlocked: program a seed-selected bit, prove it in OTP and after resense
  * write-locked: program the spare's write-lock, resense, reject a second
    bit, prove OTP and the post-resense shadow match the independent golden
    (lock bit set, rejected bit still 0)

Real fuse sense. Clear-after-program on every program completion.
"""

from __future__ import annotations

import pyuvm
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_TEST_DEV
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

        spare_fixed = {f"SPARE{i}": 0 for i in range(8)}
        # t=0 OTP load is staged by cocotb/dv_sim_prestage.py with these kwargs.
        img = self.select_efuse_image(lc_raw=LC_TEST_DEV, fixed=spare_fixed)
        assert img.field_int(cfg.field) == 0
        assert img.field_int("LOCKS") == 0 and img.field_int("LOCKS_SPARE") == 0
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(img, fields=[cfg.field, "LOCKS_SPARE"]))

        golden = SepEfuseImage()
        golden.words = list(img.words)

        await self.start_seq(sep_efuse_otp_program_seq(cfg.program_addr))
        golden.words[cfg.program_addr // 32] |= 1 << (cfg.program_addr % 32)
        got = await self._direct_word(cfg.program_addr // 32)
        assert got == golden.words[cfg.program_addr // 32], (
            f"unlocked program: OTP word {cfg.program_addr // 32} = 0x{got:08x} "
            f"!= 0x{golden.words[cfg.program_addr // 32]:08x}"
        )
        self.write_efuse_image(golden)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(golden, fields=[cfg.field]))
        self.logger.info(
            "CHK-UNLOCK-PROGRAM PASS: %s bit %d programmed and read back (OTP + resense shadow)",
            cfg.field,
            cfg.program_bit,
        )

        await self.start_seq(sep_efuse_otp_program_seq(cfg.lock_bit))
        golden.words[cfg.lock_bit // 32] |= 1 << (cfg.lock_bit % 32)
        self.write_efuse_image(golden)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(golden, fields=["LOCKS_SPARE"]))

        locked = sep_efuse_otp_program_seq(cfg.reject_addr, expect_err=True)
        await self.start_seq(locked)
        assert locked.saw_err, "write-lock reject did not observe PROGRAM_ERR"
        got = await self._direct_word(cfg.reject_addr // 32)
        assert ((got >> (cfg.reject_addr % 32)) & 1) == 0, (
            f"write-locked {cfg.field} bit {cfg.reject_bit} burned (OTP word=0x{got:08x})"
        )
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(golden, fields=[cfg.field, "LOCKS_SPARE"]))
        self.logger.info(
            "CHK-LOCK-REJECT PASS: write-locked %s rejected bit %d; "
            "OTP and resense golden unchanged for that bit",
            cfg.field,
            cfg.reject_bit,
        )
        self.logger.info(
            "CHK-RAND-REP PASS: walked unlocked-program and write-lock-reject on %s", cfg.field
        )
