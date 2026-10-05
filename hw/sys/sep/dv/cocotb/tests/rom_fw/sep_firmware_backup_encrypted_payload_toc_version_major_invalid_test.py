# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED TOC declares major_version 2; the ROM halts.

The spec supports TOC major version 1 only, so the slot must be refused with
``OCA_FAIL_PAYLOAD_TOC``. The library and the ROM do not compare toc_version_major, so the slot
is accepted. Needs ``+esrc_noise_force``: an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_payload_toc_version_major_invalid_test(
    sep_backup_toc_fail_base
):
    """Encrypted backup TOC major_version is 2 -> both slots refused -> halt."""

    toc_field = td.VERSION_MAJOR
    encrypted = True
