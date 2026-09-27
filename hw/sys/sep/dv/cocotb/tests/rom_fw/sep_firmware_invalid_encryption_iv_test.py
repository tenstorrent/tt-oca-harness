# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary OCA manifest carries an IV the payload was not encrypted with.

A wrong AES-256-CBC IV corrupts block 0 only, which holds the PTOC identifier,
so decryption completes before the TOC check fails.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_encryption_iv_test(sep_decrypt_input_defect_base):
    """Wrong OCA AES-256 IV -> TOC refused -> the backup boots."""

    defect = "iv"
