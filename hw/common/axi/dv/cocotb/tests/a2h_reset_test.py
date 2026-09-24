# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset in the middle of a transaction returns the converter to IDLE.

The pins are driven directly so reset lands in an exact phase. For each
parameter set, reset is asserted with a transaction:

* in its AHB read data phase (slave holding HREADY low);
* in its AHB write address phase (HREADY held low before acceptance);
* in its AHB write data phase (the write never completes, so memory keeps its
  old value);
* waiting on R with RREADY low;
* waiting on B with BREADY low (the AHB write already completed, so memory
  holds the new value).

While reset is low and after it is released, the FSM must be in IDLE with
HTRANS = IDLE, no R or B valid and no ready raised, and no AHB transfer may be
issued until a new request arrives. A fresh read and write must then complete
normally.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench
from cocotb.triggers import RisingEdge
from models.ahb_lite_slave import HTRANS_IDLE, HTRANS_NONSEQ, sample
from models.axil_agents import RESP_OKAY

BASE = {"a": 0x000D_0000, "b": 0x000E_0000, "c": 0x010D_0000}
FSM_IDLE = 0


async def raw_request(
    tb: Bench,
    env,
    kind: str,
    addr: int,
    data: int = 0,
    strb: int = 0xF,
    rready: int = 1,
    bready: int = 1,
) -> None:
    """Present one request and hold it until the converter accepts it."""
    raw = env.raw
    raw.drive(rready=rready, bready=bready)
    if kind == "R":
        raw.drive(araddr=addr, arprot=0, arvalid=1)
        await tb.wait_until(lambda: raw.get("arready") == 1, 100, "AR acceptance")
        raw.drive(arvalid=0)
    else:
        raw.drive(awaddr=addr, awprot=0, awvalid=1, wdata=data, wstrb=strb, wvalid=1)
        await tb.wait_until(lambda: raw.get("awready") == 1, 100, "AW/W acceptance")
        raw.drive(awvalid=0, wvalid=0)


async def raw_read(tb: Bench, env, addr: int) -> tuple[int, int]:
    await raw_request(tb, env, "R", addr)
    await tb.wait_until(lambda: env.raw.get("rvalid") == 1, 200, "R response")
    return env.raw.get("rdata"), env.raw.get("rresp")


async def raw_write(tb: Bench, env, addr: int, data: int) -> int | None:
    await raw_request(tb, env, "W", addr, data)
    await tb.wait_until(lambda: env.raw.get("bvalid") == 1, 200, "B response")
    bresp: int | None = env.raw.get("bresp")
    return bresp


def converter_idle(tb: Bench, env) -> bool:
    raw = env.raw
    state = sample(getattr(tb.dut, f"u_dut_{env.cfg.name}").state_q)
    return bool(
        state == FSM_IDLE
        and sample(env.pin("ahb_htrans")) == HTRANS_IDLE
        and raw.get("rvalid") == 0
        and raw.get("bvalid") == 0
        and raw.get("arready") == 0
        and raw.get("awready") == 0
        and raw.get("wready") == 0
    )


async def reset_and_recover(tb: Bench, env, label: str) -> None:
    chk = tb.chk
    name = env.cfg.name.upper()
    for e in tb.envs.values():
        e.raw.drive(arvalid=0, awvalid=0, wvalid=0)
    tb.dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(tb.dut.clk)
        chk(
            all(converter_idle(tb, e) for e in tb.envs.values()),
            f"cfg {name} {label}: IDLE while reset is low",
            quiet=True,
        )
    tb.dut.rst_n.value = 1
    transfers = len(env.model.transfers)
    for _ in range(6):
        await RisingEdge(tb.dut.clk)
        chk(converter_idle(tb, env), f"cfg {name} {label}: IDLE after reset", quiet=True)
    chk(
        len(env.model.transfers) == transfers,
        f"cfg {name} {label}: FSM state IDLE, HTRANS IDLE, no R/B valid and no ready during and "
        f"after reset; no AHB transfer issued without a new request",
    )


async def scenarios(tb: Bench, env) -> None:
    chk = tb.chk
    name = env.cfg.name.upper()
    base = BASE[env.cfg.name]
    m, sb = env.model, env.scoreboard
    sb.preload_word(base, 0x1234_5678)
    sb.preload_word(base + 4, 0x9ABC_DEF0)

    # Read data phase.
    m.plan(waits=40)
    aborts = m.reset_aborts
    await raw_request(tb, env, "R", base)
    await tb.wait_until(lambda: m.busy, 50, "read data phase")
    await tb.cycles(5)
    await reset_and_recover(tb, env, "read data phase")
    chk(m.reset_aborts == aborts + 1, f"cfg {name}: the stalled read data phase was cut by reset")

    # Write address phase, stalled by HREADY low.
    m.hold_hready_low(40)
    await raw_request(tb, env, "W", base, 0xAAAA_0001)
    await tb.wait_until(
        lambda: sample(env.pin("ahb_htrans")) == HTRANS_NONSEQ, 50, "write address phase"
    )
    await tb.cycles(3)
    await reset_and_recover(tb, env, "write address phase")
    chk(
        m.read_word(base) == 0x1234_5678,
        f"cfg {name}: write cut in its address phase left memory at {m.read_word(base):#010x}",
    )

    # Write data phase.
    m.plan(waits=40)
    aborts = m.reset_aborts
    await raw_request(tb, env, "W", base, 0xAAAA_0002)
    await tb.wait_until(lambda: m.busy, 50, "write data phase")
    await tb.cycles(5)
    await reset_and_recover(tb, env, "write data phase")
    chk(
        m.reset_aborts == aborts + 1 and m.read_word(base) == 0x1234_5678,
        f"cfg {name}: write cut in its data phase never reached memory",
    )

    # R response pending.
    await raw_request(tb, env, "R", base + 4, rready=0)
    await tb.wait_until(lambda: env.raw.get("rvalid") == 1, 50, "R valid")
    await tb.cycles(4)
    await reset_and_recover(tb, env, "R pending")

    # B response pending: the AHB write completed before reset.
    await raw_request(tb, env, "W", base + 4, 0xBBBB_0003, bready=0)
    await tb.wait_until(lambda: env.raw.get("bvalid") == 1, 50, "B valid")
    await tb.cycles(4)
    await reset_and_recover(tb, env, "B pending")
    chk(
        m.read_word(base + 4) == 0xBBBB_0003,
        f"cfg {name}: write whose B was lost to reset had already landed on AHB",
    )

    # Clean traffic afterwards.
    rdata, rresp = await raw_read(tb, env, base)
    chk(
        rresp == RESP_OKAY and rdata == 0x1234_5678,
        f"cfg {name}: first read after the resets returned {rdata:#010x} OKAY",
    )
    bresp = await raw_write(tb, env, base, 0xCAFE_0004)
    rdata, rresp = await raw_read(tb, env, base)
    chk(
        bresp == RESP_OKAY and rresp == RESP_OKAY and rdata == 0xCAFE_0004,
        f"cfg {name}: write/read after the resets round-trips {rdata:#010x}",
    )
    env.raw.drive(rready=0, bready=0)


@cocotb.test()
async def a2h_reset_test(dut) -> None:
    tb = await Bench.create(dut, axi="raw")
    for env in tb.all_envs:
        await scenarios(tb, env)
    for env in tb.all_envs:
        tb.chk(
            env.scoreboard.dropped_by_reset == 5,
            f"cfg {env.cfg.name.upper()}: exactly the 5 requests in flight at a reset were "
            f"dropped ({env.scoreboard.dropped_by_reset})",
        )
    await tb.finish()
