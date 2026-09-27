# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary manifest carries a 64-byte OCA KDF context that derives the wrong AES-256 key.

The packer warning "KDF derived key does not match manifest test key" for this
image is the injected fault. The resulting bad PKCS#7 plaintext is reported as
an OCA decryption failure before the encrypted backup boots.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_decryption_kdf_input_test(sep_decrypt_input_defect_base):
    """Wrong OCA KDF context -> decrypt failure -> the encrypted backup boots."""

    defect = "kdf_input"
