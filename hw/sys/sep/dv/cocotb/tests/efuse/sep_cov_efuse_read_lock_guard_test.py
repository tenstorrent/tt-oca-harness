# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The read-lock arm of the eFuse access guard.

``efuse_guard`` filters the fuse command against the sensed lock vector. Its
program-lock arm runs in ``sep_efuse_program_lock_matrix_test``; the
``is_reading_i && is_read_locked`` arm below it has never run, because no test
sets a read-lock bit and then issues a direct read of the locked field.

The stimulus programs the read-lock bit of one SPARE field, resenses so the
lock reaches the shadow vector the guard reads, and then issues an
``EFUSE_READ_CTRL`` read of a bit inside that spare. The sticky
``efuse_req_error`` flag is cleared afterwards so the channel is not left
starved.

A SPARE is used, never ``LC_STATE`` or a ``DIS`` field: a lock on one of those
would close the path this leaf itself needs.

Real fuse sense, LC TEST_DEV. The staged image pins the spare and both lock
words to zero, so the lock bit this test burns is the only one set. The
golden is updated with the programmed bit before the resense, because the
post-sense shadow compare in the bring-up path reads it.
"""

from __future__ import annotations

import pyuvm
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_TEST_DEV
from env.sep_locked_field_irq import spare_read_lock_bit
from sep_base_test import sep_base_test

from seq_lib.sep_cov_efuse_iface_seq import EFUSE_IFACE_STATUS, SepCovEfuseIface
from seq_lib.sep_efuse_program_lock_seq import field_bit_addr, spare_field_name
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_seq

_MAX_SENSE_CYCLES = 20_000

# One spare, and the bit inside it the locked read targets.
SPARE_IDX = 0
SPARE_FIELD = spare_field_name(SPARE_IDX)
READ_TARGET_BIT = 0

IMAGE_FIXED = {SPARE_FIELD: 0, "LOCKS": 0, "LOCKS_SPARE": 0}


@pyuvm.test()
class sep_cov_efuse_read_lock_guard_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        image: SepEfuseImage = self.select_efuse_image(lc_raw=LC_TEST_DEV, fixed=dict(IMAGE_FIXED))
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        efuse = SepCovEfuseIface(self)
        await efuse.clear_errors()

        # An unlocked read of the target first, so the same address is driven
        # through the guard on both sides of the lock.
        target = field_bit_addr(SPARE_FIELD, READ_TARGET_BIT)
        await efuse.read(target)
        await efuse.clear_errors()

        lock_bit = spare_read_lock_bit(SPARE_IDX)
        await self.start_seq(sep_efuse_otp_program_seq(lock_bit))
        # The bank keeps its programmed bits across reset, so the golden the
        # post-resense compare uses has to carry the same bit.
        golden = SepEfuseImage()
        golden.words = list(image.words)
        golden.words[lock_bit // 32] |= 1 << (lock_bit % 32)
        self.write_efuse_image(golden)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        self.logger.info(
            "[cov] %s read-lock burned at OTP bit %d and resensed", SPARE_FIELD, lock_bit
        )

        await efuse.clear_errors()
        await efuse.read(target)
        status = await efuse.rd(EFUSE_IFACE_STATUS)
        self.logger.info(
            "[cov] read of read-locked %s bit %d driven; interface status 0x%08x",
            SPARE_FIELD,
            READ_TARGET_BIT,
            status,
        )
        await efuse.clear_errors()
