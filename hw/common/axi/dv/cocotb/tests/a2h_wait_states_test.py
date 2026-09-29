# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""HREADY low in the AHB address phase and in the data phase.

Directed part, per parameter set:

* a read and a write presented while HREADY is held low wait in their address
  phase; the transfer is accepted once HREADY rises, with HADDR and control
  unchanged across the stall (the slave model's hold rule and the RTL's
  ``AddrPhaseHeld_A``);
* a read and a write whose data phase is extended by a fixed number of wait
  states complete with the right data, HWDATA held for the whole data phase
  (the model's hold rule and ``WriteDataHeld_A``).

Random part: several hundred mixed requests with HREADY dropped at random in
both phases, checked by the scoreboard. The run must actually have produced
address-phase stalls and data-phase wait states.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench, random_traffic
from cocotb.triggers import Combine
from models.axil_agents import RESP_OKAY

BASE = {"a": 0x0001_0000, "b": 0x0002_0000, "c": 0x0101_0000}
RANDOM_REQUESTS = 400


async def directed(tb: Bench, env) -> None:
    chk = tb.chk
    name = env.cfg.name.upper()
    base = BASE[env.cfg.name]
    env.scoreboard.preload_word(base + 0x4, 0x1357_9BDF)

    env.model.hold_hready_low(8)
    start = len(env.model.transfers)
    rdata, rresp = await env.port.read(base + 0x4)
    t = env.model.transfers[start]
    chk(
        t.addr_stall >= 1 and rresp == RESP_OKAY and rdata == 0x1357_9BDF,
        f"cfg {name}: read held in its address phase for {t.addr_stall} cycle(s), then "
        f"returned {rdata:#010x}",
    )

    env.model.hold_hready_low(8)
    start = len(env.model.transfers)
    resp = await env.port.write(base + 0x8, 0x2468_ACE0, 0xF)
    t = env.model.transfers[start]
    chk(
        t.addr_stall >= 1 and resp == RESP_OKAY and env.model.read_word(base + 0x8) == 0x2468_ACE0,
        f"cfg {name}: write held in its address phase for {t.addr_stall} cycle(s), then "
        f"landed in memory",
    )

    for waits in (1, 3, 7):
        env.model.plan(waits=waits)
        start = len(env.model.transfers)
        rdata, rresp = await env.port.read(base + 0x8)
        t = env.model.transfers[start]
        chk(
            t.wait_cycles == waits and rresp == RESP_OKAY and rdata == 0x2468_ACE0,
            f"cfg {name}: read with {waits} data-phase wait state(s) returned {rdata:#010x}",
        )

        env.model.plan(waits=waits)
        start = len(env.model.transfers)
        value = 0x0BAD_F00D ^ waits
        resp = await env.port.write(base + 0xC, value, 0xF)
        t = env.model.transfers[start]
        chk(
            t.wait_cycles == waits
            and resp == RESP_OKAY
            and env.model.read_word(base + 0xC) == value,
            f"cfg {name}: write with {waits} data-phase wait state(s) committed {value:#010x}",
        )

    if env.cfg.allow_sub_word_write:
        env.model.plan(waits=4)
        start = len(env.model.transfers)
        resp = await env.port.write(base + 0xC, 0x0000_7700, 0b0010)
        t = env.model.transfers[start]
        want = (0x0BAD_F00D ^ 7) & ~0xFF00 | 0x7700
        chk(
            t.hsize == 0
            and t.wait_cycles == 4
            and resp == RESP_OKAY
            and env.model.read_word(base + 0xC) == want,
            f"cfg {name}: byte write with 4 wait states updated only byte 1 ({want:#010x})",
        )


@cocotb.test()
async def a2h_wait_states_test(dut) -> None:
    tb = await Bench.create(dut, axi="port")
    chk = tb.chk
    for env in tb.all_envs:
        await directed(tb, env)

    for env in tb.all_envs:
        env.model.set_waits(data_prob=0.6, data_max=6, addr_prob=0.35, addr_max=5)
    stalls_before = {e.cfg.name: e.model.addr_stall_edges for e in tb.all_envs}
    waits_before = {e.cfg.name: e.model.data_wait_edges for e in tb.all_envs}
    await Combine(
        *(
            cocotb.start_soon(
                random_traffic(tb, env, RANDOM_REQUESTS, BASE[env.cfg.name] + 0x100, 32)
            )
            for env in tb.all_envs
        )
    )
    for env in tb.all_envs:
        name = env.cfg.name.upper()
        stalls = env.model.addr_stall_edges - stalls_before[env.cfg.name]
        waits = env.model.data_wait_edges - waits_before[env.cfg.name]
        stalled = sum(1 for t in env.model.transfers if t.addr_stall)
        chk(
            stalls > 0 and stalled > 0,
            f"cfg {name}: random run stalled {stalled} address phase(s) over {stalls} edges",
        )
        chk(waits > 0, f"cfg {name}: random run inserted {waits} data-phase wait state(s)")
        env.model.set_waits()
    await tb.finish()
