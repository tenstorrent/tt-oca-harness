# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Address demux smoke: range edges reach their range, the gaps around them get DECERR.

Writes the first and last word of every range, the words on either side of every range and
the last word of the page, checking which range accepted each write, then reads the same
words. Among them are the first and last word of every gap. A range's words answer OKAY with
its read data, the others DECERR with read data ``MISS_DATA``. The writes all come before the
reads, so neither channel's decode can pass on the address the other channel last carried.
"""

from __future__ import annotations

import cocotb
from addr_demux_base_test import RANGES, WINDOW_BASE, WINDOW_SIZE, AddrDemuxTb


@cocotb.test()
async def addr_demux_smoke_test(dut) -> None:
    tb = AddrDemuxTb(dut)
    await tb.start()
    addrs = [WINDOW_BASE + offset for offset, _ in RANGES]
    addrs += [WINDOW_BASE + offset + size - 4 for offset, size in RANGES]
    addrs += [WINDOW_BASE + offset - 4 for offset, _ in RANGES]
    addrs += [WINDOW_BASE + offset + size for offset, size in RANGES]
    addrs.append(WINDOW_BASE + WINDOW_SIZE - 4)
    for addr in addrs:
        await tb.check_write(addr, addr ^ 0xFFFF_FFFF)
    for addr in addrs:
        await tb.check_read(addr)
