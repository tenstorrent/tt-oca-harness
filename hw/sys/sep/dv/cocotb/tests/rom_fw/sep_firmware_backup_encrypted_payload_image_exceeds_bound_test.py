# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED TOC places image 0 inside the TOC region; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires every
image body to begin at or after ``prev_end``, seeded at the TOC region. Entry 0
declaring an offset below that region trips it, printing
``IMAGE_ORDER_BAD idx=0x00000000`` and returning ``MANIFEST_ERR_IMAGE_OVERLAP``
(0x0003000f). With the primary already refused, the backup's rejection exhausts the
retry loop and the run ends terminal on ``MANIFEST_ALL_FAILED``.

THE REFERENCE'S RULE IS THIS ROM'S RULE; ITS VALUE IS NOT REACHABLE HERE. The
scenario (``tb/cocotb_tests/sep_firmware_payload_validation_test.py:642-647``)
writes ``backup.payload_images[0].offset = 0x100``, and the reference ROM returns
``SEP_MSG_IMAGE_EXCEEDS_BOUND`` for exactly ``image->offset < prev_end_offset``
(``firmware/bootcode/src/manifest.c:455-459``). 0x100 works there because the
reference payload declares TWO images, making its TOC region 464 bytes; the shipped
OSS payload declares ONE, so its region is 248 bytes and 0x100 = 256 is ABOVE the
bound and would be ACCEPTED. 240 is planted instead -- the largest 8-byte-aligned
offset still inside the region. See ``sep_toc_bound_defect.BOUND_IMAGE_OFFSET``.

THE PAYLOAD IS GENUINELY ENCRYPTED, AND THE REFERENCE SAYS SO EXPLICITLY. Its
scenario sets ``backup.manifest.encrypted_payload: "1"`` (``:645``), overriding the
packer's backup block, which supplies 0
(``firmware/utils/pack_images/configs/default_test.yaml:145``). This port loads
``encrypted_boot.bin``, whose slots both carry ``encrypted_payload = 1``, and the
base asserts that flag on the loaded image. The reference's PRIMARY inherits
``encrypted_payload: 1`` (``:46``), as this port's does, so the slot pairing matches.

THE FAILOVER TRIGGER IS THE REFERENCE'S OWN:
``primary.manifest.manifest_identifier: "99"`` (``:646``), planted here by
``sep_backup_manifest_fail_base.corrupt_primary`` and producing
``MANIFEST_ERR_BAD_MAGIC`` before any hash, crypto or TOC work, so it cannot interact
with the arm under test.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the TOC-PAYLOAD-SIZE cell -- the token, ``IMAGE_ORDER_BAD idx=0x00000000``
    against ``TOC_PLEN_MISMATCH=``, each forbidding the other, and the error code,
    0x0003000f against 0x00030004. The two stimuli are mutually unreachable: that
    arm sits above the per-image loop and this row leaves the TOC's
    ``payload_length`` equal to the manifest's, so it cannot fire;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly ONCE, the backup's, and before the rejection;
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, no
    boot-progress marker, and the served bytes are required at the BACKUP slot's
    address (0x042028, not 0x002028). That address is the only discriminator
    available on an encrypted row: entry 0's offset lives in AES block 2, and the two
    slots' payloads are byte-identical until block 8, so both slots serve IDENTICAL
    ciphertext for the same planted value;
  * from ``sep_firmware_backup_encrypted_payload_images_out_of_order_test``, which
    lands on the SAME ``if`` -- the entry index, ``idx=0x00000000`` here against
    ``idx=0x00000001`` there, and that row's exact token is FORBIDDEN here. The two
    violate different halves of one rule: this row's body starts inside the TOC
    REGION, that row's inside the PREVIOUS IMAGE. The ROM does not report which half,
    and nothing here claims it does.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp and an AES
decryption.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_backup_toc_bound_fail_base import sep_backup_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_payload_image_exceeds_bound_test(
        sep_backup_toc_bound_fail_base):
    """Encrypted backup TOC starts image 0 inside the TOC region -> halt."""

    bound_defect = tbd.BOUND
    encrypted = True
