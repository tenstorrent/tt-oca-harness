# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED payload declares an out-of-range image count; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``0 < image_count <= 256`` and returns ``MANIFEST_ERR_TOC_COUNT`` (0x00030010)
otherwise. The primary's rejection returns into ``rom_manifest_boot``'s retry
loop, so the required outcome is a completed boot from the untouched backup.

THE PAYLOAD IS GENUINELY ENCRYPTED. This row loads ``encrypted_boot.bin``, whose
slots both carry ``encrypted_payload = 1``; the mutator decrypts the payload,
writes the field, re-encrypts and re-seals. The ROM parses the TOC only after
``decrypt_payload``, so this is the only form of the stimulus that reaches the
count check.

THE PLANTED VALUE. 257 -- one past the ``n > 256`` bound. THE ``image_count == 0`` HALF
OF THAT ARM IS THEREFORE NOT EXERCISED BY THIS ROW -- the reasoning is in
``sep_toc_defect.BAD_IMAGE_COUNT``.

WHY 257 CANNOT DRIFT INTO THE NEXT CHECK. ``TOC_REGION_OOB=`` is the arm
immediately after the count and would fire for a count whose TOC region exceeds
the payload -- which 257 certainly would, at 32 + 257*216 bytes. The count bound
runs FIRST, so the region arm must not be reached; ``TOC_REGION_OOB=`` is
forbidden here, which turns that ordering into an assertion instead of an
assumption.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the TOC-VERSION cell -- the error code, 0x00030010 against 0x00030006,
    with the sibling code FORBIDDEN;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly TWICE, with the primary's pair inside its own attempt;
  * from the BACKUP cell -- the rejection sits between the primary read and the
    backup read, and the run ends in a completed boot;
  * from all of them -- the device must be shown to have served this row's exact
    re-encrypted bytes at this row's field address.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps and two AES decryptions.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_invalid_payload_image_count_test(
        sep_primary_toc_fail_base):
    """Encrypted primary TOC image_count is 257 -> refused -> the backup boots."""

    toc_field = "image_count"
    encrypted = True
