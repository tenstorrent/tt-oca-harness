# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT payload declares an out-of-range image count; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``0 < image_count <= 256`` and returns ``MANIFEST_ERR_TOC_COUNT`` (0x00030010)
otherwise. The primary's rejection returns into ``rom_manifest_boot``'s retry
loop, so the required outcome is a completed boot from the untouched backup.

THE PAYLOAD IS NOT ENCRYPTED, EXPLICITLY. The reference scenario
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:572-577``) sets
``primary.manifest.encrypted_payload: "0"``, overriding the packer's primary block
which supplies 1 (``firmware/utils/pack_images/configs/default_test.yaml:46``).
This port loads ``secure_boot.bin``, whose slots both carry
``encrypted_payload = 0``, and the base asserts the flag on the loaded image.

THE PLANTED VALUE IS NOT INFERRED FROM THE ROW NAME. The reference draws
``random.choice([0, 257])`` (``sep_firmware_payload_validation_test.py:574``);
this port plants 257, and the ``image_count == 0`` half of the same arm is
therefore not exercised by this row. See ``sep_toc_defect.BAD_IMAGE_COUNT``.
``TOC_REGION_OOB=`` -- the arm immediately after the count -- is forbidden, which
asserts rather than assumes that the count bound ran first.

SECURE BOOT STAYS ON HERE, AND THE REFERENCE TURNS IT OFF. Its scenario also sets
``primary.manifest.boot_arguments.secure_boot: 0``
(``sep_firmware_payload_validation_test.py:576``), the convention every
``*_NON_ENCRYPTED_*`` scenario in that file follows because its packer refuses
``encrypted_payload: 1`` together with ``secure_boot: 0``. This port runs under
LC=PROD, where ``secure_boot_enabled()`` (``manifest_load.c``) enforces the chain
regardless of the manifest flag. The feature under test is unchanged and the
result is stronger: the base requires the primary's own ``RSA_VERIFY_START`` and
``SIG_VALID`` inside its attempt and ahead of its error, so the count rejection is
provably downstream of a verified signature. ``SBOOT_OFF`` is forbidden.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the TOC-VERSION cell -- the error code, 0x00030010 against 0x00030006,
    with the sibling code FORBIDDEN;
  * from the ENCRYPTED cell -- ``DECRYPT_START`` must NEVER appear;
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
class sep_firmware_primary_non_encrypted_invalid_payload_image_count_test(
        sep_primary_toc_fail_base):
    """Plaintext primary TOC image_count is 257 -> refused -> the backup boots."""

    toc_field = "image_count"
    encrypted = False
