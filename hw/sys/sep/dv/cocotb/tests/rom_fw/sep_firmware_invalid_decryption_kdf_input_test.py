# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary manifest carries a KDF input that derives a different AES key.

The packer warning "KDF derived key does not match manifest test key" for this
image is the injected fault. Needs +sep_crypto_edn_force (AES is EDN client 0).
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_decryption_kdf_input_test(sep_decrypt_input_defect_base):
    """Primary manifest KDF input derives the wrong key -> TOC refused -> backup boots."""

    defect = "kdf_input"
