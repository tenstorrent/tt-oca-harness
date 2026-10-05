# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED TOC entry 0 starts inside the TOC; the ROM halts.

The payload format places every image after the TOC, so the slot must be refused with
``OCA_FAIL_PAYLOAD_TOC``. Known gap: no library check enforces the placement, so the DUT accepts
the slot and this test fails. Needs ``+esrc_noise_force``: an RSA-3072 modexp and an AES
decryption.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_payload_image_exceeds_bound_test(sep_backup_toc_fail_base):
    """Encrypted backup TOC entry 0 offset 240 lies inside the TOC -> both slots refused -> halt."""

    toc_field = td.IMAGE_IN_TOC
    encrypted = True
