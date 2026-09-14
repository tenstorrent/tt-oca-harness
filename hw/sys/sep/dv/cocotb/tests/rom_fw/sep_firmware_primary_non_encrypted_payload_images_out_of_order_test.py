# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT payload lists its images out of order; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires image
bodies to run in strictly ascending order, enforced as ``off < prev_end``. Entry 1
declaring an offset below entry 0's end trips it, printing
``IMAGE_ORDER_BAD idx=0x00000001`` and returning ``MANIFEST_ERR_IMAGE_OVERLAP``
(0x0003000f). The primary's rejection returns into ``rom_manifest_boot``'s retry
loop, so the required outcome is a completed boot from the untouched backup.

THE PLANTED VALUES ARE THE REFERENCE'S OWN. Its scenario
(``tb/cocotb_tests/sep_firmware_payload_validation_test.py:598-604``) writes
``primary.payload_images[0].offset = 0x1000`` and
``primary.payload_images[1].offset = 0x500``. The first is a no-op against the
packer default (``firmware/utils/pack_images/configs/default_test.yaml:72``), and
the shipped OSS payload places its SEP_BL1 at 0x1000 as well, so both offsets are
reproduced exactly. See ``sep_toc_entry_defect.SECOND_IMAGE_OFFSET``.

THE PAYLOAD IS NOT ENCRYPTED, AND THE REFERENCE SAYS SO EXPLICITLY. Its scenario
sets ``primary.manifest.encrypted_payload: "0"`` (``:602``), overriding the packer's
primary default of 1 (``default_test.yaml:46``); the backup inherits 0 (``:145``)
and is plaintext in the reference too. This port loads ``secure_boot.bin``, whose
slots both carry ``encrypted_payload = 0``, and the base asserts that flag on the
loaded image.

SECURE BOOT STAYS ON HERE. The reference also sets
``primary.manifest.boot_arguments.secure_boot: 0`` (``:603``), the convention its
``*_NON_ENCRYPTED_*`` scenarios follow because the packer refuses
``encrypted_payload: 1`` together with ``secure_boot: 0``. This port runs under
LC=PROD, where ``secure_boot_enabled()`` (``manifest_load.c``) enforces the chain
regardless of the manifest flag. The feature under test is unchanged and the result
is stronger: the base requires the primary's ``RSA_VERIFY_START`` and ``SIG_VALID``
inside its own attempt before the rejection, which is what places the verdict in
the payload arm rather than in the crypto chain. Reproducing ``secure_boot: 0``
would change NOTHING at PROD, so reaching the ``SBOOT_OFF`` branch at all would need
a TEST_DEV/RMA fuse image or the ``SBOOT_DIS`` chicken bit, and no row in this batch
uses either. That arm is therefore not covered here; ``SBOOT_OFF`` and
``CRYPTO_FAIL=`` are both forbidden, so this row can never drift onto it.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-SIZE cell -- the token, ``IMAGE_ORDER_BAD idx=0x00000001``
    against ``IMAGE_LEN_ALIGN idx=0x00000000``, with the sibling token FORBIDDEN,
    and the error code, 0x0003000f against 0x0003000e;
  * from the ENCRYPTED cell -- ``DECRYPT_START`` must NEVER appear;
  * from the BACKUP cell -- the rejection sits between the primary read and the
    backup read, and the run ends in a completed boot;
  * from all of them -- the device must be shown to have served the planted
    little-endian bytes at entry 1's offset field.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_primary_toc_entry_fail_base import sep_primary_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_payload_images_out_of_order_test(
        sep_primary_toc_entry_fail_base):
    """Plaintext primary TOC lists image 1 below image 0 -> refused -> backup boots."""

    entry_defect = ted.ORDER
    encrypted = False
