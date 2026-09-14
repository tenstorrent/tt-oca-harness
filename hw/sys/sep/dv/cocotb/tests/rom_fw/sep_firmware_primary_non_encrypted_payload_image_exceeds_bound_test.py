# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT TOC places image 0 inside the TOC region; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires every
image body to begin at or after ``prev_end``, seeded at the TOC region. Entry 0
declaring an offset below that region trips it, printing
``IMAGE_ORDER_BAD idx=0x00000000`` and returning ``MANIFEST_ERR_IMAGE_OVERLAP``
(0x0003000f). The primary's rejection returns into ``rom_manifest_boot``'s retry
loop, so the required outcome is a completed boot from the untouched backup.

THE PLANTED VALUE. ``primary.payload_images[0].offset = 240``. The bound is the TOC
region, whose size follows the image count: the shipped payload declares ONE image,
so the region is 248 bytes. 240 is the largest 8-byte-aligned offset still inside
it. Any offset at or above 248 is ACCEPTED. See
``sep_toc_bound_defect.BOUND_IMAGE_OFFSET``.

THE PAYLOAD IS NOT ENCRYPTED. This row loads ``secure_boot.bin``, whose slots both
carry ``encrypted_payload = 0``, and the base asserts that flag on the loaded image
before planting anything.

SECURE BOOT STAYS ON. Under LC=PROD, ``secure_boot_enabled()``
(``manifest_load.c``) enforces the chain regardless of the manifest flag: the base
requires the primary's ``RSA_VERIFY_START`` and ``SIG_VALID`` exactly once each and
before the rejection, which places the verdict in the payload arm rather than in
the crypto chain. Reaching the ``SBOOT_OFF`` branch would need a TEST_DEV/RMA fuse
image or the ``SBOOT_DIS`` chicken bit, and no row here uses either. That arm is not
covered; ``SBOOT_OFF`` and ``CRYPTO_FAIL=`` are both forbidden, so this row cannot
drift onto it.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the TOC-PAYLOAD-SIZE cell -- the token, ``IMAGE_ORDER_BAD idx=0x00000000``
    against ``TOC_PLEN_MISMATCH=``, each forbidding the other, and the error code,
    0x0003000f against 0x00030004. The two stimuli are mutually unreachable: that
    arm sits above the per-image loop and this row leaves the TOC's
    ``payload_length`` equal to the manifest's, so it cannot fire;
  * from the ENCRYPTED cell -- ``DECRYPT_START`` must NEVER appear, which is this
    row's positive evidence that it ran the plaintext arm;
  * from the BACKUP cell -- the rejection sits between the primary read and the
    backup read, the run ends in a completed boot, and the planted little-endian
    bytes are required at the PRIMARY slot's address (0x002028);
  * from ``sep_firmware_primary_non_encrypted_payload_images_out_of_order_test``,
    which lands on the SAME ``if`` -- the entry index, ``idx=0x00000000`` here
    against ``idx=0x00000001`` there, and that row's exact token is FORBIDDEN here.
    The two violate different halves of one rule: this row's body starts inside the
    TOC REGION, that row's inside the PREVIOUS IMAGE. The ROM does not report which
    half, and nothing here claims it does.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_primary_toc_bound_fail_base import sep_primary_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_payload_image_exceeds_bound_test(
        sep_primary_toc_bound_fail_base):
    """Plaintext primary TOC starts image 0 inside the TOC region -> backup boots."""

    bound_defect = tbd.BOUND
    encrypted = False
