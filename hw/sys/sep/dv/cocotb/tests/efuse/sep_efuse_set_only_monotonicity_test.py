# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse set-only shadow OR-merge (anti-rollback monotonicity).

RANDCFG. Every seed walks seven metal ``WRITE_SET_ONLY`` fields
(``BL1_VERSION``, ``BL2_VERSION``, ``CHIPLET_PUBK_REVOKE``,
``REQUIRED_SIGNERS``, ``REQUIRED_ALGS``, ``SIP_DIS``, ``SYS_DIS``).
``SIP_DIS`` and ``SYS_DIS`` are the Class-1 members; the other five never
reach that OR-merge arm. That list is the field map, not the
``periphs.adoc`` column: ``REQUIRED_SIGNERS`` is SW-writable
there. Word index and bit patterns come from the run seed. The OR-merge
contract is directed: a sensed 1 survives a write of 0; a previously-0
bit sticks; a later write of 0 cannot clear it. Never ``LC_STATE``.
Program x lock is a different mechanism.

A WRITE_UNLOCK spare is the overwrite contrast so the OR is not a
global write path. Real fuse sense. ``SepEfuseSetOnlyCfg`` is the
single source of truth for the image pins and the checker goldens.
"""

from __future__ import annotations

import pyuvm
from env.sep_efuse_image import LC_TEST_DEV
from env.sep_efuse_set_only import CONTRAST_FIELD, SepEfuseSetOnlyCfg
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_set_only_seq import SepEfuseShadow
from seq_lib.sep_efuse_shadow_check_seq import sep_efuse_shadow_check_seq

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_efuse_set_only_monotonicity_test(sep_base_test):
    """Sensed ones survive write-0; new ones stick; spare overwrite still works."""

    async def _check_field(self, shadow: SepEfuseShadow, field) -> None:
        name, word = field.name, field.word_idx
        got = await shadow.read_word(name, word)
        assert got == field.sensed, (
            f"CHK-SENSE FAIL: {name}[{word}] = 0x{got:08x} want sensed 0x{field.sensed:08x}"
        )
        self.logger.info("CHK-SENSE PASS: %s[%d] sensed 0x%08x", name, word, got)

        await shadow.write_word(name, word, 0)
        got = await shadow.read_word(name, word)
        assert got == field.sensed, (
            f"CHK-CLEAR-REJECT FAIL: {name}[{word}] write-0 cleared "
            f"0x{field.sensed:08x} -> 0x{got:08x}"
        )
        self.logger.info("CHK-CLEAR-REJECT PASS: %s[%d] write-0 left 0x%08x", name, word, got)

        await shadow.write_word(name, word, field.set_bits)
        got = await shadow.read_word(name, word)
        assert got == field.after_set, (
            f"CHK-SET-STICKS FAIL: {name}[{word}] = 0x{got:08x} "
            f"want 0x{field.after_set:08x} "
            f"(sensed 0x{field.sensed:08x} | set 0x{field.set_bits:08x})"
        )
        self.logger.info(
            "CHK-SET-STICKS PASS: %s[%d] 0x%08x | 0x%08x = 0x%08x",
            name,
            word,
            field.sensed,
            field.set_bits,
            got,
        )

        await shadow.write_word(name, word, 0)
        got = await shadow.read_word(name, word)
        assert got == field.after_set, (
            f"CHK-OR-MERGE FAIL: {name}[{word}] write-0 cleared "
            f"0x{field.after_set:08x} -> 0x{got:08x}"
        )
        self.logger.info("CHK-OR-MERGE PASS: %s[%d] write-0 left OR 0x%08x", name, word, got)

    async def _check_writable_contrast(
        self,
        shadow: SepEfuseShadow,
        pattern: int,
    ) -> None:
        got = await shadow.read_word(CONTRAST_FIELD, 0)
        assert got == 0, f"CHK-WRITABLE-CONTRAST FAIL: {CONTRAST_FIELD} sensed 0x{got:08x}, want 0"
        await shadow.write_word(CONTRAST_FIELD, 0, pattern)
        got = await shadow.read_word(CONTRAST_FIELD, 0)
        assert got == pattern, (
            f"CHK-WRITABLE-CONTRAST FAIL: {CONTRAST_FIELD} write 0x{pattern:08x} read 0x{got:08x}"
        )
        await shadow.write_word(CONTRAST_FIELD, 0, 0)
        got = await shadow.read_word(CONTRAST_FIELD, 0)
        assert got == 0, f"CHK-WRITABLE-CONTRAST FAIL: {CONTRAST_FIELD} write-0 left 0x{got:08x}"
        self.logger.info(
            "CHK-WRITABLE-CONTRAST PASS: %s overwrite 0x%08x then 0", CONTRAST_FIELD, pattern
        )

    async def run_scenario(self) -> None:
        cfg = SepEfuseSetOnlyCfg(self.random_seed())
        self.logger.info("efuse set-only monotonicity: %s", cfg.summary())

        # t=0 OTP load is staged by cocotb/dv_sim_prestage.py via SepEfuseSetOnlyCfg.
        img = self.select_efuse_image(lc_raw=LC_TEST_DEV, fixed=cfg.image_fixed())
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(
            sep_efuse_shadow_check_seq(img, fields=[f.name for f in cfg.fields] + [CONTRAST_FIELD])
        )

        shadow = SepEfuseShadow(self)
        for field in cfg.fields:
            await self._check_field(shadow, field)
        await self._check_writable_contrast(shadow, cfg.spare_pattern)
        self.logger.info(
            "CHK-RANDCFG PASS: walked %d set-only fields; contrast=%s",
            len(cfg.fields),
            CONTRAST_FIELD,
        )
