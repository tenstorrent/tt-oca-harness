# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The HASH gate_inv clear is skipped while its gate_ok set retires; 0xF004.

The contract, stimulus and checks are in sep_rom_gate_withheld_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_gate_withheld_base import sep_rom_gate_withheld_base


@pyuvm.test()
class sep_rom_gate_inv_withheld_test(sep_rom_gate_withheld_base):
    gate = "hash"
    part = "gate_inv"
