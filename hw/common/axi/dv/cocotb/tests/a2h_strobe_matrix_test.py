# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""All 16 WSTRB values on every parameter set, at HADDR[2] = 0 and 1.

For every strobe the table below gives the B response and, when the write
reaches AHB, the HSIZE and HADDR[1:0] of its single transfer. The target word
is preloaded with a known pattern; afterwards the slave memory must hold that
pattern with exactly the strobed bytes replaced when the write was issued, and
the pattern unchanged otherwise. A frontdoor read confirms the same word.

The table restates the converter specification (axi_lite_to_ahb.sv header and
the ABR access-size rules) literally, independent of the scoreboard's rule.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench
from models.ahb_lite_slave import HTRANS_NONSEQ
from models.axil_agents import RESP_NAMES, RESP_OKAY, RESP_SLVERR

# WSTRB -> (BRESP, HSIZE, HADDR[1:0]); HSIZE None means no AHB transfer.
# Every strobe not listed completes with SLVERR and issues no transfer.
MATRIX = {
    # AHB_DATA_WIDTH=64, ALLOW_SUB_WORD_WRITE=0, ACK_ZERO_STROBE_WRITE=1
    "a": {
        0b0000: (RESP_OKAY, None, None),
        0b1111: (RESP_OKAY, 2, 0),
    },
    # AHB_DATA_WIDTH=32, ALLOW_SUB_WORD_WRITE=1, ACK_ZERO_STROBE_WRITE=0
    "b": {
        0b0000: (RESP_SLVERR, None, None),
        0b0001: (RESP_OKAY, 0, 0),
        0b0010: (RESP_OKAY, 0, 1),
        0b0100: (RESP_OKAY, 0, 2),
        0b1000: (RESP_OKAY, 0, 3),
        0b0011: (RESP_OKAY, 1, 0),
        0b1100: (RESP_OKAY, 1, 2),
        0b1111: (RESP_OKAY, 2, 0),
    },
}
# AHB_DATA_WIDTH=64, ALLOW_SUB_WORD_WRITE=1, ACK_ZERO_STROBE_WRITE=0
MATRIX["c"] = MATRIX["b"]

BASE = {"a": 0x0000_3000, "b": 0x0000_4000, "c": 0x0000_5000}
WRITE_DATA = 0xA1B2_C3D4


def merge(before: int, data: int, strb: int) -> int:
    out = before
    for k in range(4):
        if strb >> k & 1:
            out = (out & ~(0xFF << (8 * k))) | (data & (0xFF << (8 * k)))
    return out


@cocotb.test()
async def a2h_strobe_matrix_test(dut) -> None:
    tb = await Bench.create(dut, axi="port")
    chk = tb.chk
    for env in tb.all_envs:
        name = env.cfg.name.upper()
        wide = env.cfg.ahb_data_width == 64
        table = MATRIX[env.cfg.name]
        issued = local = 0
        for half in (0, 1):
            for strb in range(16):
                addr = BASE[env.cfg.name] + (strb << 3) + 4 * half
                before = 0x5A5A_5A5A ^ (strb * 0x0101_0101) ^ (half << 31)
                data = WRITE_DATA ^ (half << 4)
                env.scoreboard.preload_word(addr, before)
                resp_want, hsize_want, off_want = table.get(strb, (RESP_SLVERR, None, None))
                start = len(env.model.transfers)
                resp = await env.port.write(addr, data, strb)
                new = env.transfers_since(start)
                where = f"cfg {name} {addr:#010x}" + (f" (AHB half {half})" if wide else "")
                chk(
                    resp == resp_want,
                    f"{where} WSTRB={strb:04b}: BRESP={RESP_NAMES[resp]}, "
                    f"expected {RESP_NAMES[resp_want]}",
                )
                if hsize_want is None:
                    local += 1
                    chk(not new, f"{where} WSTRB={strb:04b}: no AHB transfer issued")
                    after_want = before
                else:
                    issued += 1
                    chk(len(new) == 1, f"{where} WSTRB={strb:04b}: exactly one AHB transfer")
                    t = new[0]
                    chk(
                        t.htrans == HTRANS_NONSEQ
                        and t.hwrite
                        and t.hsize == hsize_want
                        and t.haddr & 3 == off_want
                        and t.haddr & ~3 == addr,
                        f"{where} WSTRB={strb:04b}: NONSEQ write HSIZE={t.hsize} "
                        f"HADDR={t.haddr:#010x} (expected HSIZE={hsize_want}, "
                        f"HADDR[1:0]={off_want})",
                    )
                    if wide:
                        chk(
                            t.hwdata == data | (data << 32),
                            f"{where}: HWDATA={t.hwdata:#018x} replicates the word",
                        )
                    after_want = merge(before, data, strb)
                after = env.model.read_word(addr)
                chk(
                    after == after_want,
                    f"{where} WSTRB={strb:04b}: memory {before:#010x} -> {after:#010x}, "
                    f"expected {after_want:#010x}",
                )
                rdata, rresp = await env.port.read(addr)
                chk(
                    rresp == RESP_OKAY and rdata == after_want,
                    f"{where} WSTRB={strb:04b}: readback {rdata:#010x} {RESP_NAMES[rresp]}",
                    quiet=True,
                )
        tb.log.info(
            "strobe matrix cfg %s: %d writes issued on AHB, %d completed locally",
            name,
            issued,
            local,
        )
    await tb.finish()
