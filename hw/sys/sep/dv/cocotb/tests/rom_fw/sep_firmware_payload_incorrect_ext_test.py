# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A randomly oversized EXT payload is refused; the backup boots.

The randomized half of the over-capacity pair. Its sibling
(``sep_firmware_payload_incorrect_ext_62kb_test``) pins the first whole KiB past
the capacity, which is the value a bound that is one KiB too loose would let
through; this member draws uniformly from 1 to 100 KiB past it, which is the
reference's own range, so the same refusal has to arrive from a whole family of
lengths rather than from the one value a bound off by a single KiB would admit.

THE CAPACITY IS THIS DESIGN'S, NOT THE REFERENCE'S. The reference randomizes from
its own 59.75 KiB usable EXT SRAM; here the base is the 252 KiB that
:func:`sep_payload_size_base.ext_payload_capacity` derives from
``OCH_SEP_TOP_SEP_SRAM_SIZE`` and the shipped ``payload_offset``. The
distribution, the mutated field and the failover are the reference's.

THE REFUSAL IS NOT THE REFERENCE'S TOKEN. The reference expects ``WARNING:
INVALID_ENCRYPTED_PAYLOAD_LENGTH``, which comes from its
``payload_hashed_length != payload_length`` arm on an ENCRYPTED payload rather
than from its capacity test; the fixed-value sibling's docstring sets out how that
happens. This port aims at the capacity decision the matrix row names and forbids
the hashed-length tokens.

WHY THE ORDER OF CHECKS IS NOT A LOOPHOLE. Every length in this range breaks more
than one of the ROM's bounds: the SRAM capacity, the flash slot span
(``boot_flash.h``), and the staging destination's own capacity. Only the first is
reached -- ``validate_manifest_header`` runs before the payload location and before
staging -- so requiring ``MANIFEST_ERR=0x00030007`` exactly, and forbidding
``PAYLOAD_LOC_OT_OOB``, ``PAYLOAD_NO_ROOM=`` and every other length token, is what
keeps the verdict attributable to the capacity decision whichever value the seed
drew.

The seed is the runner's, so a failing draw is reproducible with the run's own
``--seed``; the drawn value is logged as ``CHK-STIMULUS-PAYLOAD-SIZE``.
"""

from __future__ import annotations

import pyuvm

from env.sep_seeded_rng import SepSeededRng
from rom_fw import sep_payload_size_base as psb

_CAPACITY = psb.ext_payload_capacity(psb.shipped_payload_offset("primary"))
# The reference's range: capacity + 1..100 KiB.
_EXCESS_KIB_MIN = 1
_EXCESS_KIB_MAX = 100
_REQUIRED, _FORBIDDEN = psb.refused_markers(psb.shipped_payload_bytes("backup"))


@pyuvm.test()
class sep_firmware_payload_incorrect_ext_test(psb.PayloadSizeRefusedTest):
    """Randomly over-capacity EXT payload: primary refused, backup boots."""

    stage_in_smc = False
    required_markers = psb.PayloadSizeRefusedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeRefusedTest.forbidden_markers + _FORBIDDEN

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        excess_kib = SepSeededRng(self.random_seed()).randrange(
            _EXCESS_KIB_MIN, _EXCESS_KIB_MAX + 1)
        self.payload_bytes = _CAPACITY + excess_kib * 1024
        self.logger.info(
            "CHK-STIMULUS-RANDOM-SIZE: seed %d drew %d KiB past the %d-byte EXT "
            "capacity, so payload_length = %d (0x%x)",
            self.random_seed(), excess_kib, _CAPACITY, self.payload_bytes,
            self.payload_bytes,
        )
        return super().mutate_flash_image(buf)
