# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_BL1 is not the first TOC image; the primary boots anyway.

The multi-image golden stores BLMEMMAP and _VENDOR1 ahead of SEP_BL1, so the ROM must
find BL1 by type. Needs ``+esrc_noise_force``: an RSA-3072 modexp.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_toc_order_boot_base import bl1_index, sep_toc_order_boot_base


@pyuvm.test()
class sep_firmware_manifest_primary_reordered_sepbl1_test(sep_toc_order_boot_base):
    """Primary TOC is [BLMEMMAP, _VENDOR1, SEP_BL1] as packed; BL1 is found by type."""

    def arrange_toc(self, buf: bytearray) -> str:
        index = bl1_index(buf, "primary")
        assert index > 0, "SEP_BL1 is TOC entry 0, so the run would not show a search by type"
        return f"primary TOC left as packed, SEP_BL1 at index {index}"
