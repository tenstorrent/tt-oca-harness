# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Two-cycle AHB ERROR responses on reads and writes.

For each parameter set the slave answers selected transfers with the AHB-Lite
ERROR response: one cycle with HREADY low and HRESP high, then one with both
high, after zero or more wait states. The converter must return SLVERR for
every one of them, leave memory untouched by a failed write, and complete the
next transfer cleanly, including one queued back to back behind the error.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench
from models.axil_agents import RESP_NAMES, RESP_OKAY, RESP_SLVERR

BASE = {"a": 0x0003_0000, "b": 0x0004_0000, "c": 0x0103_0000}


@cocotb.test()
async def a2h_error_response_test(dut) -> None:
    tb = await Bench.create(dut, axi="port")
    chk = tb.chk
    for env in tb.all_envs:
        name = env.cfg.name.upper()
        base = BASE[env.cfg.name]
        m = env.model
        env.scoreboard.preload_word(base, 0xC0DE_0000)
        env.scoreboard.preload_word(base + 4, 0xC0DE_0004)

        for addr in (base, base + 4):
            for waits in (0, 3):
                m.plan(error=True, waits=waits)
                start = len(m.transfers)
                _, rresp = await env.port.read(addr)
                t = m.transfers[start]
                chk(
                    rresp == RESP_SLVERR
                    and t.error
                    and t.error_cycles == 2
                    and t.wait_cycles == waits,
                    f"cfg {name}: read {addr:#010x} answered ERROR after {waits} wait state(s) "
                    f"-> RRESP={RESP_NAMES[rresp]}",
                )
                rdata, rresp = await env.port.read(addr)
                want = env.scoreboard.ref_word(addr)
                chk(
                    rresp == RESP_OKAY and rdata == want,
                    f"cfg {name}: next read {addr:#010x} is clean: {rdata:#010x} OKAY",
                )

            for waits in (0, 2):
                before = m.read_word(addr)
                m.plan(error=True, waits=waits)
                start = len(m.transfers)
                resp = await env.port.write(addr, 0xDEAD_BEEF, 0xF)
                t = m.transfers[start]
                chk(
                    resp == RESP_SLVERR and t.error and t.hwrite,
                    f"cfg {name}: write {addr:#010x} answered ERROR after {waits} wait state(s) "
                    f"-> BRESP={RESP_NAMES[resp]}",
                )
                chk(
                    m.read_word(addr) == before,
                    f"cfg {name}: failed write left {addr:#010x} at {before:#010x}",
                )
                value = 0x600D_0000 | waits << 8 | addr & 0xFF
                resp = await env.port.write(addr, value, 0xF)
                rdata, rresp = await env.port.read(addr)
                chk(
                    resp == RESP_OKAY and rresp == RESP_OKAY and rdata == value,
                    f"cfg {name}: next write/read {addr:#010x} is clean: {rdata:#010x}",
                )

        if env.cfg.allow_sub_word_write:
            before = m.read_word(base)
            m.plan(error=True, waits=1)
            resp = await env.port.write(base, 0x0000_00AA, 0b0001)
            chk(
                resp == RESP_SLVERR and m.read_word(base) == before,
                f"cfg {name}: byte write answered ERROR -> SLVERR, word stays {before:#010x}",
            )

        # Each failing request has a clean one of the same kind queued right
        # behind it; the slave fails every transfer to the two error words.
        bad_rd, bad_wr = base + 0x8, base + 0xC
        m.error_words = {bad_rd, bad_wr}
        before = m.read_word(bad_wr)
        err = env.port.issue_read(bad_rd)
        ok_rd = env.port.issue_read(base + 4)
        err_wr = env.port.issue_write(bad_wr, 0x1111_1111, 0xF)
        ok_wr = env.port.issue_write(base, 0x2222_2222, 0xF)
        await tb.wait_ops([err, ok_rd, err_wr, ok_wr], 500, f"cfg {name} back-to-back errors")
        m.error_words = set()
        chk(
            err.resp == RESP_SLVERR
            and ok_rd.resp == RESP_OKAY
            and ok_rd.rdata == env.scoreboard.ref_word(base + 4),
            f"cfg {name}: read queued behind an ERROR read returns {ok_rd.rdata:#010x} OKAY",
        )
        chk(
            err_wr.resp == RESP_SLVERR
            and m.read_word(bad_wr) == before
            and ok_wr.resp == RESP_OKAY
            and m.read_word(base) == 0x2222_2222,
            f"cfg {name}: write queued behind an ERROR write lands with OKAY, the failed one "
            f"leaves {bad_wr:#010x} untouched",
        )
        chk(m.error_responses > 0, f"cfg {name}: {m.error_responses} ERROR responses delivered")
    await tb.finish()
