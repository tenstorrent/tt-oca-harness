# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CRYPTO stamp call is skipped on a PROD secure boot over SPI; 0xF004.

The contract, stimulus and checks are in sep_rom_gate_withheld_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_gate_withheld_base import SECURE_FLASH_IMAGE, sep_rom_gate_withheld_base


@pyuvm.test()
class sep_rom_gate_skip_crypto_secure_test(sep_rom_gate_withheld_base):
    gate = "crypto"
    flash_image = SECURE_FLASH_IMAGE
    efuse_from_preload = True
    premise_line = "RSA_VERIFY_OK"
