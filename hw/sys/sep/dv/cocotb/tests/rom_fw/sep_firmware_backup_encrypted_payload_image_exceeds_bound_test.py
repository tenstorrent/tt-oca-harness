# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED TOC places image 0 inside the TOC region; the ROM halts.

The backup's image 0 offset is 240, inside the 248-byte TOC region of a one-image payload.
Needs ``+sep_crypto_edn_force``: the backup runs an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_backup_toc_bound_fail_base import sep_backup_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_payload_image_exceeds_bound_test(
    sep_backup_toc_bound_fail_base
):
    """Encrypted backup TOC starts image 0 inside the TOC region -> halt."""

    bound_defect = tbd.BOUND
    encrypted = True
