# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT TOC disagrees with the manifest on payload length; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) cross-checks the
TOC's copy of the payload length against the manifest's before reading any entry,
echoes the offending value as ``TOC_PLEN_MISMATCH=`` and returns
``MANIFEST_ERR_BAD_LENGTH`` (0x00030004). For a PLAINTEXT payload the two describe
the same bytes and must agree EXACTLY, so any difference is refused. With the primary
already refused, the backup's rejection exhausts the retry loop and the run ends
terminal on ``MANIFEST_ALL_FAILED``.

THE PLANTED VALUE IS THE REFERENCE'S OWN, VERBATIM. Its scenario
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:678-684``) writes
``backup.toc.payload_length = 0x2000``, and the reference ROM enforces the same
equality for a plaintext payload (``firmware/bootcode/src/manifest.c:399-411``). 8192
differs from this artefact's 5936, so it violates the rule here exactly as it does
there. No substitution was needed.

THE PAYLOAD IS NOT ENCRYPTED, AND THE REFERENCE SAYS SO EXPLICITLY. Its scenario
sets ``backup.manifest.encrypted_payload: "0"`` (``:681``), which agrees with the
packer's backup block
(``firmware/utils/pack_images/configs/default_test.yaml:145``). This port loads
``secure_boot.bin``, whose slots both carry ``encrypted_payload = 0``, and the base
asserts that flag on the loaded image. The reference's PRIMARY inherits
``encrypted_payload: 1`` (``:46``) where this port's is plaintext, which is
unobservable: the primary is refused on its manifest magic upstream of the first
read of that flag.

THE FAILOVER TRIGGER IS THE REFERENCE'S OWN:
``primary.manifest.manifest_identifier: "99"`` (``:683``), planted here by
``sep_backup_manifest_fail_base.corrupt_primary`` and producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work. That also keeps this
row's own code attributable: the primary's verdict is BAD_MAGIC, not BAD_LENGTH, so
the single BAD_LENGTH in the run is the backup's.

SECURE BOOT STAYS ON HERE. The reference sets
``backup.manifest.boot_arguments.secure_boot: 0`` (``:682``) -- the ``backup.`` key,
correctly paired with the slot it mutates. This port runs under LC=PROD, where
``secure_boot_enabled()`` (``manifest_load.c``) enforces the chain regardless of the
manifest flag. The feature under test is unchanged and the result is stronger, and it
is what proves this row's BAD_LENGTH is the TOC's rather than
``validate_manifest_header``'s, which can return the same code: the base asserts the
backup's ``manifest_length`` is still ``MANIFEST_SIZE`` before planting anything, and
requires ``RSA_VERIFY_START``, ``SIG_VALID``, ``PLD_HASH_OK`` and
``CRYPTO_VALIDATE_OK`` exactly once each and in order before the token -- an ordering
only a slot that cleared the header check in full can produce. Reproducing
``secure_boot: 0`` would change NOTHING at PROD, so reaching the ``SBOOT_OFF`` branch
would need a TEST_DEV/RMA fuse image or the ``SBOOT_DIS`` chicken bit, and no row in
this batch uses either. That arm is not covered here; ``SBOOT_OFF`` and
``CRYPTO_FAIL=`` are both forbidden, so this row can never drift onto it.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-EXCEEDS-BOUND cell -- the token, ``TOC_PLEN_MISMATCH=`` against
    ``IMAGE_ORDER_BAD idx=0x00000000``, each forbidding the other, and the error
    code, 0x00030004 against 0x0003000f. The two stimuli are mutually unreachable:
    this arm sits ABOVE the per-image loop, so on this row the loop is never entered
    and no image bound can be evaluated;
  * from the ENCRYPTED cell -- ``DECRYPT_START`` must NEVER appear. The two cells
    also exercise DIFFERENT sub-conditions of the same ``if``: this row violates a
    strict equality, the encrypted one violates the ciphertext bound that allows one
    AES block of PKCS#7 slack;
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, no
    boot-progress marker, and the planted little-endian bytes are required at the
    BACKUP slot's address (0x042008).

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_backup_toc_bound_fail_base import sep_backup_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_toc_payload_size_mismatch_test(
        sep_backup_toc_bound_fail_base):
    """Plaintext backup TOC claims 0x2000 against a 5936-byte payload -> halt."""

    bound_defect = tbd.PLEN
    encrypted = False
