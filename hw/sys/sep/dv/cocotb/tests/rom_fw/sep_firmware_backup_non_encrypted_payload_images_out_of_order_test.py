# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT payload lists its images out of order; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires image
bodies to run in strictly ascending order, enforced as ``off < prev_end``. Entry 1
declaring an offset below entry 0's end trips it, printing
``IMAGE_ORDER_BAD idx=0x00000001`` and returning ``MANIFEST_ERR_IMAGE_OVERLAP``
(0x0003000f). With the primary already refused, the backup's rejection exhausts the
retry loop and the run ends terminal on ``MANIFEST_ALL_FAILED``.

THE PLANTED VALUES. Image 0 keeps the 0x1000 the shipped payload already gives its
SEP_BL1, and image 1 declares 0x500 -- below image 0's start. See
``sep_toc_entry_defect.SECOND_IMAGE_OFFSET``.

THE PAYLOAD IS NOT ENCRYPTED. This row loads ``secure_boot.bin``, whose slots both
carry ``encrypted_payload = 0``, and the base asserts that flag on the loaded image
before planting anything.

THE FAILOVER TRIGGER: the primary's manifest identifier is overwritten by
``sep_backup_manifest_fail_base.corrupt_primary``, producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work.

SECURE BOOT STAYS ON. Under LC=PROD, ``secure_boot_enabled()``
(``manifest_load.c``) enforces the chain regardless of the manifest flag: the base
requires the backup's ``RSA_VERIFY_START``, ``SIG_VALID``, ``PLD_HASH_OK`` and
``CRYPTO_VALIDATE_OK`` exactly once each and in order before the rejection, which is
what places the verdict in the payload arm rather than in the crypto chain. Reaching
the ``SBOOT_OFF`` branch would need a TEST_DEV/RMA fuse image or the ``SBOOT_DIS``
chicken bit, and no row here uses either. That arm is not covered; ``SBOOT_OFF``
and ``CRYPTO_FAIL=`` are both forbidden, so this row cannot drift onto it.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-SIZE cell -- the token, ``IMAGE_ORDER_BAD idx=0x00000001``
    against ``IMAGE_LEN_ALIGN idx=0x00000000``, with the sibling token FORBIDDEN,
    and the error code, 0x0003000f against 0x0003000e;
  * from the ENCRYPTED cell -- ``DECRYPT_START`` must NEVER appear;
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, the
    ``STATUS_ENCODE(ERROR, 0x000f)`` word, no boot-progress marker, and a quiescent
    ROM afterwards;
  * from all of them -- the device must be shown to have served the planted
    little-endian bytes at the BACKUP slot's entry 1 offset field.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_toc_entry_fail_base import sep_backup_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_payload_images_out_of_order_test(
        sep_backup_toc_entry_fail_base):
    """Plaintext backup TOC lists image 1 below image 0 -> both slots refused -> halt."""

    entry_defect = ted.ORDER
    encrypted = False
