# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A package_id byte is checked only when its selector bit is set.

The primary selects a matching and a mismatching byte and is refused; the backup leaves
its only mismatching byte unselected and boots.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_device_id_variation_base import sep_device_id_variation_base


@pyuvm.test()
class sep_package_id_per_byte_variations_test(sep_device_id_variation_base):
    """Primary: byte 3 matches, byte 6 refuses. Backup: bytes 1..31 match and boot."""

    kind = "package"
    match_byte = 3
    mismatch_byte = 6
