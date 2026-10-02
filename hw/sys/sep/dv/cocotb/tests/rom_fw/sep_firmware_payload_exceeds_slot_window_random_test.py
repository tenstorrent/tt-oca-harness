# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A randomly oversized OCA payload is refused; the backup boots.

The seed draws 1 to 100 KiB past fixed SEP-SRAM staging capacity. Every draw also
ends past the slot window, so the ROM must report ``OCA_FAIL_PAYLOAD_LOCATION``
before the primary payload fetch.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from rom_fw import sep_payload_size_base as psb

_CAPACITY = psb.payload_staging_capacity()
_EXCESS_KIB_MIN = 1
_EXCESS_KIB_MAX = 100
_REQUIRED, _FORBIDDEN = psb.refused_markers(psb.shipped_payload_bytes("backup"))


@pyuvm.test()
class sep_firmware_payload_exceeds_slot_window_random_test(psb.PayloadSizeRefusedTest):
    """Randomly over-capacity OCA payload: primary refused, backup boots."""

    stage_in_smc = False
    required_markers = psb.PayloadSizeRefusedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeRefusedTest.forbidden_markers + _FORBIDDEN

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        excess_kib = SepSeededRng(self.random_seed()).randrange(
            _EXCESS_KIB_MIN, _EXCESS_KIB_MAX + 1
        )
        self.payload_bytes = _CAPACITY + excess_kib * 1024
        self.logger.info(
            "CHK-STIMULUS-RANDOM-SIZE: seed %d drew %d KiB past the %d-byte OCA "
            "SEP-SRAM staging capacity, so payload_length = %d (0x%x)",
            self.random_seed(),
            excess_kib,
            _CAPACITY,
            self.payload_bytes,
            self.payload_bytes,
        )
        return super().mutate_flash_image(buf)
