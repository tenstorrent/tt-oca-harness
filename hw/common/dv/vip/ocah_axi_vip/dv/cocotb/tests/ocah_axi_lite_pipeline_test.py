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
backdoor, so an ordering-only pass cannot mask a misrouted response. After
the pipelines, a list whose write times out behind AW and W stalls while its
read completes, and lists rejected for an invalid access before any of their
accesses reaches the bus.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable
from typing import Any

import cocotb
from cocotb.triggers import ClockCycles, Event, ReadOnly, RisingEdge
from ocah_axi_vip import RESP_OKAY, OcahAxiPipelineOp, OcahAxiPipelineResult
from ocah_axi_vip_harness import (
    build_lite_stack,
    handshake_cycles,
    scenario_rng,
    stall_cycles,
    start_clock_reset,
)
from ocah_checker import OcahChecker

log = logging.getLogger("cocotb.tb.ocah_axi_lite_pipeline_test")

CHK_ORDER = "CHK-AXI-PIPE-ORDER"
CHK_LAUNCH = "CHK-AXI-PIPE-LAUNCH"
CHK_HOLD = "CHK-AXI-PIPE-HOLD"
CHK_STALL = "CHK-AXI-PIPE-STALL"
CHK_DATA = "CHK-AXI-PIPE-DATA"
CHK_OVERLAP = "CHK-AXI-PIPE-OVERLAP"
CHK_TIMEOUT = "CHK-AXI-PIPE-TIMEOUT"
CHK_ATOMIC = "CHK-AXI-PIPE-ATOMIC"

# The bound the partial-timeout list runs under, and an AW/W READY stall that
# outlasts it so the bound, not the responder, ends the operation.
SHORT_TIMEOUT_CYCLES = 50
STALL_CYCLES = 4 * SHORT_TIMEOUT_CYCLES
# Strobe of that list's write: a contiguous lane narrower than the beat.
PARTIAL_STRB = 0x6
# Cycles for the released responder to retire the abandoned write.
DRAIN_CYCLES = 64
# Cycles recorded after a rejected list.
QUIET_CYCLES = 20

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
    """Record the l_axi nets once per cycle through the edge ``stop`` is set on."""
    samples: list[dict[str, int]] = []
    while True:
        await RisingEdge(dut.clk)
        samples.append({key: _sample(getattr(dut, f"l_axi_{key}")) for key in _KEYS})
        await ReadOnly()
        if stop.is_set():
            return samples


async def recorded(dut, operation: Awaitable[Any]) -> tuple[Any, list[dict[str, int]]]:
    """Await ``operation`` under a recording that ends on the edge it returns on."""
    stop = Event()
    recorder = cocotb.start_soon(record(dut, stop))
    try:
        value = await operation
    finally:
        stop.set()
    return value, await recorder


def check_lane(
    checker: OcahChecker,
    samples: list[dict[str, int]],
    channel: str,
    payload: str,
    expected: list[int],
    delays: list[int],
    *,
    ctx: str,
) -> list[int]:
    """Judge one request channel's order and launch cycles; return its handshake cycles.

    A beat with delay ``d`` may launch on the edge after ``d`` cycles, so it
    shows in sample ``d + 1`` at the earliest; it also waits for the cycle
    after the beat ahead of it was accepted.
    """
    valid, ready = f"{channel}valid", f"{channel}ready"
    name = channel.upper()
    hs = handshake_cycles(samples, valid, ready)
    if not checker.expect_equal(
        CHK_ORDER, len(hs), len(expected), context=f"{ctx} {name} handshakes"
    ):
        return hs
    for beat, (value, delay) in enumerate(zip(expected, delays)):
        floor = hs[beat - 1] + 1 if beat else 0
        checker.expect_equal(
            CHK_ORDER, samples[hs[beat]][payload], value, context=f"{ctx} {name} beat {beat}"
        )
        launch = next(c for c in range(floor, len(samples)) if samples[c][valid])
        checker.expect_equal(
            CHK_LAUNCH,
            launch,
            max(delay + 1, floor),
            context=f"{ctx} {name} beat {beat} delay {delay} floor {floor}",
        )
        checker.expect_true(
            CHK_LAUNCH,
            all(samples[c][valid] for c in range(launch, hs[beat] + 1)),
            context=f"{ctx} {name} beat {beat} held VALID",
        )
    return hs


def check_hold(
    checker: OcahChecker,
    samples: list[dict[str, int]],
    channel: str,
    hold: int,
    hs: list[int],
    *,
    ctx: str,
) -> None:
    """READY stays low for ``hold`` cycles from the first VALID."""
    if not hs or hold == 0:
        return
    valid, ready = f"{channel}valid", f"{channel}ready"
    first = next(c for c, row in enumerate(samples) if row[valid])
    low = not any(row[ready] for row in samples[first : first + hold])
    checker.expect_true(
        CHK_HOLD,
        hs[0] - first >= hold and low,
        context=f"{ctx} {channel.upper()} first={first} handshake={hs[0]} hold={hold}",
    )


def check_stalls(
    checker: OcahChecker,
    check_id: str,
    result: OcahAxiPipelineResult,
    samples: list[dict[str, int]],
    *,
    ctx: str,
) -> None:
    """Each request channel's reported stall cycles equal the recorded ones."""
    for channel, reported in (
        ("aw", result.aw_stall_cycles),
        ("w", result.w_stall_cycles),
        ("ar", result.ar_stall_cycles),
    ):
        wire = stall_cycles(samples, f"{channel}valid", f"{channel}ready")
        checker.expect_equal(check_id, reported, wire, context=f"{ctx} {channel.upper()} stalls")


async def run_pipeline(
    dut,
    checker: OcahChecker,
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
    ctx = f"op={index}"
    log.info(
        "%s: %d accesses (%s) b_hold=%d r_hold=%d stall=%d",
        ctx,
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
    result, samples = await recorded(
        dut, seq.pipeline_result(ops, b_hold_cycles=b_hold, r_hold_cycles=r_hold)
    )

    # Each word takes one direction per list, so a read returns the word as
    # it stood before the list.
    for position, (op, res) in enumerate(zip(ops, result.results)):
        checker.expect_true(
            CHK_DATA,
            res.ok and not res.timed_out,
            context=f"{ctx} access {position} resp={res.resp}",
        )
        if op.direction == "write":
            memory[op.address] = op.data
        else:
            expected = memory[op.address & ~0x3] >> 8 * (op.address % 4)
            checker.expect_equal(
                CHK_DATA, res.data, expected, context=f"{ctx} read 0x{op.address:08x}"
            )
    for addr, value in memory.items():
        checker.expect_equal(
            CHK_DATA, slave.sequence.read32(addr), value, context=f"{ctx} backdoor 0x{addr:08x}"
        )

    writes = [op for op in ops if op.direction == "write"]
    reads = [op for op in ops if op.direction == "read"]
    check_lane(
        checker,
        samples,
        "aw",
        "awaddr",
        [op.address for op in writes],
        [op.aw_valid_delay for op in writes],
        ctx=ctx,
    )
    check_lane(
        checker,
        samples,
        "w",
        "wdata",
        [op.data for op in writes],
        [op.w_valid_delay for op in writes],
        ctx=ctx,
    )
    ar_hs = check_lane(
        checker,
        samples,
        "ar",
        "araddr",
        [op.address for op in reads],
        [op.ar_valid_delay for op in reads],
        ctx=ctx,
    )
    b_hs = handshake_cycles(samples, "bvalid", "bready")
    r_hs = handshake_cycles(samples, "rvalid", "rready")
    checker.expect_true(
        CHK_ORDER,
        len(b_hs) == len(writes) and len(r_hs) == len(reads),
        context=f"{ctx} {len(b_hs)} B and {len(r_hs)} R handshakes for "
        f"{len(writes)} writes and {len(reads)} reads",
    )
    check_hold(checker, samples, "b", b_hold, b_hs, ctx=ctx)
    check_hold(checker, samples, "r", r_hold, r_hs, ctx=ctx)
    check_stalls(checker, CHK_STALL, result, samples, ctx=ctx)
    return b_hs, ar_hs


async def check_partial_timeout(
    dut, checker: OcahChecker, seq, slave, *, words: list[int], memory: dict[int, int], rng
) -> None:
    """A write held off far beyond a shortened bound times out; the read beside it completes.

    The list runs once with no stall, then again with the write held off far
    beyond a shortened bound: the read keeps its result, the write reports
    ``timed_out`` with the byte length its partial strobe selects, and the
    stall counts run up to the expiry. The statistics baseline follows the
    first run. The abandoned write's word is never read back: the backend
    completes that write once the responder takes its beats.
    """
    word_a, word_b, word_c = words
    ctx = "partial-timeout"
    log.info(
        "%s: strb=0x%x bound=%d stall=%d", ctx, PARTIAL_STRB, SHORT_TIMEOUT_CYCLES, STALL_CYCLES
    )
    slave.sequence.disable_backpressure()
    ops = [
        OcahAxiPipelineOp.write(word_a, rng.getrandbits(32), strb=PARTIAL_STRB),
        OcahAxiPipelineOp.read(word_b),
    ]
    first = await seq.pipeline_result(ops)
    first_write, first_read = first.results
    checker.expect_equal(
        CHK_TIMEOUT,
        first_write.length,
        PARTIAL_STRB.bit_count(),
        context=f"{ctx} first-run write 0x{word_a:08x} byte length",
    )
    checker.expect_equal(
        CHK_TIMEOUT,
        first_read.data,
        memory[word_b],
        context=f"{ctx} first-run read 0x{word_b:08x} data",
    )

    slave.sequence.enable_backpressure(channels=("aw", "w"), stall_cycles=STALL_CYCLES)
    before = seq.get_statistics()
    result, samples = await recorded(
        dut, seq.pipeline_result(ops, timeout_cycles=SHORT_TIMEOUT_CYCLES, allow_timeout=True)
    )
    after = seq.get_statistics()
    wres, rres = result.results
    checker.expect_true(CHK_TIMEOUT, result.timed_out, context=f"{ctx} operation timed out")
    checker.expect_true(
        CHK_TIMEOUT,
        wres.timed_out and not wres.ok,
        context=f"{ctx} write 0x{word_a:08x} timed out",
    )
    checker.expect_equal(
        CHK_TIMEOUT,
        wres.length,
        first_write.length,
        context=f"{ctx} timed-out write 0x{word_a:08x} byte length",
    )
    checker.expect_equal(
        CHK_TIMEOUT, rres.resp, RESP_OKAY, context=f"{ctx} read 0x{word_b:08x} response"
    )
    checker.expect_equal(
        CHK_TIMEOUT, rres.data, memory[word_b], context=f"{ctx} read 0x{word_b:08x} data"
    )
    checker.expect_true(
        CHK_TIMEOUT,
        result.aw_stall_cycles > 0,
        context=f"{ctx} AW stalled {result.aw_stall_cycles} cycles",
    )
    check_stalls(checker, CHK_TIMEOUT, result, samples, ctx=ctx)
    checker.expect_equal(
        CHK_TIMEOUT,
        (
            after["write_transactions"] - before["write_transactions"],
            after["read_transactions"] - before["read_transactions"],
        ),
        (0, 1),
        context=f"{ctx} statistics count the completed read only",
    )

    slave.sequence.disable_backpressure()
    await ClockCycles(dut.clk, DRAIN_CYCLES)
    data = rng.getrandbits(32)
    wres = await seq.write_result(word_c, data)
    rres = await seq.read_result(word_c)
    checker.expect_true(
        CHK_TIMEOUT,
        wres.ok and rres.ok and rres.data == data,
        context=f"{ctx} readback 0x{word_c:08x} after the timeout data=0x{rres.data:08x}",
    )


async def check_atomic_validation(
    dut, checker: OcahChecker, seq, slave, *, word: int, memory: dict[int, int]
) -> None:
    """A list holding an invalid access fails before the valid write ahead of it starts.

    The call raises, the bus stays idle, and a valid list issued afterwards
    reads the word back unchanged.
    """
    ctx = "atomic"
    for invalid in (OcahAxiPipelineOp.read(2**32), OcahAxiPipelineOp.read(word, prot=8)):
        what = f"{ctx} read 0x{invalid.address:x} prot={invalid.prot}"
        ops = [OcahAxiPipelineOp.write(word, memory[word] ^ 0xFFFF_FFFF), invalid]
        rejected = False
        try:
            await seq.pipeline_result(ops)
        except ValueError as exc:
            rejected = True
            log.info("%s: rejected as required: %s", what, exc)
        checker.expect_true(CHK_ATOMIC, rejected, context=f"{what} rejected")
        _, samples = await recorded(dut, ClockCycles(dut.clk, QUIET_CYCLES))
        active = [
            key
            for key in ("awvalid", "wvalid", "bvalid", "arvalid", "rvalid")
            if any(row[key] for row in samples)
        ]
        checker.expect_equal(
            CHK_ATOMIC, active, [], context=f"{what} VALID seen over {len(samples)} cycles"
        )

    follow = await seq.pipeline_result([OcahAxiPipelineOp.read(word)])
    checker.expect_equal(
        CHK_ATOMIC,
        follow.results[0].data,
        memory[word],
        context=f"{ctx} read 0x{word:08x} after the rejected lists",
    )
    checker.expect_equal(
        CHK_ATOMIC, slave.sequence.read32(word), memory[word], context=f"{ctx} backdoor"
    )


@cocotb.test()
async def ocah_axi_lite_pipeline_test(dut) -> None:
    await start_clock_reset(dut)
    master, slave = build_lite_stack(dut)
    await master.start()
    seq = master.sequence
    rng = scenario_rng("pipeline")
    checker = OcahChecker(
        name="ocah_axi_lite_pipeline",
        fail_fast=False,
        logger=log,
        required_ids=(
            CHK_ORDER,
            CHK_LAUNCH,
            CHK_HOLD,
            CHK_STALL,
            CHK_DATA,
            CHK_OVERLAP,
            CHK_TIMEOUT,
            CHK_ATOMIC,
        ),
    )

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
        checker,
        seq,
        slave,
        index=0,
        ops=directed,
        b_hold=10,
        r_hold=4,
        stall=0,
        memory=memory,
    )
    checker.expect_true(
        CHK_OVERLAP,
        bool(ar_hs and b_hs) and ar_hs[0] < b_hs[0],
        context=f"op=0 AR handshakes {ar_hs} B handshakes {b_hs}",
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
            checker,
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
    checker.expect_true(
        CHK_DATA,
        wres.ok and rres.ok and rres.data == 0x5A5A_A5A5,
        context=f"post-pipeline access bresp=0x{wres.resp:x} rresp=0x{rres.resp:x} "
        f"data=0x{rres.data:08x}",
    )
    stats = seq.get_statistics()
    log.info("%d pipelines complete, sequence stats=%s", n_ops + 1, stats)
    writes = sum(1 for op in issued if op.direction == "write")
    checker.expect_equal(
        CHK_DATA,
        (stats["write_transactions"], stats["read_transactions"]),
        (writes + 1, len(issued) - writes + 1),
        context="sequence statistics (writes, reads)",
    )

    await check_partial_timeout(dut, checker, seq, slave, words=words[6:9], memory=memory, rng=rng)
    await check_atomic_validation(dut, checker, seq, slave, word=words[9], memory=memory)
    checker.finalize()
