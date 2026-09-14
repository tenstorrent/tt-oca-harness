# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload lists its images out of order; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires image
bodies to run in strictly ascending order, enforced as ``off < prev_end``. Entry 1
declaring an offset below entry 0's end trips it, printing
``IMAGE_ORDER_BAD idx=0x00000001`` and returning ``MANIFEST_ERR_IMAGE_OVERLAP``
(0x0003000f). With the primary already refused, the backup's rejection exhausts the
retry loop and the run ends terminal on ``MANIFEST_ALL_FAILED``.

THE PLANTED VALUES. Image 0 keeps the 0x1000 the shipped payload already gives its
SEP_BL1, and image 1 declares 0x500 -- below image 0's start. The shipped payload
declares only one image, so entry 1 is created, typed SEPBL2. See
``sep_toc_entry_defect.SECOND_IMAGE_OFFSET``.

THE PAYLOAD IS GENUINELY ENCRYPTED. This row loads ``encrypted_boot.bin``, whose
slots both carry ``encrypted_payload = 1``, and the base asserts that flag on the
loaded image. The primary's encryption state is unobservable in this run: it is
refused on its manifest magic upstream of the first read of that flag.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-SIZE cell -- the token, ``IMAGE_ORDER_BAD idx=0x00000001``
    against ``IMAGE_LEN_ALIGN idx=0x00000000``, with the sibling token FORBIDDEN,
    and the error code, 0x0003000f against 0x0003000e;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly ONCE, the backup's, and before the rejection;
  * from the PRIMARY cell -- the run is terminal: ``MANIFEST_ALL_FAILED``, the
    ``STATUS_ENCODE(ERROR, 0x000f)`` word, no boot-progress marker, and a quiescent
    ROM afterwards;
  * from all of them -- the device must be shown to have served this row's exact
    re-encrypted bytes at the BACKUP slot's entry 1 offset field.

Needs ``+sep_crypto_edn_force``: an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_toc_entry_fail_base import sep_backup_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_payload_images_out_of_order_test(
        sep_backup_toc_entry_fail_base):
    """Encrypted backup TOC lists image 1 below image 0 -> both slots refused -> halt."""

    entry_defect = ted.ORDER
    encrypted = True
