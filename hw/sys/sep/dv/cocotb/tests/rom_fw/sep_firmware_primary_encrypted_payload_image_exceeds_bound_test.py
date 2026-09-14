# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC places image 0 inside the TOC region; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires every
image body to begin at or after ``prev_end``, seeded at the TOC region. Entry 0
declaring an offset below that region trips it, printing
``IMAGE_ORDER_BAD idx=0x00000000`` and returning ``MANIFEST_ERR_IMAGE_OVERLAP``
(0x0003000f). The primary's rejection returns into ``rom_manifest_boot``'s retry
loop, so the required outcome is a completed boot from the untouched backup.

THE PLANTED VALUE. ``primary.payload_images[0].offset = 240``. The bound is the TOC
region, whose size follows the image count: the shipped payload declares ONE image,
so the region is 32 + 216 = 248 bytes. 240 is the largest 8-byte-aligned offset
still inside it, which makes it the tightest possible violation and pins the
comparison to the region size exactly. Any offset at or above 248 is ACCEPTED;
``pm.set_toc_entry_offset`` refuses one rather than planting it. See
``sep_toc_bound_defect.BOUND_IMAGE_OFFSET``.

THE PAYLOAD IS GENUINELY ENCRYPTED. This row loads ``encrypted_boot.bin``, whose
slots both carry ``encrypted_payload = 1``, and the base asserts that flag on the
loaded image. The recovering backup is encrypted too and decrypts in turn, which is
why this row requires the decryption markers twice rather than once.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the TOC-PAYLOAD-SIZE cell -- the token, ``IMAGE_ORDER_BAD idx=0x00000000``
    against ``TOC_PLEN_MISMATCH=``, each forbidding the other, and the error code,
    0x0003000f against 0x00030004, with the sibling code forbidden too. The two
    stimuli are mutually unreachable: that arm sits above the per-image loop and
    this row leaves the TOC's ``payload_length`` equal to the manifest's, so it
    cannot fire;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly TWICE, with the primary's pair inside its own attempt;
  * from the BACKUP cell -- the rejection sits between the primary read and the
    backup read, the run ends in a completed boot, and the served bytes are required
    at the PRIMARY slot's address (0x002028, not 0x042028). That address is the only
    discriminator available on an encrypted row: entry 0's offset lives in AES block
    2, and the two slots' payloads are byte-identical until block 8, so both slots
    serve IDENTICAL ciphertext for the same planted value;
  * from ``sep_firmware_primary_encrypted_payload_images_out_of_order_test``, which
    lands on the SAME ``if`` -- the entry index, ``idx=0x00000000`` here against
    ``idx=0x00000001`` there, and that row's exact token is FORBIDDEN here. The two
    violate different halves of one rule: this row's body starts inside the TOC
    REGION, that row's starts inside the PREVIOUS IMAGE. The ROM does not report
    which half, and nothing here claims it does.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps and two AES decryptions.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_primary_toc_bound_fail_base import sep_primary_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_payload_image_exceeds_bound_test(
        sep_primary_toc_bound_fail_base):
    """Encrypted primary TOC starts image 0 inside the TOC region -> backup boots."""

    bound_defect = tbd.BOUND
    encrypted = True
