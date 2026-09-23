# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's plaintext TOC places image 0 inside the TOC region; the backup boots.

Image 0 starts at 240, inside the 248-byte TOC region, and fails ``IMAGE_ORDER_BAD``.
Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_primary_toc_bound_fail_base import sep_primary_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_payload_image_exceeds_bound_test(
        sep_primary_toc_bound_fail_base):
    """Plaintext primary TOC starts image 0 inside the TOC region -> backup boots."""

    bound_defect = tbd.BOUND
    encrypted = False
