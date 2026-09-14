# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT payload lists its images out of order; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires image
bodies to run in strictly ascending order, enforced as ``off < prev_end``. Entry 1
declaring an offset below entry 0's end trips it, printing
``IMAGE_ORDER_BAD idx=0x00000001`` and returning ``MANIFEST_ERR_IMAGE_OVERLAP``
(0x0003000f). With the primary already refused, the backup's rejection exhausts the
retry loop and the run ends terminal on ``MANIFEST_ALL_FAILED``.

THE PLANTED VALUES ARE THE REFERENCE'S OWN. Its scenario
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:605-612``) writes
``backup.payload_images[0].offset = 0x1000`` and
``backup.payload_images[1].offset = 0x500``. The first is a no-op against the packer
default (``firmware/utils/pack_images/configs/default_test.yaml:163``), and the
shipped OSS payload places its SEP_BL1 at 0x1000 as well, so both offsets are
reproduced exactly. See ``sep_toc_entry_defect.SECOND_IMAGE_OFFSET``.

THE PAYLOAD IS NOT ENCRYPTED, AND THE REFERENCE SAYS SO EXPLICITLY. Its scenario
sets ``backup.manifest.encrypted_payload: "0"`` (``:609``), which agrees with the
packer's backup block (``default_test.yaml:145``). This port loads
``secure_boot.bin``, whose slots both carry ``encrypted_payload = 0``, and the base
asserts that flag on the loaded image. The reference's PRIMARY inherits
``encrypted_payload: 1`` (``:46``) where this port's is plaintext, which is
unobservable: the primary is refused on its manifest magic upstream of the first
read of that flag.

THE FAILOVER TRIGGER IS THE REFERENCE'S OWN:
``primary.manifest.manifest_identifier: "99"`` (``:611``), planted here by
``sep_backup_manifest_fail_base.corrupt_primary`` and producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work.

SECURE BOOT STAYS ON HERE. The reference sets
``backup.manifest.boot_arguments.secure_boot: 0`` (``:610``) -- the ``backup.`` key,
unlike the copy-paste slip recorded as ``FINDINGS[0918rtl] R02`` in a neighbouring
row. This port runs under LC=PROD, where ``secure_boot_enabled()``
(``manifest_load.c``) enforces the chain regardless of the manifest flag. The
feature under test is unchanged and the result is stronger: the base requires the
backup's ``RSA_VERIFY_START``, ``SIG_VALID``, ``PLD_HASH_OK`` and
``CRYPTO_VALIDATE_OK`` exactly once each and in order before the rejection, which is
what places the verdict in the payload arm rather than in the crypto chain.
Reproducing ``secure_boot: 0`` here would change NOTHING -- at PROD the manifest flag
is never consulted -- so reaching the ``SBOOT_OFF`` branch at all would need a
TEST_DEV/RMA fuse image or the ``SBOOT_DIS`` chicken bit, and no row in this batch
uses either. That arm is therefore not covered here; ``SBOOT_OFF`` and
``CRYPTO_FAIL=`` are both forbidden, so this row can never drift onto it.

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
