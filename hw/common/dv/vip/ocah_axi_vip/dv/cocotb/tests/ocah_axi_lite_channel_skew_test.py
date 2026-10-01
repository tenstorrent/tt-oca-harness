# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI-Lite VIP selftest: independent AW/W launch skew and deferred BREADY.

AXI4-Lite permits the AW and W channels to arrive in either order (IHI 0022,
single-beat writes), and a master may withhold BREADY as response
backpressure. ``write_skewed_result`` claims to hold the delayed channel's
VALID low for exactly the requested cycles and to defer the BREADY assert
after the request phase; every claim is judged against a per-cycle wire
recording of the l_axi nets, and data integrity is cross-checked through the
lite slave's backdoor so an ordering-only pass cannot mask a data defect.
"""

from __future__ import annotations

import logging
import os
import random

import cocotb
from ocah_axi_vip_harness import (
    build_lite_stack,
    first_cycle,
    handshake_cycle,
    observe_lite_write,
    start_clock_reset,
)

log = logging.getLogger("cocotb.tb.ocah_axi_lite_channel_skew_test")

# The launch pipeline (queue -> pause release -> VALID drive) adds at most one
# cycle of slack on the delayed channel; the skew must never be shorter than
# requested.
SKEW_SLACK_CYCLES = 1


async def run_skewed_write(
    dut, seq, slave, *, index: int, addr: int, data: int, aw_delay: int, w_delay: int, b_delay: int
) -> None:
    """Issue one skewed write and judge the wire recording against the request."""
    log.info(
        "op %d: addr=0x%08x data=0x%08x aw_valid_delay=%d w_valid_delay=%d b_ready_delay=%d",
        index,
        addr,
        data,
        aw_delay,
        w_delay,
        b_delay,
    )
    observer = cocotb.start_soon(observe_lite_write(dut))
    result = await seq.write_skewed_result(
        addr,
        data,
        aw_valid_delay=aw_delay,
        w_valid_delay=w_delay,
        b_ready_delay=b_delay,
    )
    samples = await observer

    assert result.ok, f"op {index}: skewed write resp=0x{result.resp:x} addr=0x{addr:08x}"
    backdoor = slave.sequence.read32(addr)
    assert backdoor == data, (
        f"op {index}: backdoor 0x{backdoor:08x} != written 0x{data:08x} at 0x{addr:08x}"
    )

    awvalid_first = first_cycle(samples, "awvalid")
    wvalid_first = first_cycle(samples, "wvalid")
    aw_hs = handshake_cycle(samples, "awvalid", "awready")
    w_hs = handshake_cycle(samples, "wvalid", "wready")
    bvalid_first = first_cycle(samples, "bvalid")
    assert None not in (awvalid_first, wvalid_first, aw_hs, w_hs, bvalid_first), (
        f"op {index}: incomplete write on the wire: awvalid={awvalid_first} "
        f"wvalid={wvalid_first} aw_hs={aw_hs} w_hs={w_hs} bvalid={bvalid_first}"
    )

    # The requested skew is the launch-cycle difference; the delayed channel
    # must trail by at least the request and by at most one slack cycle.
    skew = awvalid_first - wvalid_first
    requested = aw_delay - w_delay
    log.info(
        "op %d: observed awvalid@%d wvalid@%d (skew=%+d requested=%+d) aw_hs@%d w_hs@%d bvalid@%d",
        index,
        awvalid_first,
        wvalid_first,
        skew,
        requested,
        aw_hs,
        w_hs,
        bvalid_first,
    )
    if requested > 0:
        assert requested <= skew <= requested + SKEW_SLACK_CYCLES, (
            f"op {index}: AW launch skew {skew} outside [{requested}, "
            f"{requested + SKEW_SLACK_CYCLES}] (aw_valid_delay={aw_delay} w_valid_delay={w_delay})"
        )
    elif requested < 0:
        assert requested - SKEW_SLACK_CYCLES <= skew <= requested, (
            f"op {index}: W launch skew {skew} outside [{requested - SKEW_SLACK_CYCLES}, "
            f"{requested}] (aw_valid_delay={aw_delay} w_valid_delay={w_delay})"
        )
    else:
        assert abs(skew) <= SKEW_SLACK_CYCLES, (
            f"op {index}: equal delays must launch together, observed skew {skew}"
        )

    # BREADY deferral: after both request handshakes the accept must wait at
    # least b_ready_delay cycles (the release plus ready-drive pipeline may
    # add slack, never remove it). BREADY idles high between operations, so
    # the scan starts after the request phase.
    if b_delay > 0:
        request_done = max(aw_hs, w_hs)
        bready_live = first_cycle(samples, "bready", start=request_done + 1)
        assert bready_live is not None, f"op {index}: BREADY never rose after the request phase"
        assert bready_live - request_done >= b_delay, (
            f"op {index}: BREADY rose {bready_live - request_done} cycles after the request "
            f"phase, requested deferral {b_delay}"
        )
        log.info(
            "op %d: BREADY deferred %d cycles (requested %d)",
            index,
            bready_live - request_done,
            b_delay,
        )


@cocotb.test()
async def ocah_axi_lite_channel_skew_test(dut) -> None:
    await start_clock_reset(dut)
    master, slave = build_lite_stack(dut)
    await master.start()
    seq = master.sequence

    n_ops = int(os.environ.get("OCAH_AXI_LITE_SKEW_OPS", "10"))
    log.info("=" * 70)
    log.info("AXI-Lite channel skew: %d randomized ops plus directed corners", n_ops)
    log.info("=" * 70)

    # Directed corners: each arrival order alone, deferral alone, everything
    # at once, and the no-skew degenerate case.
    directed = [
        (0, 5, 0),  # AW first, W trails
        (5, 0, 0),  # W first, AW trails
        (0, 0, 4),  # deferral only
        (0, 0, 0),  # degenerate: plain single-beat write through the skew path
        (3, 3, 2),  # equal nonzero delays plus deferral
    ]
    index = 0
    for aw_delay, w_delay, b_delay in directed:
        addr = random.randrange(0, 2**14) & ~0x3
        data = random.getrandbits(32)
        await run_skewed_write(
            dut,
            seq,
            slave,
            index=index,
            addr=addr,
            data=data,
            aw_delay=aw_delay,
            w_delay=w_delay,
            b_delay=b_delay,
        )
        index += 1

    # Randomized sweep over both arrival orders and the deferral range.
    for _ in range(n_ops):
        aw_delay = random.randrange(0, 8)
        w_delay = random.randrange(0, 8)
        b_delay = random.randrange(0, 5)
        addr = random.randrange(0, 2**14) & ~0x3
        data = random.getrandbits(32)
        await run_skewed_write(
            dut,
            seq,
            slave,
            index=index,
            addr=addr,
            data=data,
            aw_delay=aw_delay,
            w_delay=w_delay,
            b_delay=b_delay,
        )
        index += 1

    # A plain write afterwards proves the skew path leaves no pause behind.
    addr = random.randrange(0, 2**14) & ~0x3
    data = random.getrandbits(32)
    wres = await seq.write_result(addr, data)
    assert wres.ok and slave.sequence.read32(addr) == data, (
        f"post-skew plain write failed: resp=0x{wres.resp:x}"
    )

    stats = seq.get_statistics()
    log.info("done: %d skewed ops + 1 plain write, sequence stats=%s", index, stats)
    assert stats["write_transactions"] == index + 1
