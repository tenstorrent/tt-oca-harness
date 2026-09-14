# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT payload declares a misaligned image length; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires every
image length to be 4-byte aligned, enforced as ``(len & 3u) != 0``. A length of
0x72D trips it, printing ``IMAGE_LEN_ALIGN idx=0x00000000`` and returning
``MANIFEST_ERR_IMAGE_OOB`` (0x0003000e). The primary's rejection returns into
``rom_manifest_boot``'s retry loop, so the required outcome is a completed boot from
the untouched backup.

THE ERROR CODE ALONE PROVES NOTHING HERE, which is why the token is required. The
SILENT ``end > p_len`` bounds arm sits immediately above the alignment arm in the
same entry and returns exactly the same ``MANIFEST_ERR_IMAGE_OOB``. Only
``IMAGE_LEN_ALIGN idx=`` distinguishes them, and only this arm prints it.

THE PLANTED VALUE IS NOT INFERRED FROM THE ROW NAME, AND IT IS NOT THE REFERENCE'S.
The reference plants ``primary.payload_images[0].length = 0x1001``
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:626``), which is 1 modulo
4. That exact value cannot be planted on the shipped OSS payload: its single image
sits at 0x1000 in a 5936-byte payload, so 0x1000 + 0x1001 lands outside it and the
SILENT bounds arm would produce this row's error code by a different check. 0x72D is
the largest value with the reference's own residue that still ends inside the
payload, on both shipped images. Residues 2 and 3 are unexercised batch-wide; the
full reasoning is in ``sep_toc_entry_defect.BAD_IMAGE_LENGTH``.

THE PAYLOAD IS NOT ENCRYPTED, AND THE REFERENCE SAYS SO EXPLICITLY. Its scenario
sets ``primary.manifest.encrypted_payload: "0"`` (``:627``), overriding the packer's
primary default of 1 (``firmware/utils/pack_images/configs/default_test.yaml:46``);
the backup inherits 0 (``:145``) and is plaintext in the reference too. This port
loads ``secure_boot.bin``, whose slots both carry ``encrypted_payload = 0``, and the
base asserts that flag on the loaded image.

SECURE BOOT STAYS ON HERE. The reference also sets
``primary.manifest.boot_arguments.secure_boot: 0`` (``:628``), the convention its
``*_NON_ENCRYPTED_*`` scenarios follow because the packer refuses
``encrypted_payload: 1`` together with ``secure_boot: 0``. This port runs under
LC=PROD, where ``secure_boot_enabled()`` (``manifest_load.c``) enforces the chain
regardless of the manifest flag. The feature under test is unchanged and the result
is stronger: the base requires the primary's ``RSA_VERIFY_START`` and ``SIG_VALID``
inside its own attempt before the rejection. Reproducing ``secure_boot: 0`` would
change NOTHING at PROD, so reaching the ``SBOOT_OFF`` branch at all would need a
TEST_DEV/RMA fuse image or the ``SBOOT_DIS`` chicken bit, and no row in this batch
uses either. That arm is therefore not covered here; ``SBOOT_OFF`` and
``CRYPTO_FAIL=`` are both forbidden, so this row can never drift onto it.

THE IMAGE STILL HASHES CORRECTLY. ``pm.set_toc_entry_length`` recomputes the entry's
digest over the newly declared range, so alignment is the ONLY rule this payload
violates and ``IMAGE_HASH_MISMATCH`` is forbidden rather than tolerated.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-ORDER cell -- the token, ``IMAGE_LEN_ALIGN idx=0x00000000``
    against ``IMAGE_ORDER_BAD idx=0x00000001``, with the sibling token FORBIDDEN,
    and the error code, 0x0003000e against 0x0003000f;
  * from the ENCRYPTED cell -- ``DECRYPT_START`` must NEVER appear;
  * from the BACKUP cell -- the rejection sits between the primary read and the
    backup read, and the run ends in a completed boot;
  * from all of them -- the device must be shown to have served the planted
    little-endian bytes at entry 0's length field.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_primary_toc_entry_fail_base import sep_primary_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_invalid_payload_image_size_test(
        sep_primary_toc_entry_fail_base):
    """Plaintext primary TOC image 0 length is 0x72D -> refused -> the backup boots."""

    entry_defect = ted.SIZE
    encrypted = False
