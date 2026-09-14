# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT payload declares an out-of-range image count; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``0 < image_count <= 256`` and returns ``MANIFEST_ERR_TOC_COUNT`` (0x00030010)
otherwise. With the primary already refused, the backup's rejection exhausts the
retry loop and the run ends terminal on ``MANIFEST_ALL_FAILED``.

THE PAYLOAD IS NOT ENCRYPTED. This row loads ``secure_boot.bin``, whose slots both
carry ``encrypted_payload = 0``, and the base asserts that flag on the loaded
image.

THE FAILOVER TRIGGER: the primary's manifest identifier is overwritten by
``sep_backup_manifest_fail_base.corrupt_primary``, producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work.

THE PLANTED VALUE. 257 -- one past the ``n > 256`` bound. The ``image_count == 0``
half of the same arm is therefore not exercised by this row. See
``sep_toc_defect.BAD_IMAGE_COUNT``.
``TOC_REGION_OOB=``, the arm immediately after the count, is forbidden.

SECURE BOOT STAYS ON. Under LC=PROD, ``secure_boot_enabled()``
(``manifest_load.c``) enforces the chain regardless of the manifest flag: the base
requires the backup's ``RSA_VERIFY_START``, ``SIG_VALID``, ``PLD_HASH_OK`` and
``CRYPTO_VALIDATE_OK`` exactly once each and in order before the rejection, which
is what places the verdict in the payload arm
rather than in the crypto chain. Reproducing ``secure_boot: 0`` here would change
NOTHING -- at PROD the manifest flag is never consulted -- so reaching the
``SBOOT_OFF`` branch at all would need a TEST_DEV/RMA fuse image or the
``SBOOT_DIS`` chicken bit, and no row in this batch uses either. That arm of
``validate_manifest_payload`` is therefore not covered here; ``SBOOT_OFF`` and
``CRYPTO_FAIL=`` are both forbidden, so this row can never drift onto it.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the TOC-VERSION cell -- the error code, 0x00030010 against 0x00030006,
    with the sibling code FORBIDDEN;
  * from the ENCRYPTED cell -- ``DECRYPT_START`` must NEVER appear;
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, the
    ``STATUS_ENCODE(ERROR, 0x0010)`` word, no boot-progress marker, and a
    quiescent ROM afterwards;
  * from all of them -- the device must be shown to have served the planted
    little-endian bytes at the backup slot's field address.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_invalid_payload_image_count_test(
        sep_backup_toc_fail_base):
    """Plaintext backup TOC image_count is 257 -> both slots refused -> halt."""

    toc_field = "image_count"
    encrypted = False
