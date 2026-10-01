# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Queued reads each carry their full address and return their own word.

A bridge that streams queued reads as HTRANS = SEQ with HADDR[2:0] cleared
presents a read of MLDSA_VERSION1 (offset 0xC, value 0x0000_3100) at HADDR
offset 0x8. The 64-bit Adams Bridge slave then returns the word at 0x8 on the
low half of HRDATA and zeros on the upper half, and the upper-half select that
offset 0xC makes returns 0 instead of 0x0000_3100. Only a read issued while
another is in flight can show it.

The stock cocotbext-axi AxiLiteMaster queues 1, 2, 3, 4 and 8 reads of
offset 0xC back to back, then a burst of mixed offsets, on every parameter
set, with the slave holding distinct values at offsets 0x0/0x4/0x8/0xC. Every
read must return its own address's value, and every AHB transfer must be a
NONSEQ word read carrying the full address. A second pass repeats the pattern
with random wait states in both AHB phases and, on the 64-bit sets, zeros in
the unused half of HRDATA, which is what the Adams Bridge slave returns there.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench
from cocotb.triggers import Combine
from cocotbext.axi import AxiResp
from models.ahb_lite_slave import HSIZE_WORD, HTRANS_NONSEQ

BASE = 0x1094_0000
WORDS = {0x0: 0x4D4C_4453, 0x4: 0x0000_0087, 0x8: 0x0000_0001, 0xC: 0x0000_3100}
DEPTHS = (1, 2, 3, 4, 8)
MIXED = (0xC, 0x8, 0x4, 0x0, 0xC, 0xC, 0x4, 0x8, 0x0, 0xC, 0x10C, 0x2008)


async def queued_reads(tb: Bench, env, offsets: list[int], label: str) -> None:
    chk = tb.chk
    name = env.cfg.name.upper()
    start = len(env.model.transfers)
    ar_wait_before = env.monitor.ar_wait_edges
    events = [env.master.init_read(BASE + off, 4) for off in offsets]
    await Combine(*(e.wait() for e in events))
    got = [int.from_bytes(e.data.data, "little") for e in events]
    want = [env.scoreboard.ref_word(BASE + off) for off in offsets]
    resp_ok = all(e.data.resp == AxiResp.OKAY for e in events)
    chk(
        resp_ok and got == want,
        f"cfg {name} {label}: {len(offsets)} queued reads returned "
        f"[{', '.join(f'{v:#x}' for v in got)}]",
    )
    new = env.transfers_since(start)
    addrs = [t.haddr for t in new]
    chk(
        len(new) == len(offsets)
        and all(t.htrans == HTRANS_NONSEQ and not t.hwrite and t.hsize == HSIZE_WORD for t in new)
        and addrs == [BASE + off for off in offsets],
        f"cfg {name} {label}: {len(new)} AHB transfers, all NONSEQ word reads at "
        f"HADDR=[{', '.join(f'{a:#x}' for a in addrs)}]",
    )
    if len(offsets) > 1:
        chk(
            env.monitor.ar_wait_edges > ar_wait_before,
            f"cfg {name} {label}: the next AR was already waiting while a read was in flight "
            f"({env.monitor.ar_wait_edges - ar_wait_before} edges)",
        )


@cocotb.test()
async def a2h_pipelined_read_test(dut) -> None:
    tb = await Bench.create(dut, axi="master")
    chk = tb.chk
    for env in tb.all_envs:
        for off, value in WORDS.items():
            env.scoreboard.preload_word(BASE + off, value)
        for rounds in ("zero-wait", "random waits"):
            if rounds == "random waits":
                env.model.set_waits(data_prob=0.5, data_max=4, addr_prob=0.3, addr_max=3)
                if env.cfg.ahb_data_width == 64:
                    env.model.lane_fill = "zero"
            for depth in DEPTHS:
                await queued_reads(tb, env, [0xC] * depth, f"{rounds} depth {depth} @0xC")
            await queued_reads(tb, env, list(MIXED), f"{rounds} mixed offsets")
        env.model.set_waits()
        env.model.lane_fill = "garbage"
        seq = env.model.htrans_counts
        chk(
            seq[1] == 0 and seq[3] == 0,
            f"cfg {env.cfg.name.upper()}: HTRANS edge counts IDLE={seq[0]} NONSEQ={seq[2]} "
            f"BUSY={seq[1]} SEQ={seq[3]}",
        )
    await tb.finish()
