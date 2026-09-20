# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Program completion without the write-readback phase.

``efuse_interface_shim`` leaves ``StWriteWait`` two ways. With
``FUSE_COMMAND_PROGRAM_READ_BACK`` it enters the readback phase; with the plain
``FUSE_COMMAND_PROGRAM`` it completes the command in ``StWriteWait`` itself and
clears ``write_readback_phase_en``. ``sep_efuse_otp_program_seq`` always sets
``efuse_program_read_back``, so every program in the suite takes the first
exit and the second one has never run.

The stimulus programs one bit of an unlocked SPARE field with
``efuse_program_read_back`` clear, then a second bit with it set, so both exits
of the same state are driven in one leaf.

Real fuse sense, LC TEST_DEV: the program path is gated by the sensed LOCKS
image, so the fuse array has to be sensed for the command to reach the bank.
The image pins SPARE0 and the LOCKS pair to zero, so the field is unlocked and
starts from a known-blank value.
"""

from __future__ import annotations

import pyuvm
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_TEST_DEV
from sep_base_test import sep_base_test

from seq_lib.sep_cov_efuse_iface_seq import SepCovEfuseIface
from seq_lib.sep_efuse_program_lock_seq import field_bit_addr

_MAX_SENSE_CYCLES = 20_000

# Two distinct bits of one unlocked spare: the first takes the plain
# FUSE_COMMAND_PROGRAM exit, the second the readback exit.
SPARE_FIELD = "SPARE0"
NO_READBACK_BIT = 0
READBACK_BIT = 1

IMAGE_FIXED = {"SPARE0": 0, "LOCKS": 0, "LOCKS_SPARE": 0}


@pyuvm.test()
class sep_cov_efuse_program_no_readback_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        image: SepEfuseImage = self.select_efuse_image(lc_raw=LC_TEST_DEV, fixed=dict(IMAGE_FIXED))
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        efuse = SepCovEfuseIface(self)
        await efuse.clear_errors()

        no_rb = field_bit_addr(SPARE_FIELD, NO_READBACK_BIT)
        await efuse.program(no_rb, data=1, enable=True, read_back=False)
        await efuse.clear_errors()
        self.logger.info(
            "[cov] plain FUSE_COMMAND_PROGRAM driven on %s bit %d (OTP bit %d)",
            SPARE_FIELD,
            NO_READBACK_BIT,
            no_rb,
        )

        with_rb = field_bit_addr(SPARE_FIELD, READBACK_BIT)
        await efuse.program(with_rb, data=1, enable=True, read_back=True)
        await efuse.clear_errors()
        self.logger.info(
            "[cov] FUSE_COMMAND_PROGRAM_READ_BACK driven on %s bit %d (OTP bit %d); "
            "both StWriteWait exits taken",
            SPARE_FIELD,
            READBACK_BIT,
            with_rb,
        )
