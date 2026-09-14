# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED TOC claims more payload than the manifest; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) cross-checks the
TOC's copy of the payload length against the manifest's before reading any entry,
echoes the offending value as ``TOC_PLEN_MISMATCH=`` and returns
``MANIFEST_ERR_BAD_LENGTH`` (0x00030004). For an ENCRYPTED payload the two are not
required to be equal -- the manifest counts ciphertext and the TOC counts plaintext,
so the manifest may legitimately run up to one AES block ahead -- but the TOC may
never claim MORE than was loaded. With the primary already refused, the backup's
rejection exhausts the retry loop and the run ends terminal on
``MANIFEST_ALL_FAILED``.

THE PLANTED VALUE. ``backup.toc.payload_length = 0x2000``. The encrypted arm
requires the manifest's length to equal the TOC's rounded up to the next AES block,
which for this artefact's 5936 plaintext bytes is 5952. 8192 is neither, so the
agreement is violated.

A TOC DECLARING LESS THAN THE MANIFEST IS NOT COVERED. 0x2000 is above the
manifest's length; no row plants one below it. See
``sep_toc_bound_defect.BAD_TOC_PAYLOAD_LENGTH``.

THE PAYLOAD IS GENUINELY ENCRYPTED. This row loads ``encrypted_boot.bin``, whose
slots both carry ``encrypted_payload = 1``, and the base asserts that flag on the
loaded image.

THE FAILOVER TRIGGER: the primary's manifest identifier is overwritten by
``sep_backup_manifest_fail_base.corrupt_primary``, producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work. That also keeps this
row's own code attributable: the primary's verdict is BAD_MAGIC, not BAD_LENGTH, so
the single BAD_LENGTH in the run is the backup's -- and the base requires it after
the backup's ``CRYPTO_VALIDATE_OK``, which only a slot that cleared
``validate_manifest_header`` in full can reach.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-EXCEEDS-BOUND cell -- the token, ``TOC_PLEN_MISMATCH=`` against
    ``IMAGE_ORDER_BAD idx=0x00000000``, each forbidding the other, and the error
    code, 0x00030004 against 0x0003000f. The two stimuli are mutually unreachable:
    this arm sits ABOVE the per-image loop, so on this row the loop is never entered
    and no image bound can be evaluated;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly ONCE, the backup's, and before the rejection. The two compare
    against different lengths: the plaintext row against the manifest's own, this
    one against the PKCS#7-padded length derived from the TOC's;
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, no
    boot-progress marker, and the served bytes are required at the BACKUP slot's
    address (0x042008, not 0x002008). That address is the only discriminator
    available on an encrypted row: the TOC's payload_length lives in AES block 0, and
    the two slots' payloads are byte-identical until block 8, so both slots serve
    IDENTICAL ciphertext for the same planted value.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp and an AES
decryption.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_backup_toc_bound_fail_base import sep_backup_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_toc_payload_size_mismatch_test(
        sep_backup_toc_bound_fail_base):
    """Encrypted backup TOC claims 0x2000 against a 5952-byte payload -> halt."""

    bound_defect = tbd.PLEN
    encrypted = True
