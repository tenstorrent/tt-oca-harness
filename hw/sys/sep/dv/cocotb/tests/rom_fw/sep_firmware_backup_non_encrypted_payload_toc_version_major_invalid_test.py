# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT TOC declares major_version 2; the ROM halts.

The spec rejects a TOC major version above 1 (``OCA_FAIL_PAYLOAD_TOC``); the DUT does not check
the field, so the row fails. Needs ``+esrc_noise_force``: an RSA-3072 modexp.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_payload_toc_version_major_invalid_test(
    sep_backup_toc_fail_base
):
    """Plaintext backup TOC major_version is 2 -> both slots refused -> halt."""

    toc_field = td.VERSION_MAJOR
    encrypted = False
