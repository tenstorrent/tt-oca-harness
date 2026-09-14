# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED payload lists its images out of order; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires image
bodies to run in strictly ascending order, enforced as ``off < prev_end``. Entry 1
declaring an offset below entry 0's end trips it, printing
``IMAGE_ORDER_BAD idx=0x00000001`` and returning ``MANIFEST_ERR_IMAGE_OVERLAP``
(0x0003000f). The primary's rejection returns into ``rom_manifest_boot``'s retry
loop, so the required outcome is a completed boot from the untouched backup.

THE PLANTED VALUES ARE THE REFERENCE'S OWN. Its scenario
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:585-590``) writes
``primary.payload_images[0].offset = 0x1000`` and
``primary.payload_images[1].offset = 0x500``. The first is a no-op against the
packer default, which already places image 0 at 0x1000
(``firmware/utils/pack_images/configs/default_test.yaml:72``), and the shipped OSS
payload places its SEP_BL1 at 0x1000 as well -- so both offsets are reproduced here
exactly. The reference's image 1 is a SEPBL2
(``default_test.yaml:80-88``); the OSS payload declares only one image, so the
second is created with that type. See ``sep_toc_entry_defect.SECOND_IMAGE_OFFSET``.

THE PAYLOAD IS GENUINELY ENCRYPTED, AND THE REFERENCE SAYS SO EXPLICITLY. Its
scenario sets ``primary.manifest.encrypted_payload: "1"`` (``:589``), which matches
what the packer's primary block would have supplied anyway (``default_test.yaml:46``).
Neither slot's ``boot_arguments.secure_boot`` is touched, so both inherit 1
(``default_test.yaml:15`` and ``:117``). The reference's BACKUP inherits
``encrypted_payload: 0`` (``:145``) and is therefore plaintext; this port loads
``encrypted_boot.bin``, whose BOTH slots are encrypted, so the recovering backup
decrypts too. That is more work for the DUT, not less, and it is why this row
requires the decryption markers twice rather than once.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-SIZE cell -- the token, ``IMAGE_ORDER_BAD idx=0x00000001``
    against ``IMAGE_LEN_ALIGN idx=0x00000000``, with the sibling token FORBIDDEN,
    and the error code, 0x0003000f against 0x0003000e, with the sibling code
    forbidden too;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly TWICE, with the primary's pair inside its own attempt;
  * from the BACKUP cell -- the rejection sits between the primary read and the
    backup read, and the run ends in a completed boot;
  * from all of them -- the device must be shown to have served this row's exact
    re-encrypted bytes at entry 1's offset field.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps and two AES decryptions.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_primary_toc_entry_fail_base import sep_primary_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_payload_images_out_of_order_test(
        sep_primary_toc_entry_fail_base):
    """Encrypted primary TOC lists image 1 below image 0 -> refused -> backup boots."""

    entry_defect = ted.ORDER
    encrypted = True
