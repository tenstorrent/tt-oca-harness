# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC entry 0 starts inside the TOC; the backup boots.

The payload format places every image after the TOC, but no validation rule enforces it,
so the ROM accepts this slot. Needs ``+esrc_noise_force``: two RSA and AES runs.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_payload_image_exceeds_bound_test(sep_primary_toc_fail_base):
    """Encrypted primary TOC entry 0 starts inside the TOC -> refused -> the backup boots."""

    toc_field = td.IMAGE_IN_TOC
    encrypted = True
