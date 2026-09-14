# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT payload declares a bad TOC major version; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``toc->major_version == TOC_MAJOR_VERSION`` and returns
``MANIFEST_ERR_BAD_TOC_VERSION`` (0x00030006) otherwise. With the primary already
refused, the backup's rejection exhausts the retry loop and the run ends terminal.

THE PAYLOAD IS NOT ENCRYPTED. This row loads ``secure_boot.bin``, whose slots both
carry ``encrypted_payload = 0``, and the base asserts that flag on the loaded image
rather than trusting the filename.

THE FAILOVER TRIGGER: the primary's manifest identifier is overwritten by
``sep_backup_manifest_fail_base.corrupt_primary``, producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work.

THE PLANTED VALUE. ``TOC_MAJOR_VERSION + 1 = 2``. Any value other than
``TOC_MAJOR_VERSION`` reaches this arm; the choice of the adjacent one is argued in
``sep_toc_defect.BAD_TOC_VERSION``.

SECURE BOOT STAYS ON. Under LC=PROD, ``secure_boot_enabled()``
(``manifest_load.c``) enforces the chain regardless of the manifest flag, and
the base then requires the backup's ``RSA_VERIFY_START``, ``SIG_VALID``,
``PLD_HASH_OK`` and ``CRYPTO_VALIDATE_OK`` exactly once each and in order before
the rejection. That ordering is what places the verdict in the payload arm rather
than in the crypto chain; ``CRYPTO_FAIL=`` and ``SBOOT_OFF`` are forbidden.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-COUNT cell -- the error code, 0x00030006 against 0x00030010,
    with the sibling code FORBIDDEN;
  * from the ENCRYPTED cell -- ``DECRYPT_START`` must NEVER appear. The ROM calls
    ``decrypt_payload`` only for a slot whose ``encrypted_payload`` flag is set;
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, the
    ``STATUS_ENCODE(ERROR, 0x0006)`` word, no boot-progress marker, and a
    quiescent ROM afterwards;
  * from all of them -- the device must be shown to have served the planted
    little-endian bytes at the backup slot's field address.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_payload_toc_version_major_invalid_test(
        sep_backup_toc_fail_base):
    """Plaintext backup TOC major_version is 2 -> both slots refused -> halt."""

    toc_field = "version_major"
    encrypted = False
