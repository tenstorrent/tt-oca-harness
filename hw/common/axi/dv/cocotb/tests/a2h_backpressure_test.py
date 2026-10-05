# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RREADY and BREADY held low: the response waits, unchanged, until it is taken.

Directed part, per parameter set: with RREADY (then BREADY) held low for a
fixed number of cycles and a request of the other kind issued once the
response is pending, the response must stay valid with its payload unchanged,
the AHB side must stay IDLE and the queued request must not be accepted until
the response is taken.

Random part: RREADY and BREADY are dropped in random runs of up to 12 cycles
under mixed traffic. The monitor checks every stalled cycle; the run must have
stalled both channels.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench, random_traffic
from cocotb.triggers import Combine, RisingEdge
from models.ahb_lite_slave import HTRANS_IDLE, sample
from models.axil_agents import RESP_OKAY, pause_pattern

BASE = {"a": 0x0005_0000, "b": 0x0006_0000, "c": 0x0105_0000}
HOLD_CYCLES = 25
RANDOM_REQUESTS = 400


async def hold_response(tb: Bench, env, channel: str) -> None:
    chk = tb.chk
    name = env.cfg.name.upper()
    base = BASE[env.cfg.name]
    sink = env.port.r if channel == "R" else env.port.b
    valid = env.pin(f"axil_{'rvalid' if channel == 'R' else 'bvalid'}")
    payload = (
        [env.pin("axil_rdata"), env.pin("axil_rresp")]
        if channel == "R"
        else [env.pin("axil_bresp")]
    )
    queued_ready = env.pin("axil_awready" if channel == "R" else "axil_arready")

    env.scoreboard.preload_word(base, 0x0F0F_1234)
    sink.pause = True
    if channel == "R":
        first = env.port.issue_read(base)
    else:
        first = env.port.issue_write(base, 0x4321_0F0F, 0xF)
    await tb.wait_until(lambda: sample(valid) == 1, 100, f"{channel} response to go valid")
    if channel == "R":
        second = env.port.issue_write(base + 4, 0x7777_8888, 0xF)
    else:
        second = env.port.issue_read(base + 4)
    held = [sample(s) for s in payload]
    transfers = len(env.model.transfers)
    for _ in range(HOLD_CYCLES):
        await RisingEdge(tb.dut.clk)
        chk(
            sample(valid) == 1
            and [sample(s) for s in payload] == held
            and sample(env.pin("ahb_htrans")) == HTRANS_IDLE
            and sample(queued_ready) == 0,
            f"cfg {name}: {channel} held",
            quiet=True,
        )
    chk(
        len(env.model.transfers) == transfers
        and not first.done.is_set()
        and not second.done.is_set(),
        f"cfg {name}: {channel} response {held} held {HOLD_CYCLES} cycles with its ready low; "
        f"AHB stayed IDLE and the queued request was not accepted",
    )
    sink.pause = False
    await tb.wait_ops([first, second], 200, f"cfg {name} held {channel} to drain")
    chk(
        first.resp == RESP_OKAY and second.resp == RESP_OKAY,
        f"cfg {name}: held {channel} and the request queued behind it both completed OKAY",
    )
    if channel == "R":
        chk(first.rdata == 0x0F0F_1234, f"cfg {name}: held read returned {first.rdata:#010x}")
    else:
        chk(env.model.read_word(base) == 0x4321_0F0F, f"cfg {name}: held write landed")


@cocotb.test()
async def a2h_backpressure_test(dut) -> None:
    tb = await Bench.create(dut, axi="port")
    chk = tb.chk
    for env in tb.all_envs:
        await hold_response(tb, env, "R")
        await hold_response(tb, env, "W")

    for env in tb.all_envs:
        env.port.set_ready_pause(
            b=pause_pattern(env.rng, 0.5, 12), r=pause_pattern(env.rng, 0.5, 12)
        )
    await Combine(
        *(
            cocotb.start_soon(
                random_traffic(tb, env, RANDOM_REQUESTS, BASE[env.cfg.name] + 0x100, 32)
            )
            for env in tb.all_envs
        )
    )
    for env in tb.all_envs:
        env.port.set_ready_pause()
        mon = env.monitor
        name = env.cfg.name.upper()
        chk(
            mon.r_stall_edges > 0 and mon.b_stall_edges > 0,
            f"cfg {name}: RREADY low under a valid R for {mon.r_stall_edges} edges (longest "
            f"{mon.max_r_stall_run}), BREADY low under a valid B for {mon.b_stall_edges} edges "
            f"(longest {mon.max_b_stall_run}); every stalled edge kept the response unchanged",
        )
        chk(
            mon.max_r_stall_run >= HOLD_CYCLES and mon.max_b_stall_run >= HOLD_CYCLES,
            f"cfg {name}: the directed holds lasted at least {HOLD_CYCLES} edges",
        )
    await tb.finish()
