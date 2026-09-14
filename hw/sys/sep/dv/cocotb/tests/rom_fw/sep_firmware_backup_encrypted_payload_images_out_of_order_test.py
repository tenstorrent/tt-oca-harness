# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload lists its images out of order; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires image
bodies to run in strictly ascending order, enforced as ``off < prev_end``. Entry 1
declaring an offset below entry 0's end trips it, printing
``IMAGE_ORDER_BAD idx=0x00000001`` and returning ``MANIFEST_ERR_IMAGE_OVERLAP``
(0x0003000f). With the primary already refused, the backup's rejection exhausts the
retry loop and the run ends terminal on ``MANIFEST_ALL_FAILED``.

THE PLANTED VALUES ARE THE REFERENCE'S OWN. Its scenario
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:591-597``) writes
``backup.payload_images[0].offset = 0x1000`` and
``backup.payload_images[1].offset = 0x500``. The first is a no-op against the packer
default, which already places image 0 at 0x1000
(``firmware/utils/pack_images/configs/default_test.yaml:163``), and the shipped OSS
payload places its SEP_BL1 at 0x1000 as well, so both offsets are reproduced exactly.
The reference's image 1 is a SEPBL2 (``default_test.yaml:169-177``); the OSS payload
declares only one image, so the second is created with that type. See
``sep_toc_entry_defect.SECOND_IMAGE_OFFSET``.

THE PAYLOAD IS GENUINELY ENCRYPTED, AND THE REFERENCE SAYS SO EXPLICITLY. Its
scenario sets ``backup.manifest.encrypted_payload: "1"`` (``:595``), overriding the
packer's backup default of 0 (``default_test.yaml:145``) -- the very field whose
omission in the neighbouring TOC-version row is recorded as ``FINDINGS[0918rtl] R02``.
This row's reference branch sets it, so no such defect applies here. Neither slot's
``boot_arguments.secure_boot`` is touched, so both inherit 1 (``:15`` and ``:117``),
and the reference's PRIMARY inherits ``encrypted_payload: 1`` (``:46``). This port
loads ``encrypted_boot.bin``, whose both slots are encrypted, which matches the
reference on both counts -- and the primary's encryption state is unobservable
anyway, because it is refused on its manifest magic upstream of the first read of
that flag.

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
