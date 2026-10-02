# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A chiplet_id byte is checked only when its selector bit is set.

The primary selects a matching byte 2 and a mismatching byte 5 and is refused; the backup
selects matching bytes 1..31, leaves a mismatching byte 0 unselected, and boots.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_device_id_variation_base import sep_device_id_variation_base


@pyuvm.test()
class sep_chiplet_id_per_byte_variations_test(sep_device_id_variation_base):
    """Primary: byte 2 matches, byte 5 refuses. Backup: bytes 1..31 match and boot."""

    kind = "chiplet"
    match_byte = 2
    mismatch_byte = 5
