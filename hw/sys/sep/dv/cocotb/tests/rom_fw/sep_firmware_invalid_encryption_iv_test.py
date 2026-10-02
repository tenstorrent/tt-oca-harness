# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary OCA manifest carries an IV the payload was not encrypted with.

A wrong AES-256-CBC IV changes plaintext block 0 only, so decryption completes and
the TOC bytes then fail the payload hash chain.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_encryption_iv_test(sep_decrypt_input_defect_base):
    """Wrong OCA AES-256 IV -> hash chain refused -> the encrypted backup boots."""

    defect = "iv"
