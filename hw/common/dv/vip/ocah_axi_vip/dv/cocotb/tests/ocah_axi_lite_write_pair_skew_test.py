# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI-Lite VIP selftest: two outstanding writes with channel skew.

``write_pair_skewed_result`` claims to queue the second write's AW and W
behind the first, to apply the first write's launch skew, to defer BREADY
after the first write's request phase, and to report the AW channel's stall
cycles and stability across the pair. Every
claim is judged against a per-cycle wire recording of the l_axi nets, and data
integrity is cross-checked through the lite slave's backdoor so an
ordering-only pass cannot mask a misrouted beat.
"""

from __future__ import annotations

import logging
import os

import cocotb
from ocah_axi_vip_harness import (
    address_stable_while_stalled,
    build_lite_stack,
    first_cycle,
    handshake_cycles,
    observe_lite_write,
    scenario_rng,
    stall_cycles,
    start_clock_reset,
)

log = logging.getLogger("cocotb.tb.ocah_axi_lite_write_pair_skew_test")

# The launch pipeline (queue -> pause release -> VALID drive) adds at most one
# cycle of slack on the delayed channel; the skew must never be shorter than
# requested.
SKEW_SLACK_CYCLES = 1

# Directed (aw_valid_delay, w_valid_delay, b_ready_delay, aw_stall_cycles)
# corners: AW first with W trailing, W first with AW trailing, deferral alone,
# the AW-first shape under AWREADY stalls, and the degenerate no-skew pair.
DIRECTED_CORNERS = ((0, 5, 0, 0), (5, 0, 0, 0), (0, 0, 3, 0), (0, 4, 2, 2), (0, 0, 0, 0))


def check_first_write_skew(index: int, samples, *, aw_delay: int, w_delay: int) -> None:
    """The first write's AW/W launch order follows the requested skew within the slack."""
    awvalid_first = first_cycle(samples, "awvalid")
    wvalid_first = first_cycle(samples, "wvalid")
    assert awvalid_first is not None and wvalid_first is not None
    skew = awvalid_first - wvalid_first
    requested = aw_delay - w_delay
    log.info(
        "op %d: awvalid@%d wvalid@%d (skew=%+d requested=%+d)",
        index,
        awvalid_first,
        wvalid_first,
        skew,
        requested,
    )
    if requested > 0:
        assert requested <= skew <= requested + SKEW_SLACK_CYCLES, (
            f"op {index}: AW launch skew {skew} outside [{requested}, {requested + SKEW_SLACK_CYCLES}]"
        )
    elif requested < 0:
        assert requested - SKEW_SLACK_CYCLES <= skew <= requested, (
            f"op {index}: W launch skew {skew} outside [{requested - SKEW_SLACK_CYCLES}, {requested}]"
        )
    else:
        assert abs(skew) <= SKEW_SLACK_CYCLES, (
            f"op {index}: equal delays must launch together, observed skew {skew}"
        )


async def run_paired_write(
    dut,
    seq,
    slave,
    *,
    index: int,
    addr_a: int,
    data_a: int,
    addr_b: int,
    data_b: int,
    aw_delay: int,
    w_delay: int,
    b_delay: int,
    aw_stall: int,
) -> None:
    """Issue one paired write and judge the wire recording against the request."""
    log.info(
        "op %d: a=0x%08x/0x%08x b=0x%08x/0x%08x aw_valid_delay=%d w_valid_delay=%d "
        "b_ready_delay=%d aw_stall=%d",
        index,
        addr_a,
        data_a,
        addr_b,
        data_b,
        aw_delay,
        w_delay,
        b_delay,
        aw_stall,
    )
    if aw_stall > 0:
        slave.sequence.enable_backpressure(channels=("aw",), stall_cycles=aw_stall)
    else:
        slave.sequence.disable_backpressure()
    observer = cocotb.start_soon(observe_lite_write(dut, handshakes=2))
    result = await seq.write_pair_skewed_result(
        addr_a,
        data_a,
        addr_b,
        data_b,
        aw_valid_delay=aw_delay,
        w_valid_delay=w_delay,
        b_ready_delay=b_delay,
    )
    samples = await observer

    assert result.ok, f"op {index}: resp a=0x{result.first.resp:x} b=0x{result.second.resp:x}"
    backdoor = (slave.sequence.read32(addr_a), slave.sequence.read32(addr_b))
    assert backdoor == (data_a, data_b), (
        f"op {index}: backdoor 0x{backdoor[0]:08x}/0x{backdoor[1]:08x} != written "
        f"0x{data_a:08x}/0x{data_b:08x}"
    )

    aw_hs = handshake_cycles(samples, "awvalid", "awready")
    w_hs = handshake_cycles(samples, "wvalid", "wready")
    b_hs = handshake_cycles(samples, "bvalid", "bready")
    assert len(aw_hs) == 2 and len(w_hs) == 2 and len(b_hs) == 2, (
        f"op {index}: incomplete pair on the wire: aw_hs={aw_hs} w_hs={w_hs} b_hs={b_hs}"
    )
    assert [samples[c]["awaddr"] for c in aw_hs] == [addr_a, addr_b], (
        f"op {index}: AW order on the wire {[hex(samples[c]['awaddr']) for c in aw_hs]}"
    )
    assert [samples[c]["wdata"] for c in w_hs] == [data_a, data_b], (
        f"op {index}: W order on the wire {[hex(samples[c]['wdata']) for c in w_hs]}"
    )

    # The VIP's AW observation must equal the wire recording: the stall count,
    # and VALID/AWADDR held through every stall (IHI 0022 A3.2.1).
    wire_stall = stall_cycles(samples, "awvalid", "awready")
    log.info(
        "op %d: aw_hs=%s w_hs=%s b_hs=%s wire_stall=%d vip_stall=%d vip_stable=%s",
        index,
        aw_hs,
        w_hs,
        b_hs,
        wire_stall,
        result.aw_stall_cycles,
        result.aw_stable,
    )
    assert result.aw_stall_cycles == wire_stall, (
        f"op {index}: VIP aw_stall_cycles={result.aw_stall_cycles} != wire {wire_stall}"
    )
    assert result.aw_stable and address_stable_while_stalled(
        samples, "awvalid", "awready", "awaddr"
    ), f"op {index}: AW channel changed while stalled (vip_stable={result.aw_stable})"
    if aw_stall > 0:
        assert wire_stall > 0, f"op {index}: AWREADY stalls requested but none observed"

    check_first_write_skew(index, samples, aw_delay=aw_delay, w_delay=w_delay)

    # The first B is accepted after the first write's request phase, trailing
    # it by at least the deferral, and the second B after the second.
    request_done = max(aw_hs[0], w_hs[0])
    assert b_hs[0] > request_done and b_hs[1] > max(aw_hs[1], w_hs[1]), (
        f"op {index}: B accepts {b_hs} precede their request phases aw={aw_hs} w={w_hs}"
    )
    if b_delay > 0:
        assert b_hs[0] - request_done >= b_delay, (
            f"op {index}: BREADY rose {b_hs[0] - request_done} cycles after the first request "
            f"phase, requested deferral {b_delay}"
        )


@cocotb.test()
async def ocah_axi_lite_write_pair_skew_test(dut) -> None:
    await start_clock_reset(dut)
    master, slave = build_lite_stack(dut)
    await master.start()
    seq = master.sequence
    rng = scenario_rng("write_pair_skew")

    n_ops = int(os.environ.get("OCAH_AXI_LITE_PAIR_OPS", "10"))
    log.info("=" * 70)
    log.info("AXI-Lite paired write with skew: %d randomized ops plus directed corners", n_ops)
    log.info("=" * 70)

    # Unique word addresses for every pair so a misrouted beat is visible.
    addrs: list[int] = []
    while len(addrs) < 2 * (n_ops + len(DIRECTED_CORNERS)) + 1:
        addr = rng.randrange(0, 2**14) & ~0x3
        if addr not in addrs:
            addrs.append(addr)

    index = 0
    for aw_delay, w_delay, b_delay, aw_stall in DIRECTED_CORNERS:
        await run_paired_write(
            dut,
            seq,
            slave,
            index=index,
            addr_a=addrs[2 * index],
            data_a=rng.getrandbits(32),
            addr_b=addrs[2 * index + 1],
            data_b=rng.getrandbits(32),
            aw_delay=aw_delay,
            w_delay=w_delay,
            b_delay=b_delay,
            aw_stall=aw_stall,
        )
        index += 1

    for _ in range(n_ops):
        await run_paired_write(
            dut,
            seq,
            slave,
            index=index,
            addr_a=addrs[2 * index],
            data_a=rng.getrandbits(32),
            addr_b=addrs[2 * index + 1],
            data_b=rng.getrandbits(32),
            aw_delay=rng.randrange(0, 8),
            w_delay=rng.randrange(0, 8),
            b_delay=rng.randrange(0, 5),
            aw_stall=rng.randrange(0, 4),
        )
        index += 1

    # A plain write afterwards proves the pair path leaves no pause or
    # backpressure behind.
    slave.sequence.disable_backpressure()
    last = addrs[-1]
    data = rng.getrandbits(32)
    wres = await seq.write_result(last, data)
    assert wres.ok and slave.sequence.read32(last) == data, (
        f"post-pair plain write failed: resp=0x{wres.resp:x}"
    )

    stats = seq.get_statistics()
    log.info("done: %d paired writes + 1 plain write, sequence stats=%s", index, stats)
    assert stats["write_transactions"] == 2 * index + 1
