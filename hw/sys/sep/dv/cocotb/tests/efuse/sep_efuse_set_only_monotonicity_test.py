# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse shadow write-policy sweep (anti-rollback monotonicity).

RANDCFG. Every seed walks every ``otp_fuse_controller.adoc`` fuse-field row except
``LC_STATE``. Set-only rows OR-merge; SW-writable rows overwrite.
``SIP_DIS`` and ``SYS_DIS`` stay on their function-group word. ``LOCK``
is both RDL windows (``LOCKS`` word 0, ``LOCKS`` word 1, ``LOCKS_SPARE``)
after the other rows, from a zero sense on assigned slots. The
lifecycle nibble stays with the LC W1S leaves. Word index and bit
patterns come from the run seed. Program x lock is a different
mechanism.

Real fuse sense. ``SepEfuseSetOnlyCfg`` is the single source of truth
for the image pins and the checker goldens.
"""

from __future__ import annotations

import pyuvm
from env.sep_efuse_image import LC_TEST_DEV
from env.sep_efuse_set_only import SepEfuseSetOnlyCfg
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_set_only_seq import SepEfuseShadow
from seq_lib.sep_efuse_shadow_check_seq import sep_efuse_shadow_check_seq

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_efuse_set_only_monotonicity_test(sep_base_test):
    """Sensed ones survive write-0; new ones stick; writable shadows overwrite."""

    async def _check_field(self, shadow: SepEfuseShadow, field) -> None:
        name, word = field.name, field.word_idx
        got = await shadow.read_word(name, word)
        assert got == field.sensed, (
            f"CHK-SENSE FAIL: {name}[{word}] = 0x{got:08x} want sensed 0x{field.sensed:08x}"
        )
        self.logger.info("CHK-SENSE PASS: %s[%d] sensed 0x%08x", name, word, got)

        if field.sensed:
            await shadow.write_word(name, word, field.drive_word(0))
            got = await shadow.read_word(name, word)
            assert got == field.sensed, (
                f"CHK-CLEAR-REJECT FAIL: {name}[{word}] write-0 cleared "
                f"0x{field.sensed:08x} -> 0x{got:08x}"
            )
            self.logger.info("CHK-CLEAR-REJECT PASS: %s[%d] write-0 left 0x%08x", name, word, got)

        await shadow.write_word(name, word, field.drive_word(field.set_bits))
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

        await shadow.write_word(name, word, field.drive_word(0))
        got = await shadow.read_word(name, word)
        assert got == field.after_set, (
            f"CHK-OR-MERGE FAIL: {name}[{word}] write-0 cleared "
            f"0x{field.after_set:08x} -> 0x{got:08x}"
        )
        self.logger.info("CHK-OR-MERGE PASS: %s[%d] write-0 left OR 0x%08x", name, word, got)

    async def _check_writable_contrast(self, shadow: SepEfuseShadow, field) -> None:
        name, word, pattern = field.name, field.word_idx, field.pattern
        got = await shadow.read_word(name, word)
        assert got == 0, f"CHK-WRITABLE-CONTRAST FAIL: {name}[{word}] sensed 0x{got:08x}, want 0"
        await shadow.write_word(name, word, pattern)
        got = await shadow.read_word(name, word)
        assert got == pattern, (
            f"CHK-WRITABLE-CONTRAST FAIL: {name}[{word}] write 0x{pattern:08x} read 0x{got:08x}"
        )
        await shadow.write_word(name, word, 0)
        got = await shadow.read_word(name, word)
        assert got == 0, f"CHK-WRITABLE-CONTRAST FAIL: {name}[{word}] write-0 left 0x{got:08x}"
        self.logger.info(
            "CHK-WRITABLE-CONTRAST PASS: %s[%d] overwrite 0x%08x then 0",
            name,
            word,
            pattern,
        )

    async def _collect(self, coro) -> None:
        try:
            await coro
        except AssertionError as exc:
            self.logger.error("%s", exc)
            self._failures.append(str(exc))

    async def run_scenario(self) -> None:
        self._failures: list[str] = []
        cfg = SepEfuseSetOnlyCfg(self.random_seed())
        self.logger.info("efuse set-only monotonicity: %s", cfg.summary())

        # t=0 OTP load is staged by cocotb/dv_sim_prestage.py via SepEfuseSetOnlyCfg.
        img = self.select_efuse_image(lc_raw=LC_TEST_DEV, fixed=cfg.image_fixed())
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        walked = list(
            dict.fromkeys(
                [f.name for f in cfg.fields]
                + [f.name for f in cfg.lock_fields]
                + [w.name for w in cfg.writable]
            )
        )
        await self.start_seq(sep_efuse_shadow_check_seq(img, fields=walked))

        shadow = SepEfuseShadow(self)
        for field in cfg.fields:
            await self._collect(self._check_field(shadow, field))
        for field in cfg.writable:
            await self._collect(self._check_writable_contrast(shadow, field))
        # Assigned lock bits write-lock the row they name, so both LOCK
        # windows run after every other shadow write in this invocation.
        for field in cfg.lock_fields:
            await self._collect(self._check_field(shadow, field))
        if self._failures:
            raise AssertionError(
                f"{len(self._failures)} eFuse write-policy check(s) failed: "
                + "; ".join(self._failures)
            )
        self.logger.info(
            "CHK-RANDCFG PASS: walked %d set-only fields, %d lock cells "
            "(LOCKS word 0, LOCKS word 1, LOCKS_SPARE) and %d writable fields",
            len(cfg.fields),
            len(cfg.lock_fields),
            len(cfg.writable),
        )
