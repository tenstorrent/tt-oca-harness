# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Set-only eFuse shadow fields OR-merge and never clear; SW-writable fields overwrite.

RANDCFG. Every seed walks every fuse-field row of
``hw/sys/sep/doc/otp_fuse_controller.adoc`` except ``LC_STATE``. Set-only rows
OR-merge and SW-writable rows overwrite. ``SIP_DIS`` and ``SYS_DIS`` stay on
their function-group word. The ``LOCK`` row covers three RDL windows (``LOCKS``
word 0, ``LOCKS`` word 1, ``LOCKS_SPARE``) and runs after the other rows, from a
zero sense on the assigned slots. The seed selects the word index and bit
patterns. The LC_STATE nibble is graded by
lcc/sep_lcc_lc_state_transition_matrix_test, and program x lock by
efuse/sep_efuse_program_lock_matrix_test.

Real fuse sense. ``SepEfuseSetOnlyCfg`` is the single source of truth
for the image pins and the checker goldens.

Write responses. No text states the bus response of a write to a set-only
shadow row, so the set-only rows log it: ``OBS-SETONLY-CLEAR-RESP`` for each
write-0 and ``OBS-SETONLY-SET-RESP`` for each set-1 write, and no check reads
either record. A write that gets no B response fails the leaf at the bus
timeout of the access. The ``LOCK`` cells and the writable rows keep the OKAY
grade of the register driver.
"""

from __future__ import annotations

import pyuvm
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import LC_TEST_DEV
from env.sep_efuse_set_only import SepEfuseSetOnlyCfg
from env.sep_efuse_test_lib import SepEfuseFd
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_set_only_seq import SepEfuseShadow
from seq_lib.sep_efuse_shadow_check_seq import sep_efuse_shadow_check_seq

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_efuse_set_only_monotonicity_test(sep_base_test):
    """Sensed ones survive write-0; new ones stick; writable shadows overwrite."""

    async def _write(self, shadow: SepEfuseShadow, field, data: int, *, set_only: bool) -> int:
        """One shadow write: the response code of a set-only row, else 0 after an OKAY."""
        name, word = field.name, field.word_idx
        if set_only:
            return await self.fd.wr_graded_by_readback(shadow._addr(name, word), data)
        await shadow.write_word(name, word, data)
        return 0

    def _obs_clear(self, shadow: SepEfuseShadow, field, before: int, code: int, after: int) -> None:
        name, word = field.name, field.word_idx
        self.chk.obs(
            "SETONLY-CLEAR-RESP",
            field=name,
            word=word,
            addr=f"0x{shadow._addr(name, word):08x}",
            before=f"0x{before:08x}",
            wdata=f"0x{field.drive_word(0):08x}",
            resp=code,
            after=f"0x{after:08x}",
        )

    async def _check_field(self, shadow: SepEfuseShadow, field, *, set_only: bool) -> None:
        name, word = field.name, field.word_idx
        got = await shadow.read_word(name, word)
        assert got == field.sensed, (
            f"CHK-SENSE FAIL: {name}[{word}] = 0x{got:08x} want sensed 0x{field.sensed:08x}"
        )
        self.logger.info("CHK-SENSE PASS: %s[%d] sensed 0x%08x", name, word, got)

        if field.sensed:
            before = got
            code = await self._write(shadow, field, field.drive_word(0), set_only=set_only)
            got = await shadow.read_word(name, word)
            if set_only:
                self._obs_clear(shadow, field, before, code, got)
            assert got == field.sensed, (
                f"CHK-CLEAR-REJECT FAIL: {name}[{word}] write-0 cleared "
                f"0x{field.sensed:08x} -> 0x{got:08x}"
            )
            self.logger.info("CHK-CLEAR-REJECT PASS: %s[%d] write-0 left 0x%08x", name, word, got)

        wdata = field.drive_word(field.set_bits)
        code = await self._write(shadow, field, wdata, set_only=set_only)
        got = await shadow.read_word(name, word)
        if set_only:
            self.chk.obs(
                "SETONLY-SET-RESP",
                field=name,
                word=word,
                addr=f"0x{shadow._addr(name, word):08x}",
                wdata=f"0x{wdata:08x}",
                set_resp=code,
            )
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

        before = got
        code = await self._write(shadow, field, field.drive_word(0), set_only=set_only)
        got = await shadow.read_word(name, word)
        if set_only:
            self._obs_clear(shadow, field, before, code, got)
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
        seed = self.random_seed()
        self.chk = SepChkLog(self, "sep_efuse_set_only_monotonicity_test", seed)
        self.fd = SepEfuseFd(self)
        cfg = SepEfuseSetOnlyCfg(seed)
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
        # The sequence reads SEP_FUSE_SENSE_STATUS, then every word of each walked row.
        reads = 1 + sum(len(img.expected_field(name)) for name in walked)
        mark = self.sb_mark()
        await self.start_seq(sep_efuse_shadow_check_seq(img, fields=walked))
        self.assert_sb_judged(mark, "CHK-SENSE-WALK")
        judged = self.env.scoreboard.value_checks - mark[1]
        assert judged == reads, f"CHK-SENSE-WALK FAIL: scoreboard judged {judged} of {reads} reads"
        self.logger.info(
            "CHK-SENSE-WALK PASS: rows=%d judged=%d/%d reads", len(walked), judged, reads
        )

        shadow = SepEfuseShadow(self)
        for field in cfg.fields:
            await self._collect(self._check_field(shadow, field, set_only=True))
        for field in cfg.writable:
            await self._collect(self._check_writable_contrast(shadow, field))
        # Assigned lock bits write-lock the row they name, so both LOCK
        # windows run after every other shadow write in this invocation.
        for field in cfg.lock_fields:
            await self._collect(self._check_field(shadow, field, set_only=False))
        self.chk.ok(
            "RANDCFG",
            not self._failures,
            set_only=len(cfg.fields),
            lock_cells=len(cfg.lock_fields),
            writable=len(cfg.writable),
            failures=len(self._failures),
        )
        self.chk.finish()
