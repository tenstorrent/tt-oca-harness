# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Composable JTAG2AXI command library; operations execute through a parent DTP sequence."""

from __future__ import annotations

import random
from typing import Any

AXI_MEM_SIZE = 2**16
AXI_BEAT_BYTES = 8


class dtp_jtag2axi_cmd_lib_seq:
    """Small JTAG2AXI operations that execute through a parent DTP sequence."""

    def __init__(self, parent: Any) -> None:
        self.parent = parent
        self.log = parent.log

    def random_aligned_addr(self, rng: random.Random) -> int:
        """Pick one aligned address inside the OSS AXI RAM window."""
        return rng.randrange(0, AXI_MEM_SIZE - AXI_BEAT_BYTES, AXI_BEAT_BYTES)

    async def random_single_write(self, rng: random.Random) -> tuple[int, int, object]:
        """Issue one randomized JTAG2AXI write and return address, data, and item."""
        addr = self.random_aligned_addr(rng)
        data = rng.getrandbits(64)
        self.log.info("Random JTAG2AXI write addr=0x%08x data=0x%016x", addr, data)
        item = await self.parent.jtag2axi_write(addr, data)
        return addr, data, item

    async def random_single_read(self, rng: random.Random) -> tuple[int, object]:
        """Issue one randomized JTAG2AXI read and return address and item."""
        addr = self.random_aligned_addr(rng)
        self.log.info("Random JTAG2AXI read addr=0x%08x", addr)
        item = await self.parent.jtag2axi_read(addr)
        return addr, item
