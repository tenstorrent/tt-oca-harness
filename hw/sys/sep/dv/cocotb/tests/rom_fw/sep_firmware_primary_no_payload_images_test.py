# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary's payload declares no images at all; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``0 < image_count <= 256`` and returns ``MANIFEST_ERR_TOC_COUNT`` (0x00030010)
otherwise. This row plants the ZERO half -- an empty image list -- which no other
row in this repository exercises; ``sep_toc_defect.BAD_IMAGE_COUNT`` records that
gap in writing. The rejection returns into ``rom_manifest_boot``'s retry loop, so
the required outcome is a completed boot from the untouched backup.

WHAT AN EMPTY LIST REACHES. The per-image loop does not run, so no image type,
bound, ordering or digest is examined and ``bl1_found`` stays false. That alone
would not let the payload through -- the ``if (!bl1_found)`` arm after the loop
refuses it anyway with ``MANIFEST_ERR_NO_BL1_IMAGE``. What this row establishes is
WHICH arm refuses it and HOW EARLY, so both neighbours are forbidden:
``TOC_REGION_OOB=`` / 0x00030007 immediately after the count, and ``NO_BL1_IMAGE``
/ 0x00030008 at the end of the loop.

THE REFERENCE'S TOKEN IS NOT THIS DESIGN'S ARM. The reference expects
``WARNING: INVALID_PAYLOAD_LENGTH`` because its header validation carries a rule
this design does not -- ``payload_length <= sizeof(toc_header) +
sizeof(toc_entry)``, "must include the TOC and at least one image" -- and its
empty-list artefact packs a payload short enough to land there. This ROM has no
such rule: its only MINIMUM-size rule on ``payload_length`` is ``p_len == 0``,
which a payload holding a TOC header satisfies, so the empty list reaches the count
bound instead. Requiring the reference's token would aim this row at a
truncated-payload rule rather than at the empty list it is named for, so the count
code is required and every neighbouring structural code -- ``BAD_LENGTH`` included
-- is forbidden.

SECURE BOOT STAYS ON. Under LC=PROD, ``secure_boot_enabled()`` enforces the chain
regardless of the manifest flag, and the base requires the primary's own
``RSA_VERIFY_START`` and ``SIG_VALID`` inside its attempt and ahead of its error --
positive evidence that the count rejection is downstream of a verified signature
rather than an early structural refusal wearing the right code. ``SBOOT_OFF`` is
forbidden.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the four ``*_invalid_payload_image_count_test`` cells -- the planted value,
    0 against 257. Their consoles are otherwise identical, so the device must be
    shown to have served eight ZERO bytes at the primary's ``image_count``;
  * from the TOC-version cells -- the error code, with theirs forbidden;
  * from the ENCRYPTED stimulus -- ``DECRYPT_START`` must never appear;
  * from the BACKUP and PRIMARY_AND_BACKUP rows -- the run ends in a completed
    boot, and ``MANIFEST_ALL_FAILED`` is forbidden.

Needs ``+sep_crypto_edn_force``: both slots run a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_no_payload_images_base import sep_no_payload_images_primary_base


@pyuvm.test()
class sep_firmware_primary_no_payload_images_test(sep_no_payload_images_primary_base):
    """Plaintext primary TOC image_count is 0 -> refused -> the backup boots."""
