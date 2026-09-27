# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An erased OCA CLASS_KEY is refused before AES-256 key derivation.

The backup slot is cleartext and boots after the primary reports that no
provisioned secret exists.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_decryption_class_key_test(sep_decrypt_input_defect_base):
    """Erased CLASS_KEY -> no provisioned secret -> the backup boots."""

    defect = "class_key"
