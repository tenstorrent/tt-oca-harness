# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC is stored in descending offset order; the primary boots.

The spec forbids only overlap, not any entry order, so this is a legal payload.
Needs ``+esrc_noise_force``: an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm
from env import sep_payload_mutate as pm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_toc_order_boot_base import sep_toc_order_boot_base


@pyuvm.test()
class sep_firmware_primary_encrypted_payload_images_descending_order_test(sep_toc_order_boot_base):
    """Encrypted primary TOC stored in descending order -> the primary boots."""

    encrypted = True

    def arrange_toc(self, buf: bytearray) -> str:
        old = pm.permute_toc_entries(buf, "primary", td.DESCENDING)
        assert old == sorted(old, reverse=True), f"stored offsets {old} are not descending"
        return f"primary TOC entries stored as golden indices {list(td.DESCENDING)}"
