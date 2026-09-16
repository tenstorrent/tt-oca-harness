# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Composable JTAG command library; operations execute through a parent DTP sequence."""

from __future__ import annotations

import random
from typing import Any

from env.dtp_tap_device import DTP_BSR_MODEL_LEN
from env.dtp_types import DtpJtagInstr


class dtp_jtag_cmd_lib_seq:
    """Small JTAG operations that execute through a parent DTP sequence."""

    def __init__(self, parent: Any) -> None:
        self.parent = parent
        self.log = parent.log

    async def reset_to_known_idle(self) -> None:
        """Reset the TAP and leave it in Run-Test/Idle."""
        await self.parent.reset_to_tlr()
        await self.parent.goto_run_test_idle()

    async def random_bypass_scan(
        self,
        rng: random.Random,
        *,
        instr: DtpJtagInstr | int = DtpJtagInstr.BYPASS_3F,
        width: int = 64,
    ) -> int:
        """Run one random BYPASS scan and return the pattern used."""
        pattern = self.parent.random_pattern(width, rng)
        self.log.info(
            "Random BYPASS op instr=0x%02x width=%d pattern=0x%x", int(instr), width, pattern
        )
        await self.parent.check_bypass_delay(instr, pattern, width)
        return pattern

    async def random_loopback_scan(
        self,
        rng: random.Random,
        *,
        instr: DtpJtagInstr | int = DtpJtagInstr.SAMPLE_PRELOAD,
        width: int = DTP_BSR_MODEL_LEN,
    ) -> int:
        """Run one random scan-loopback operation and return the pattern used."""
        pattern = self.parent.random_pattern(width, rng)
        self.log.info(
            "Random loopback op instr=0x%02x width=%d pattern=0x%x", int(instr), width, pattern
        )
        await self.parent.check_loopback_scan(instr, pattern, width)
        return pattern
