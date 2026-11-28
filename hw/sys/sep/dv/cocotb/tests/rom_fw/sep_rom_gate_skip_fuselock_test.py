# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The FUSELOCK stamp call is skipped; the self-check halts with 0xF004.

The contract, stimulus and checks are in sep_rom_gate_withheld_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_gate_withheld_base import sep_rom_gate_withheld_base


@pyuvm.test()
class sep_rom_gate_skip_fuselock_test(sep_rom_gate_withheld_base):
    gate = "fuselock"
