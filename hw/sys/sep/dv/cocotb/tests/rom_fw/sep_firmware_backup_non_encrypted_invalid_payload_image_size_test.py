# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT payload declares a misaligned image length; the ROM halts.

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

THE PLANTED VALUE IS NOT INFERRED FROM THE ROW NAME, AND IT IS NOT THE REFERENCE'S.
The reference plants ``backup.payload_images[0].length = 0x1001``
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:632``), which is 1 modulo
4. That exact value cannot be planted on the shipped OSS payload: its single image
sits at 0x1000 in a 5936-byte payload, so 0x1000 + 0x1001 lands outside it and the
SILENT bounds arm would produce this row's error code by a different check. 0x72D is
the largest value with the reference's own residue that still ends inside the
payload, on both shipped images. Residues 2 and 3 are unexercised batch-wide; the
full reasoning is in ``sep_toc_entry_defect.BAD_IMAGE_LENGTH``.

THE PAYLOAD IS NOT ENCRYPTED, AND THE REFERENCE SAYS SO EXPLICITLY. Its scenario
sets ``backup.manifest.encrypted_payload: "0"`` (``:633``), which agrees with the
packer's backup block (``firmware/utils/pack_images/configs/default_test.yaml:145``).
This port loads ``secure_boot.bin``, whose slots both carry ``encrypted_payload = 0``,
and the base asserts that flag on the loaded image. The reference's PRIMARY inherits
``encrypted_payload: 1`` (``:46``) where this port's is plaintext, which is
unobservable: the primary is refused on its manifest magic upstream of the first
read of that flag.

THE FAILOVER TRIGGER IS THE REFERENCE'S OWN:
``primary.manifest.manifest_identifier: "99"`` (``:635``), planted here by
``sep_backup_manifest_fail_base.corrupt_primary`` and producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work.

SECURE BOOT STAYS ON HERE. The reference sets
``backup.manifest.boot_arguments.secure_boot: 0`` (``:634``) -- the ``backup.`` key,
unlike the copy-paste slip recorded as ``FINDINGS[0918rtl] R02`` in a neighbouring
row. This port runs under LC=PROD, where ``secure_boot_enabled()``
(``manifest_load.c``) enforces the chain regardless of the manifest flag. The
feature under test is unchanged and the result is stronger: the base requires the
backup's ``RSA_VERIFY_START``, ``SIG_VALID``, ``PLD_HASH_OK`` and
``CRYPTO_VALIDATE_OK`` exactly once each and in order before the rejection.
Reproducing ``secure_boot: 0`` here would change NOTHING -- at PROD the manifest flag
is never consulted -- so reaching the ``SBOOT_OFF`` branch at all would need a
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
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, the
    ``STATUS_ENCODE(ERROR, 0x000e)`` word, no boot-progress marker, and a quiescent
    ROM afterwards;
  * from all of them -- the device must be shown to have served the planted
    little-endian bytes at the BACKUP slot's entry 0 length field.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_toc_entry_fail_base import sep_backup_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_invalid_payload_image_size_test(
        sep_backup_toc_entry_fail_base):
    """Plaintext backup TOC image 0 length is 0x72D -> both slots refused -> halt."""

    entry_defect = ted.SIZE
    encrypted = False
