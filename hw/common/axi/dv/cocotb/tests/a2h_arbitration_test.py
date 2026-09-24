# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read/write arbitration and the AW/W pairing rule.

* Continuous traffic: a burst of reads and a burst of writes queued together
  keep AR and AW+W valid at once. The AHB transfers must alternate strictly,
  read first, so neither side starves.
* AW before W: with W held back, the converter must not accept AW, must issue
  no AHB write, and must keep serving reads; the write goes through once W
  arrives.
* W before AW: the same with AW held back.
* Random VALID gaps on AW, W and AR: every request completes, and whenever
  both a read and a complete write were waiting at two consecutive
  acceptances, the two acceptances were of different kinds.
"""

from __future__ import annotations

import cocotb
from a2h_base_test import Bench
from cocotb.triggers import RisingEdge
from models.ahb_lite_slave import sample
from models.axil_agents import RESP_OKAY, pause_pattern

BASE = {"a": 0x0007_0000, "b": 0x0008_0000, "c": 0x0107_0000}
BURST = 12
RANDOM_EACH = 150


async def continuous(tb: Bench, env) -> None:
    chk = tb.chk
    name = env.cfg.name.upper()
    base = BASE[env.cfg.name]
    start = len(env.model.transfers)
    ops = []
    for k in range(BURST):
        ops.append(env.port.issue_read(base + 4 * k))
        ops.append(env.port.issue_write(base + 0x100 + 4 * k, 0xAB00_0000 | k, 0xF))
    await tb.wait_ops(ops, 2000, f"cfg {name} continuous burst")
    kinds = "".join(t.kind for t in env.transfers_since(start))
    chk(
        kinds == "RW" * BURST,
        f"cfg {name}: with AR and AW+W both valid the AHB order is {kinds} (strict R/W "
        f"alternation, read first)",
    )
    chk(all(op.resp == RESP_OKAY for op in ops), f"cfg {name}: all {len(ops)} requests OKAY")


async def one_channel_first(tb: Bench, env, held: str) -> None:
    """Hold back ``held`` ("W" or "AW") and show the write waits while reads pass it."""
    chk = tb.chk
    name = env.cfg.name.upper()
    base = BASE[env.cfg.name] + 0x200
    source = env.port.w if held == "W" else env.port.aw
    other = "AW" if held == "W" else "W"
    other_valid = env.pin("axil_awvalid" if held == "W" else "axil_wvalid")
    source.pause = True
    start = len(env.model.transfers)
    wr = env.port.issue_write(base, 0x5EED_0000 | len(held), 0xF)
    await tb.wait_until(lambda: sample(other_valid) == 1, 50, f"{other} to go valid alone")
    reads = [env.port.issue_read(base + 4 * (k + 1)) for k in range(3)]
    waited = 0
    for _ in range(40):
        await RisingEdge(tb.dut.clk)
        chk(
            sample(env.pin("axil_awready")) == 0 and sample(env.pin("axil_wready")) == 0,
            f"cfg {name}: {other} not accepted without {held}",
            quiet=True,
        )
        waited += 1
    chk(
        all(op.done.is_set() and op.resp == RESP_OKAY for op in reads) and not wr.done.is_set(),
        f"cfg {name}: {other} valid alone for {waited} cycles was not accepted, and the 3 "
        f"reads queued behind it completed",
    )
    chk(
        all(not t.hwrite for t in env.transfers_since(start)),
        f"cfg {name}: no AHB write issued while {held} was missing",
    )
    source.pause = False
    await tb.wait_ops([wr], 100, f"cfg {name} write once {held} arrives")
    writes = [t for t in env.transfers_since(start) if t.hwrite]
    chk(
        wr.resp == RESP_OKAY
        and len(writes) == 1
        and writes[0].haddr == base
        and env.model.read_word(base) == 0x5EED_0000 | len(held),
        f"cfg {name}: once {held} arrived the write issued one AHB transfer and landed",
    )


async def random_fairness(tb: Bench, env) -> None:
    chk = tb.chk
    name = env.cfg.name.upper()
    base = BASE[env.cfg.name] + 0x400
    rng = env.rng
    env.port.set_valid_pause(
        aw=pause_pattern(rng, 0.3, 4), w=pause_pattern(rng, 0.3, 4), ar=pause_pattern(rng, 0.3, 4)
    )
    accepts: list[tuple[str, bool]] = []
    done = False

    async def watch() -> None:
        sig = {
            n: env.pin(f"axil_{n}") for n in ("arvalid", "arready", "awvalid", "awready", "wvalid")
        }
        while not done:
            await RisingEdge(tb.dut.clk)
            v = {n: sample(s) for n, s in sig.items()}
            rd_wait = v["arvalid"] == 1
            wr_wait = v["awvalid"] == 1 and v["wvalid"] == 1
            if v["arvalid"] and v["arready"]:
                accepts.append(("R", wr_wait))
            elif v["awvalid"] and v["awready"]:
                accepts.append(("W", rd_wait))

    watcher = cocotb.start_soon(watch())
    ops = []
    for k in range(RANDOM_EACH):
        ops.append(env.port.issue_read(base + 4 * (k % 16)))
        ops.append(env.port.issue_write(base + 4 * (k % 16), rng.getrandbits(32), 0xF))
    await tb.wait_ops(ops, 20000, f"cfg {name} random fairness traffic")
    done = True
    await watcher
    env.port.set_valid_pause()
    contested = 0
    for (k0, other0), (k1, other1) in zip(accepts, accepts[1:]):
        if other0 and other1:
            contested += 1
            chk(k0 != k1, f"cfg {name}: consecutive contested acceptances alternate", quiet=True)
    chk(
        len(accepts) == len(ops) and contested > 0,
        f"cfg {name}: all {len(ops)} requests completed under random VALID gaps; "
        f"{contested} back-to-back contested acceptances all alternated",
    )


@cocotb.test()
async def a2h_arbitration_test(dut) -> None:
    tb = await Bench.create(dut, axi="port")
    for env in tb.all_envs:
        await continuous(tb, env)
        await one_channel_first(tb, env, "W")
        await one_channel_first(tb, env, "AW")
        await random_fairness(tb, env)
    await tb.finish()
