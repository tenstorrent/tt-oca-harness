# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED payload declares a bad TOC major version; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``toc->major_version == TOC_MAJOR_VERSION`` and returns
``MANIFEST_ERR_BAD_TOC_VERSION`` (0x00030006) otherwise. A primary-side rejection
returns into ``rom_manifest_boot``'s retry loop, so the required outcome is a
completed boot from the untouched backup rather than a halt.

THE PAYLOAD IS GENUINELY ENCRYPTED, AND THE DEFECT IS PLANTED IN THE PLAINTEXT.
This row loads ``encrypted_boot.bin``, whose slots both carry
``encrypted_payload = 1``; the mutator decrypts the payload, writes the field,
re-encrypts and re-seals (``env/sep_payload_mutate.set_toc_version_major``).
Planting it in the ciphertext directly would not reach this check at all -- the ROM
validates the TOC only after ``decrypt_payload``, so a corrupted ciphertext produces
``MANIFEST_ERR_BAD_TOC_ID`` one arm earlier, which is a different testcase
(``sep_decryption_failure_terminal_test``).

THE PLANTED VALUE. ``TOC_MAJOR_VERSION + 1 = 2``. Any value other than
``TOC_MAJOR_VERSION`` reaches this arm; the choice of the adjacent one is argued in
``sep_toc_defect.BAD_TOC_VERSION``.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR. The arm prints no console token, so
the discrimination is stated rather than assumed:

  * from the IMAGE-COUNT cell -- the error code, 0x00030006 against 0x00030010.
    The sibling code is FORBIDDEN here, so this row cannot pass on it;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly TWICE (the mutated primary's and the recovering backup's), and
    the primary's pair must sit between its slot read and its rejection. The
    plaintext cell forbids ``DECRYPT_START`` outright;
  * from the BACKUP cell -- the rejection sits between the primary read and the
    backup read, and the run ends in a completed boot rather than
    ``MANIFEST_ALL_FAILED``;
  * from all of them -- the flash device must be shown to have served this row's
    exact re-encrypted bytes at this row's field address.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps on OTBN and two AES
decryptions, and AES is EDN client 0.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_payload_toc_version_major_invalid_test(
        sep_primary_toc_fail_base):
    """Encrypted primary TOC major_version is 2 -> refused -> the backup boots."""

    toc_field = "version_major"
    encrypted = True
