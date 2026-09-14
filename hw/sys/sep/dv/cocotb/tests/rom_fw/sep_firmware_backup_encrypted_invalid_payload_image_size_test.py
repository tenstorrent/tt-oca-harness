# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload declares a misaligned image length; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires every
image length to be 4-byte aligned, enforced as ``(len & 3u) != 0``. A length of
0x72D trips it, printing ``IMAGE_LEN_ALIGN idx=0x00000000`` and returning
``MANIFEST_ERR_IMAGE_OOB`` (0x0003000e). With the primary already refused, the
backup's rejection exhausts the retry loop and the run ends terminal on
``MANIFEST_ALL_FAILED``.

THE ERROR CODE ALONE PROVES NOTHING HERE, which is why the token is required. The
SILENT ``end > p_len`` bounds arm sits immediately above the alignment arm in the
same entry and returns exactly the same ``MANIFEST_ERR_IMAGE_OOB``. Only
``IMAGE_LEN_ALIGN idx=`` distinguishes them, and only this arm prints it.

THE PLANTED VALUE. 0x72D, which is 1 modulo 4 and so violates ``(len & 3u) != 0``.
It is the largest such value that still ends inside the payload on both shipped
images: the single image sits at 0x1000 in 5936 plaintext bytes, and a length that
overruns would be refused by the SILENT bounds arm, which returns this row's error
code from a different check. Residues 2 and 3 are unexercised; the full reasoning
is in ``sep_toc_entry_defect.BAD_IMAGE_LENGTH``.

THE PAYLOAD IS GENUINELY ENCRYPTED. This row loads ``encrypted_boot.bin``, whose
slots both carry ``encrypted_payload = 1``, and the base asserts that flag on the
loaded image.

THE FAILOVER TRIGGER: the primary's manifest identifier is overwritten by
``sep_backup_manifest_fail_base.corrupt_primary``, producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work.

THE IMAGE STILL HASHES CORRECTLY. ``pm.set_toc_entry_length`` recomputes the entry's
digest over the newly declared range, so alignment is the ONLY rule this payload
violates and ``IMAGE_HASH_MISMATCH`` is forbidden rather than tolerated.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-ORDER cell -- the token, ``IMAGE_LEN_ALIGN idx=0x00000000``
    against ``IMAGE_ORDER_BAD idx=0x00000001``, with the sibling token FORBIDDEN,
    and the error code, 0x0003000e against 0x0003000f;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly ONCE, the backup's, and before the rejection;
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, the
    ``STATUS_ENCODE(ERROR, 0x000e)`` word, no boot-progress marker, and a quiescent
    ROM afterwards;
  * from all of them -- the device must be shown to have served this row's exact
    re-encrypted bytes at the BACKUP slot's entry 0 length field.

Needs ``+sep_crypto_edn_force``: an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_toc_entry_fail_base import sep_backup_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_invalid_payload_image_size_test(
        sep_backup_toc_entry_fail_base):
    """Encrypted backup TOC image 0 length is 0x72D -> both slots refused -> halt."""

    entry_defect = ted.SIZE
    encrypted = True
