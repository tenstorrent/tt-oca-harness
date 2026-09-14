# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload declares an out-of-range image count; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``0 < image_count <= 256`` and returns ``MANIFEST_ERR_TOC_COUNT`` (0x00030010)
otherwise. With the primary already refused, the backup's rejection exhausts the
retry loop and the run ends terminal on ``MANIFEST_ALL_FAILED``.

THE PAYLOAD IS GENUINELY ENCRYPTED. This row loads ``encrypted_boot.bin``, whose
slots both carry ``encrypted_payload = 1``; the mutator decrypts the backup
payload, writes the field, re-encrypts and re-seals.

THE FAILOVER TRIGGER: the primary's manifest identifier is overwritten by
``sep_backup_manifest_fail_base.corrupt_primary``, producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work.

THE PLANTED VALUE. 257 -- one past the ``n > 256`` bound. The ``image_count == 0``
half of the same arm is therefore not exercised by this row. See
``sep_toc_defect.BAD_IMAGE_COUNT``.
``TOC_REGION_OOB=``, the arm immediately after the count, is forbidden -- which
asserts rather than assumes that the count bound ran first.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the TOC-VERSION cell -- the error code, 0x00030010 against 0x00030006,
    with the sibling code FORBIDDEN;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly ONCE, ordered after the backup read and before its rejection;
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, the
    ``STATUS_ENCODE(ERROR, 0x0010)`` word, no boot-progress marker, and a
    quiescent ROM afterwards;
  * from all of them -- the device must be shown to have served this row's exact
    re-encrypted bytes at the backup slot's field address.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp and an AES
decryption, and AES is EDN client 0.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_invalid_payload_image_count_test(
        sep_backup_toc_fail_base):
    """Encrypted backup TOC image_count is 257 -> both slots refused -> halt."""

    toc_field = "image_count"
    encrypted = True
