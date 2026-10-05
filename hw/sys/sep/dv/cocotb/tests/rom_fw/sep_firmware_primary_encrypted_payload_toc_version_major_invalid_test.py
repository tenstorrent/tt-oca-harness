# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC declares major_version 2; the backup boots.

The spec supports TOC major version 1 only, so the slot must be refused with
``OCA_FAIL_PAYLOAD_TOC``. Needs ``+esrc_noise_force``: two RSA-3072 modexps and AES decryptions.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_payload_toc_version_major_invalid_test(
    sep_primary_toc_fail_base
):
    """Encrypted primary TOC major_version is 2 -> refused -> the backup boots."""

    toc_field = td.VERSION_MAJOR
    encrypted = True
