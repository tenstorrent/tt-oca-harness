# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC entry 0 starts inside the TOC; the backup boots.

The payload format puts every image after the TOC, but neither the spec's rule list nor
the library checks it, so the DUT accepts the slot and this row fails.
Needs ``+esrc_noise_force``: two RSA-3072 modexps and AES decryptions.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_payload_image_exceeds_bound_test(sep_primary_toc_fail_base):
    """Encrypted primary TOC entry 0 starts at offset 240, inside the TOC -> refused -> the backup boots."""

    toc_field = td.IMAGE_IN_TOC
    encrypted = True
