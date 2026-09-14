# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload declares a bad TOC major version; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``toc->major_version == TOC_MAJOR_VERSION`` and returns
``MANIFEST_ERR_BAD_TOC_VERSION`` (0x00030006) otherwise. With the primary already
refused, the backup's rejection exhausts the retry loop and the run ends terminal
on ``MANIFEST_ALL_FAILED``.

THE FAILOVER TRIGGER: the primary's manifest identifier is overwritten by
``sep_backup_manifest_fail_base.corrupt_primary``, so the primary is refused with
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work and the trigger
cannot interact with the arm under test.

THE PLANTED VALUE. ``TOC_MAJOR_VERSION + 1 = 2``. Any value other than
``TOC_MAJOR_VERSION`` reaches this arm; the choice of the adjacent one is argued in
``sep_toc_defect.BAD_TOC_VERSION``.

THE BACKUP IS GENUINELY ENCRYPTED, from ``encrypted_boot.bin``, and the base
asserts that flag on the loaded image. The row's requirement is a TOC defect
reached through decryption, so a plaintext backup would make this testcase and its
non-encrypted sibling indistinguishable and one of the two would verify nothing.
The encrypted form is also the longer path: the slot must pass its signature, its
ciphertext payload hash and its decryption before the TOC is parsed at all.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-COUNT cell -- the error code, 0x00030006 against 0x00030010,
    with the sibling code FORBIDDEN;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly ONCE, ordered after the backup read and before its rejection.
    The plaintext cell forbids ``DECRYPT_START``. (Once, not twice: the primary
    dies on its magic word long before ``decrypt_payload``, which is what
    separates this family's count from the primary family's.);
  * from the PRIMARY cell -- the run is terminal. ``MANIFEST_ALL_FAILED`` and the
    ``STATUS_ENCODE(ERROR, ...)`` word are required, every boot-progress marker is
    forbidden, and the ROM must stay quiescent afterwards;
  * from all of them -- the device must be shown to have served this row's exact
    re-encrypted bytes at the backup slot's field address.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp and an AES
decryption, and AES is EDN client 0.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_payload_toc_version_major_invalid_test(
        sep_backup_toc_fail_base):
    """Encrypted backup TOC major_version is 2 -> both slots refused -> halt."""

    toc_field = "version_major"
    encrypted = True
