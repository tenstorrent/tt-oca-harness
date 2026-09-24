# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Random traffic on every parameter set against the reference-memory scoreboard.

All instances run concurrently. Each request is a read or a write to one of
64 words, sometimes at an unaligned address, with a random AxPROT and, for
writes, a random WSTRB covering all 16 values. The slave inserts random wait
states in both AHB phases and answers a share of transfers with ERROR; the
master gaps AW, W and AR VALID and drops BREADY and RREADY at random. Requests
are queued in bursts of up to six.

The scoreboard checks every request against the reference memory and the
specification's strobe rule; at the end the slave memory must equal the
reference byte for byte, and every response class must have been exercised.
The seed comes from the runner (RANDOM_SEED), and the testlist reseeds this
leaf.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench, random_traffic
from cocotb.triggers import Combine
from models.axil_agents import pause_pattern

REQUESTS_PER_CFG = 1500
BASE = {"a": 0x000B_0000, "b": 0x000C_0000, "c": 0x010B_0000}


@cocotb.test()
async def a2h_random_stress_test(dut) -> None:
    tb = await Bench.create(dut, axi="port")
    chk = tb.chk
    for env in tb.all_envs:
        rng = env.rng
        env.model.set_waits(data_prob=0.35, data_max=5, addr_prob=0.2, addr_max=4)
        env.model.error_prob = 0.06
        env.port.set_valid_pause(
            aw=pause_pattern(rng, 0.2, 3),
            w=pause_pattern(rng, 0.2, 3),
            ar=pause_pattern(rng, 0.2, 3),
        )
        env.port.set_ready_pause(b=pause_pattern(rng, 0.3, 6), r=pause_pattern(rng, 0.3, 6))
    await Combine(
        *(
            cocotb.start_soon(
                random_traffic(tb, env, REQUESTS_PER_CFG, BASE[env.cfg.name], 64, max_queue=6)
            )
            for env in tb.all_envs
        )
    )
    for env in tb.all_envs:
        env.port.set_valid_pause()
        env.port.set_ready_pause()
        env.model.set_waits()
        env.model.error_prob = 0.0
        await tb.wait_until(env.quiescent, 20000, f"cfg {env.cfg.name.upper()} to drain")

    for env in tb.all_envs:
        sb, m, mon = env.scoreboard, env.model, env.monitor
        name = env.cfg.name.upper()
        chk(
            sb.reads_checked + sb.writes_checked == REQUESTS_PER_CFG,
            f"cfg {name}: scoreboard checked all {REQUESTS_PER_CFG} requests "
            f"({sb.reads_checked} reads, {sb.writes_checked} writes)",
        )
        chk(
            sb.writes_with_transfer > 0
            and sb.writes_local > 0
            and sb.slverr_from_ahb > 0
            and sb.slverr_local > 0,
            f"cfg {name}: writes issued on AHB={sb.writes_with_transfer}, completed locally="
            f"{sb.writes_local}, SLVERR from HRESP={sb.slverr_from_ahb}, SLVERR from strobe="
            f"{sb.slverr_local}",
        )
        if env.cfg.ack_zero_strobe_write:
            chk(
                sb.okay_zero_strobe > 0,
                f"cfg {name}: {sb.okay_zero_strobe} zero-strobe writes acknowledged OKAY",
            )
        sizes = {t.hsize for t in m.transfers if t.hwrite}
        want_sizes = {0, 1, 2} if env.cfg.allow_sub_word_write else {2}
        chk(sizes == want_sizes, f"cfg {name}: AHB write HSIZE values seen {sorted(sizes)}")
        chk(
            m.addr_stall_edges > 0
            and m.data_wait_edges > 0
            and mon.r_stall_edges > 0
            and mon.b_stall_edges > 0,
            f"cfg {name}: stress stalled AHB address phases ({m.addr_stall_edges} edges), data "
            f"phases ({m.data_wait_edges}), R ({mon.r_stall_edges}) and B ({mon.b_stall_edges})",
        )
    await tb.finish()
