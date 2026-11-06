# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Address demux sweep: every word around the window, then random addresses.

Writes every word from one page below the window to one page above it and then reads them,
then does the same for 512 random words across the 32-bit space, holding each response and
each write's range to ``expected``. Each set's writes all come before its reads, so neither
channel's decode can pass on the address the other channel last carried.
"""

from __future__ import annotations

import random

import cocotb
from addr_demux_base_test import WINDOW_BASE, WINDOW_SIZE, AddrDemuxTb, random_seed


@cocotb.test()
async def addr_demux_sweep_test(dut) -> None:
    tb = AddrDemuxTb(dut)
    await tb.start()
    rng = random.Random(random_seed())
    window = range(WINDOW_BASE - WINDOW_SIZE, WINDOW_BASE + 2 * WINDOW_SIZE, 4)
    randoms = [rng.randrange(0, 1 << 32, 4) for _ in range(512)]
    for addrs in (window, randoms):
        for addr in addrs:
            await tb.check_write(addr, addr)
        for addr in addrs:
            await tb.check_read(addr)
