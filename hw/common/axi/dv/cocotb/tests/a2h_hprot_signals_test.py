# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""HPROT from AxPROT, and the AHB control the converter holds constant.

Every AxPROT value is sent on a read and a word write through every parameter
set. HPROT must follow the table below (HPROT[0] data = !AxPROT[2],
HPROT[1] privileged = AxPROT[0], never bufferable or cacheable; AxPROT[1],
non-secure, has no AHB-Lite counterpart). Every transfer must be a single
NONSEQ with HBURST = SINGLE and HMASTLOCK = 0; across the whole run HBURST and
HMASTLOCK must be zero on every edge and HTRANS never BUSY or SEQ.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench
from models.ahb_lite_slave import HTRANS_BUSY, HTRANS_IDLE, HTRANS_NONSEQ, HTRANS_SEQ
from models.axil_agents import RESP_OKAY

# AxPROT -> HPROT
HPROT_TABLE = {
    0b000: 0b0001,
    0b001: 0b0011,
    0b010: 0b0001,
    0b011: 0b0011,
    0b100: 0b0000,
    0b101: 0b0010,
    0b110: 0b0000,
    0b111: 0b0010,
}

BASE = {"a": 0x0009_0000, "b": 0x000A_0000, "c": 0x0109_0000}


@cocotb.test()
async def a2h_hprot_signals_test(dut) -> None:
    tb = await Bench.create(dut, axi="port")
    chk = tb.chk
    for env in tb.all_envs:
        name = env.cfg.name.upper()
        base = BASE[env.cfg.name]
        for prot, hprot in HPROT_TABLE.items():
            for kind in ("R", "W"):
                start = len(env.model.transfers)
                addr = base + 8 * prot + (4 if kind == "W" else 0)
                if kind == "R":
                    _, resp = await env.port.read(addr, prot)
                else:
                    resp = await env.port.write(addr, 0x1000_0000 | prot, 0xF, prot)
                new = env.transfers_since(start)
                chk(
                    resp == RESP_OKAY and len(new) == 1,
                    f"cfg {name}: {kind} AxPROT={prot:03b} issued one transfer",
                    quiet=True,
                )
                t = new[0]
                chk(
                    t.hprot == hprot
                    and t.htrans == HTRANS_NONSEQ
                    and t.hburst == 0
                    and t.hmastlock == 0,
                    f"cfg {name}: {kind} AxPROT={prot:03b} -> HPROT={t.hprot:04b} "
                    f"(expected {hprot:04b}), HTRANS=NONSEQ, HBURST={t.hburst}, "
                    f"HMASTLOCK={t.hmastlock}",
                )
        m = env.model
        counts = m.htrans_counts
        chk(
            m.ctrl_nonzero_edges == 0,
            f"cfg {name}: HBURST and HMASTLOCK were zero on all {sum(counts.values())} edges",
        )
        chk(
            counts[HTRANS_BUSY] == 0 and counts[HTRANS_SEQ] == 0 and counts[HTRANS_NONSEQ] > 0,
            f"cfg {name}: HTRANS edge counts IDLE={counts[HTRANS_IDLE]} "
            f"NONSEQ={counts[HTRANS_NONSEQ]} BUSY={counts[HTRANS_BUSY]} SEQ={counts[HTRANS_SEQ]}",
        )
    await tb.finish()
