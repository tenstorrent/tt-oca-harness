# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI-Lite VIP selftest: reads and writes in flight together.

``pipeline_result`` claims that every beat launches on the later of its
channel delay and the cycle after the beat ahead of it on its channel was
accepted, that the read and write channels run independently, that BREADY
and RREADY stay low for the requested hold after the first BVALID and
RVALID, that each response returns to its own access, and that the reported
stall cycles match the wires. Every claim is judged against a per-cycle
recording of the l_axi nets, with and without the responder stalling its
request channels. Data integrity is cross-checked through the lite slave's
backdoor, so an ordering-only pass cannot mask a misrouted response.
"""

from __future__ import annotations

import logging
import os

import cocotb
from cocotb.triggers import Event, RisingEdge
from ocah_axi_vip import OcahAxiPipelineOp
from ocah_axi_vip_harness import (
    build_lite_stack,
    handshake_cycles,
    scenario_rng,
    stall_cycles,
    start_clock_reset,
)

log = logging.getLogger("cocotb.tb.ocah_axi_lite_pipeline_test")

_KEYS = (
    "awvalid",
    "awready",
    "awaddr",
    "wvalid",
    "wready",
    "wdata",
    "bvalid",
    "bready",
    "arvalid",
    "arready",
    "araddr",
    "rvalid",
    "rready",
)


def _sample(handle) -> int:
    try:
        return int(handle.value)
    except ValueError:
        return 0


async def record(dut, stop: Event) -> list[dict[str, int]]:
    """Record the l_axi nets once per cycle, from the next edge until ``stop`` is set."""
    samples: list[dict[str, int]] = []
    while not stop.is_set():
        await RisingEdge(dut.clk)
        samples.append({key: _sample(getattr(dut, f"l_axi_{key}")) for key in _KEYS})
    return samples


def check_lane(
    samples: list[dict[str, int]],
    channel: str,
    payload: str,
    expected: list[int],
    delays: list[int],
    *,
    index: int,
) -> list[int]:
    """Judge one request channel's order and launch cycles; return its handshake cycles.

    A beat with delay ``d`` may launch on the edge after ``d`` cycles, so it
    shows in sample ``d + 1`` at the earliest; it also waits for the cycle
    after the beat ahead of it was accepted.
    """
    valid, ready = f"{channel}valid", f"{channel}ready"
    hs = handshake_cycles(samples, valid, ready)
    assert len(hs) == len(expected), (
        f"op {index}: {len(hs)} {channel.upper()} handshakes on the wire, expected {len(expected)}"
    )
    assert [samples[c][payload] for c in hs] == expected, (
        f"op {index}: {channel.upper()} order {[hex(samples[c][payload]) for c in hs]} "
        f"!= {[hex(value) for value in expected]}"
    )
    for beat, delay in enumerate(delays):
        floor = hs[beat - 1] + 1 if beat else 0
        launch = next(c for c in range(floor, len(samples)) if samples[c][valid])
        assert launch == max(delay + 1, floor), (
            f"op {index}: {channel.upper()} beat {beat} launched at {launch}, "
            f"expected max(delay {delay} + 1, {floor})"
        )
        assert all(samples[c][valid] for c in range(launch, hs[beat] + 1)), (
            f"op {index}: {channel.upper()} beat {beat} dropped VALID before its handshake"
        )
    return hs


def check_hold(
    samples: list[dict[str, int]], channel: str, hold: int, hs: list[int], *, index: int
) -> None:
    """READY stays low for ``hold`` cycles from the first VALID."""
    if not hs or hold == 0:
        return
    valid, ready = f"{channel}valid", f"{channel}ready"
    first = next(c for c, row in enumerate(samples) if row[valid])
    assert hs[0] - first >= hold, (
        f"op {index}: first {channel.upper()} handshake {hs[0] - first} cycles after "
        f"{channel.upper()}VALID, hold {hold}"
    )
    assert not any(row[ready] for row in samples[first : first + hold]), (
        f"op {index}: {channel.upper()}READY rose inside the {hold}-cycle hold"
    )


async def run_pipeline(
    dut,
    seq,
    slave,
    *,
    index: int,
    ops: list[OcahAxiPipelineOp],
    b_hold: int,
    r_hold: int,
    stall: int,
    memory: dict[int, int],
) -> tuple[list[int], list[int]]:
    """Issue one pipeline, judge the wire recording, and return the B and AR handshakes."""
    log.info(
        "op %d: %d accesses (%s) b_hold=%d r_hold=%d stall=%d",
        index,
        len(ops),
        "".join(op.direction[0] for op in ops),
        b_hold,
        r_hold,
        stall,
    )
    if stall > 0:
        slave.sequence.enable_backpressure(channels=("aw", "w", "ar"), stall_cycles=stall)
    else:
        slave.sequence.disable_backpressure()
    stop = Event()
    recorder = cocotb.start_soon(record(dut, stop))
    result = await seq.pipeline_result(ops, b_hold_cycles=b_hold, r_hold_cycles=r_hold)
    stop.set()
    samples = await recorder

    # Each word takes one direction per list, so a read returns the word as
    # it stood before the list.
    assert result.ok, f"op {index}: responses {[r.resp for r in result.results]}"
    for op, res in zip(ops, result.results):
        if op.direction == "write":
            memory[op.address] = op.data
        else:
            shift = 8 * (op.address % 4)
            expected = memory[op.address & ~0x3] >> shift
            assert res.data == expected, (
                f"op {index}: read 0x{op.address:08x} returned 0x{res.data:08x}, "
                f"expected 0x{expected:08x}"
            )
    for addr, value in memory.items():
        assert slave.sequence.read32(addr) == value, f"op {index}: backdoor 0x{addr:08x}"

    writes = [op for op in ops if op.direction == "write"]
    reads = [op for op in ops if op.direction == "read"]
    check_lane(
        samples,
        "aw",
        "awaddr",
        [op.address for op in writes],
        [op.aw_valid_delay for op in writes],
        index=index,
    )
    check_lane(
        samples,
        "w",
        "wdata",
        [op.data for op in writes],
        [op.w_valid_delay for op in writes],
        index=index,
    )
    ar_hs = check_lane(
        samples,
        "ar",
        "araddr",
        [op.address for op in reads],
        [op.ar_valid_delay for op in reads],
        index=index,
    )
    b_hs = handshake_cycles(samples, "bvalid", "bready")
    r_hs = handshake_cycles(samples, "rvalid", "rready")
    assert len(b_hs) == len(writes) and len(r_hs) == len(reads), (
        f"op {index}: {len(b_hs)} B and {len(r_hs)} R handshakes for "
        f"{len(writes)} writes and {len(reads)} reads"
    )
    check_hold(samples, "b", b_hold, b_hs, index=index)
    check_hold(samples, "r", r_hold, r_hs, index=index)

    for channel, reported in (
        ("aw", result.aw_stall_cycles),
        ("w", result.w_stall_cycles),
        ("ar", result.ar_stall_cycles),
    ):
        wire = stall_cycles(samples, f"{channel}valid", f"{channel}ready")
        assert reported == wire, f"op {index}: VIP {channel}_stall_cycles={reported} != wire {wire}"
    return b_hs, ar_hs


@cocotb.test()
async def ocah_axi_lite_pipeline_test(dut) -> None:
    await start_clock_reset(dut)
    master, slave = build_lite_stack(dut)
    await master.start()
    seq = master.sequence
    rng = scenario_rng("pipeline")

    n_ops = int(os.environ.get("OCAH_AXI_LITE_PIPELINE_OPS", "12"))
    log.info("=" * 70)
    log.info("AXI-Lite pipelined reads and writes: directed list plus %d randomized lists", n_ops)
    log.info("=" * 70)

    words = rng.sample(range(0, 2**14, 4), 64)
    memory: dict[int, int] = {}
    for addr in words:
        memory[addr] = rng.getrandbits(32)
        slave.sequence.write32(addr, memory[addr])

    # Directed: reads interleaved with three writes whose responses wait
    # behind a BREADY hold, an AW-first and a W-first write, and an
    # unaligned read.
    directed = [
        OcahAxiPipelineOp.write(words[0], rng.getrandbits(32)),
        OcahAxiPipelineOp.read(words[1]),
        OcahAxiPipelineOp.write(words[2], rng.getrandbits(32), w_valid_delay=3),
        OcahAxiPipelineOp.read(words[3] + 1, ar_valid_delay=1),
        OcahAxiPipelineOp.write(words[4], rng.getrandbits(32), aw_valid_delay=5, w_valid_delay=1),
        OcahAxiPipelineOp.read(words[5]),
    ]
    b_hs, ar_hs = await run_pipeline(
        dut,
        seq,
        slave,
        index=0,
        ops=directed,
        b_hold=10,
        r_hold=4,
        stall=0,
        memory=memory,
    )
    assert ar_hs[0] < b_hs[0], (
        f"op 0: the first AR at {ar_hs[0]} was not accepted before the first B at {b_hs[0]}"
    )
    issued = list(directed)

    for index in range(1, n_ops + 1):
        ops = []
        for _ in range(rng.randrange(3, 9)):
            addr = rng.choice(words)
            if rng.random() < 0.5:
                ops.append(
                    OcahAxiPipelineOp.write(
                        addr,
                        rng.getrandbits(32),
                        aw_valid_delay=rng.randrange(0, 7),
                        w_valid_delay=rng.randrange(0, 7),
                    )
                )
            else:
                ops.append(OcahAxiPipelineOp.read(addr, ar_valid_delay=rng.randrange(0, 7)))
        # A read and a write to one word in the same list race on the lite
        # RAM, so keep each word to one direction per list.
        directions: dict[int, str] = {}
        ops = [op for op in ops if directions.setdefault(op.address, op.direction) == op.direction]
        issued.extend(ops)
        await run_pipeline(
            dut,
            seq,
            slave,
            index=index,
            ops=ops,
            b_hold=rng.randrange(0, 9),
            r_hold=rng.randrange(0, 9),
            stall=rng.randrange(0, 4),
            memory=memory,
        )

    # A plain access afterwards proves the pipeline leaves no pause, hold or
    # queue limit behind.
    slave.sequence.disable_backpressure()
    last = words[-1]
    wres = await seq.write_result(last, 0x5A5A_A5A5)
    rres = await seq.read_result(last)
    assert wres.ok and rres.ok and rres.data == 0x5A5A_A5A5, (
        f"post-pipeline access failed: bresp=0x{wres.resp:x} rresp=0x{rres.resp:x} "
        f"data=0x{rres.data:08x}"
    )
    stats = seq.get_statistics()
    log.info("done: %d pipelines, sequence stats=%s", n_ops + 1, stats)
    writes = sum(1 for op in issued if op.direction == "write")
    assert stats["write_transactions"] == writes + 1
    assert stats["read_transactions"] == len(issued) - writes + 1
