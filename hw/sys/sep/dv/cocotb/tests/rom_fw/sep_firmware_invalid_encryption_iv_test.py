# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary manifest carries an IV the payload was not encrypted with.

A wrong CBC IV corrupts block 0 only, which holds the PTOC identifier, so the TOC
ID check fails. Needs +sep_crypto_edn_force (AES is EDN client 0).
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_encryption_iv_test(sep_decrypt_input_defect_base):
    """Primary manifest IV != encryption IV -> TOC refused -> the backup boots."""

    defect = "iv"
