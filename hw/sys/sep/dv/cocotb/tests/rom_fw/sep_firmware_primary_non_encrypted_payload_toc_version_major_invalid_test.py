# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT payload declares a bad TOC major version; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``toc->major_version == TOC_MAJOR_VERSION`` and returns
``MANIFEST_ERR_BAD_TOC_VERSION`` (0x00030006) otherwise. The primary's rejection
returns into ``rom_manifest_boot``'s retry loop, so the required outcome is a
completed boot from the untouched backup.

THE PAYLOAD IS NOT ENCRYPTED, WHICH IS AN EXPLICIT CHOICE IN THE REFERENCE, NOT AN
INHERITED DEFAULT. The reference scenario
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:508-513``) sets
``primary.manifest.encrypted_payload: 0``, overriding the packer's primary block,
which would otherwise supply 1
(``firmware/utils/pack_images/configs/default_test.yaml:46``). This port loads
``secure_boot.bin``, whose primary and backup slots both carry
``encrypted_payload = 0``, and the base asserts that flag rather than trusting the
filename.

THE PLANTED VALUE IS NOT INFERRED FROM THE ROW NAME. The reference draws it from
``[v for v in range(0, 11) if v != TOC_MAJOR_VERSION]``
(``sep_firmware_payload_validation_test.py:486-492``); this port plants
``TOC_MAJOR_VERSION + 1 = 2``, argued in ``sep_toc_defect.BAD_TOC_VERSION``.

============================================================================
SECURE BOOT STAYS ON HERE, AND THE REFERENCE TURNS IT OFF
============================================================================

The reference's scenario also sets
``primary.manifest.boot_arguments.secure_boot: 0``
(``sep_firmware_payload_validation_test.py:512``), which every one of its
``*_NON_ENCRYPTED_*`` scenarios does -- the packer refuses ``encrypted_payload: 1``
together with ``secure_boot: 0``, so the pair travels together in that file. This
port runs under LC=PROD, where ``secure_boot_enabled()`` (``manifest_load.c``)
enforces the crypto chain regardless of the manifest flag, so the primary's
signature is verified and only then is its TOC refused.

That is a deliberate difference and a STRENGTHENING, not a weakening. The feature
under test is unchanged -- ``validate_manifest_payload`` is reached on both paths
and grades the same field -- but with the chain enabled the rejection's POSITION
is pinned: the base requires the primary's own ``RSA_VERIFY_START`` and
``SIG_VALID`` to sit inside its attempt and ahead of its error, so a slot refused
early cannot wear this verdict. Reproducing ``secure_boot: 0`` here would change
NOTHING -- at PROD the manifest flag is never consulted -- so reaching the
``SBOOT_OFF`` branch at all would need a TEST_DEV/RMA fuse image or the
``SBOOT_DIS`` chicken bit, and no row in this batch uses either. That arm of
``validate_manifest_payload`` is therefore not covered here; ``SBOOT_OFF`` is
forbidden, so this row can never drift onto it.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-COUNT cell -- the error code, 0x00030006 against 0x00030010,
    with the sibling code FORBIDDEN;
  * from the ENCRYPTED cell -- ``DECRYPT_START`` must NEVER appear. The ROM calls
    ``decrypt_payload`` only for a slot whose ``encrypted_payload`` flag is set, so
    the marker's absence is the flag's absence;
  * from the BACKUP cell -- the rejection sits between the primary read and the
    backup read, and the run ends in a completed boot;
  * from all of them -- the device must be shown to have served the planted
    little-endian bytes at this row's field address.

Needs ``+sep_crypto_edn_force``: both slots run a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_payload_toc_version_major_invalid_test(
        sep_primary_toc_fail_base):
    """Plaintext primary TOC major_version is 2 -> refused -> the backup boots."""

    toc_field = "version_major"
    encrypted = False
