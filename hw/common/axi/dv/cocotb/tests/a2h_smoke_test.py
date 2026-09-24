# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Word write and readback through the stock cocotbext-axi AxiLiteMaster.

Each write must reach AHB as one NONSEQ word transfer at the word address and
each read must return the word. On the 64-bit parameter sets (cfg A and C) the
words sit at HADDR[2] = 0 and HADDR[2] = 1, so both halves of the AHB data bus
carry a transfer: the write data must be on both halves of HWDATA and the read
must return the half HADDR[2] selects. The slave fills the other half with
random data on the first pass and with the neighbouring word on the second, so
reading the wrong half fails either way.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench
from cocotbext.axi import AxiResp
from models.ahb_lite_slave import HSIZE_WORD, HTRANS_NONSEQ

WORDS = {
    "a": [
        (0x0000_1000, 0x1111_2222),
        (0x0000_1004, 0x3333_4444),
        (0x1094_0008, 0x5566_7788),
        (0x1094_000C, 0x0000_3100),
    ],
    "b": [(0x0000_2000, 0x9999_AAAA), (0x0000_2004, 0xBBBB_CCCC)],
    "c": [(0x0000_3000, 0xDDDD_EEEE), (0x0000_3004, 0xFFFF_0101)],
}


@cocotb.test()
async def a2h_smoke_test(dut) -> None:
    tb = await Bench.create(dut, axi="master")
    chk = tb.chk
    for env in tb.all_envs:
        name = env.cfg.name.upper()
        wide = env.cfg.ahb_data_width == 64
        for addr, value in WORDS[env.cfg.name]:
            start = len(env.model.transfers)
            wr = await env.master.write(addr, value.to_bytes(4, "little"))
            chk(wr.resp == AxiResp.OKAY, f"cfg {name}: write {addr:#010x}={value:#010x} BRESP OKAY")
            new = env.transfers_since(start)
            chk(len(new) == 1, f"cfg {name}: write {addr:#010x} issued exactly one AHB transfer")
            t = new[0]
            half_txt = f" (AHB half {addr >> 2 & 1})" if wide else ""
            chk(
                t.htrans == HTRANS_NONSEQ
                and t.hwrite
                and t.hsize == HSIZE_WORD
                and t.haddr == addr,
                f"cfg {name}: write is a NONSEQ word transfer at HADDR={addr:#010x}{half_txt}",
            )
            want_hwdata = value | (value << 32) if wide else value
            chk(
                t.hwdata == want_hwdata,
                f"cfg {name}: HWDATA={t.hwdata:#x} carries the word"
                + (" on both halves of the bus" if wide else ""),
            )
            chk(
                env.model.read_word(addr) == value,
                f"cfg {name}: slave memory {addr:#010x} holds {value:#010x}",
            )

        for fill in ("garbage", "memory") if wide else ("garbage",):
            env.model.lane_fill = fill
            fill_txt = f" (unused half filled with {fill})" if wide else ""
            for addr, value in WORDS[env.cfg.name]:
                start = len(env.model.transfers)
                rd = await env.master.read(addr, 4)
                got = int.from_bytes(rd.data, "little")
                chk(
                    rd.resp == AxiResp.OKAY and got == value,
                    f"cfg {name}: read {addr:#010x}{fill_txt} returned "
                    f"{got:#010x} OKAY, expected {value:#010x}",
                )
                new = env.transfers_since(start)
                chk(
                    len(new) == 1
                    and new[0].htrans == HTRANS_NONSEQ
                    and not new[0].hwrite
                    and new[0].hsize == HSIZE_WORD
                    and new[0].haddr == addr,
                    f"cfg {name}: read is one NONSEQ word transfer at HADDR={addr:#010x}",
                )
                if wide:
                    lane = addr >> 2 & 1
                    chk(
                        (new[0].hrdata >> (32 * lane)) & 0xFFFF_FFFF == value,
                        f"cfg {name}: HRDATA={new[0].hrdata:#018x} carried the word on half "
                        f"{lane}, the half the converter returned",
                    )
        env.model.lane_fill = "garbage"
    await tb.finish()
