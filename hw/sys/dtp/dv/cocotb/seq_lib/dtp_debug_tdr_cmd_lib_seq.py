# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Composable debug-TDR command library; operations execute through a parent DTP sequence."""

from __future__ import annotations

import random
from typing import Any

DEBUG_CAPS_REGS = [
    "JTAG_CAPS",
    "SMC_JTAG2AXI_CAPS",
    "SMC_OTP_JTAG2AXI_CAPS",
    "SEP_OTP_JTAG2AXI_CAPS",
]


class dtp_debug_tdr_cmd_lib_seq:
    """Small debug-TDR operations that execute through a parent DTP sequence."""

    def __init__(self, parent: Any) -> None:
        self.parent = parent
        self.log = parent.log

    async def random_tmp_status_read(self, rng: random.Random) -> int:
        """Read TMP_STATUS while shifting a randomized two-bit value."""
        shift_value = rng.getrandbits(2)
        value = await self.parent.read_tmp_status(shift_value=shift_value)
        self.parent.log_tmp_status("Random TMP_STATUS read", value)
        return value

    async def random_debug_control_op(self, rng: random.Random) -> int:
        """Write and preserve-read one randomized DEBUG_CONTROL value."""
        value = self.parent.pack_debug_control(
            boot_stall=rng.randint(0, 1),
            boot_stall_ovrd=rng.randint(0, 1),
            cla_clock_stop_en=rng.randint(0, 1),
            jtag_clock_stop=rng.randint(0, 1),
        )
        self.log.info("Random DEBUG_CONTROL write value=0x%x", value)
        await self.parent.write_debug_control(value)
        readback = await self.parent.read_debug_control(shift_value=value)
        self.parent.log_debug_control("Random DEBUG_CONTROL readback", readback)
        return readback

    async def random_caps_read(self, rng: random.Random) -> tuple[str, int]:
        """Read one random CAPS register and return its name/value pair."""
        reg = rng.choice(DEBUG_CAPS_REGS)
        value = await self.parent.read_caps_tdr(reg)
        if reg == "JTAG_CAPS":
            self.parent.log_jtag_caps(value)
        else:
            self.parent.log_jtag2axi_caps(reg, value)
        return reg, value
