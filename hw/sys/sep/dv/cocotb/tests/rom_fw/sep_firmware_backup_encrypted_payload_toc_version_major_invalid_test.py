# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload declares a bad TOC major version; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``toc->major_version == TOC_MAJOR_VERSION`` and returns
``MANIFEST_ERR_BAD_TOC_VERSION`` (0x00030006) otherwise. With the primary already
refused, the backup's rejection exhausts the retry loop and the run ends terminal
on ``MANIFEST_ALL_FAILED``.

THE FAILOVER TRIGGER IS THE REFERENCE'S OWN. Its scenario
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:503-507``) pairs the
backup mutation with ``primary.manifest.manifest_identifier: "99"``;
``sep_backup_manifest_fail_base.corrupt_primary`` plants that same defect and the
primary is refused with ``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC
work, so the trigger cannot interact with the arm under test.

THE PLANTED VALUE IS NOT INFERRED FROM THE ROW NAME. The reference draws it from
``[v for v in range(0, 11) if v != TOC_MAJOR_VERSION]``
(``sep_firmware_payload_validation_test.py:486-492``); this port plants
``TOC_MAJOR_VERSION + 1 = 2``, argued in ``sep_toc_defect.BAD_TOC_VERSION``.

============================================================================
THE REFERENCE'S BACKUP PAYLOAD IS NOT ENCRYPTED HERE, AND THIS PORT'S IS
============================================================================

This is the one deliberate stimulus difference in this batch, and it is recorded
rather than quietly corrected.

The reference scenario at ``:503-507`` mutates ``backup.toc.version_major`` and
``primary.manifest.manifest_identifier`` and says nothing about encryption, so the
backup slot INHERITS ``encrypted_payload: 0`` from the packer's backup block
(``firmware/utils/pack_images/configs/default_test.yaml:145``). Its
``BACKUP_NON_ENCRYPTED`` sibling at ``:514-520`` sets the same flag to 0
explicitly. The two scenarios therefore pack byte-identical payload encryption,
and the only difference between them is
``primary.manifest.boot_arguments.secure_boot``, on a primary that is rejected on
its magic word before that flag is ever consulted.

The omission is specific to this one pair. The file holds SIX ``BACKUP_ENCRYPTED_*``
scenarios and five of them set the flag explicitly:

  * image count, ``:566-571`` (sets at ``:568``);
  * images out of order, ``:591-597`` (``:595``);
  * image size, ``:618-623`` (``:621``);
  * image exceeds bound, ``:642-647`` (``:645``);
  * TOC payload size mismatch, ``:666-671`` (``:669``).

Their ``BACKUP_NON_ENCRYPTED`` counterparts set it to 0 at ``:578-584``,
``:605-612``, ``:630-636``, ``:654-660`` and ``:678-684``. Only ``:503-507``
omits it. Read against its own siblings it is a missing line, not a design choice.

A second copy-paste slip sits in the same cell pair: the ``BACKUP_NON_ENCRYPTED``
half writes ``primary.manifest.boot_arguments.secure_boot`` at ``:519`` where all
five of its siblings write the ``backup.`` key (``:583``, ``:610``, ``:634``,
``:658``, ``:682``).

This port runs the backup GENUINELY ENCRYPTED, from ``encrypted_boot.bin``. Three
reasons, in order of weight: the row's own requirement is a TOC defect reached
through decryption; leaving it plaintext would make this testcase and its
non-encrypted sibling indistinguishable, so one of the two would be verifying
nothing; and the encrypted form is strictly the longer path, since the slot must
pass its signature, its ciphertext payload hash and its decryption before the TOC
is parsed at all.

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
