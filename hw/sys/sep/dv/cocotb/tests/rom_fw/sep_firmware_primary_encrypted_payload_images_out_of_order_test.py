# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED payload lists its images out of order; the backup boots.

An added image 1 declares offset 0x500, below image 0 at 0x1000.
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
