# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI-Lite VIP selftest: two outstanding reads under an RREADY hold.

``read_pair_hold_result`` claims to present the second AR while the first
response is held, to return both responses in issue order, and to report the
AR channel's stall cycles and stability across the pair. Every claim is
judged against a per-cycle wire recording of the l_axi nets: the stall count
and the address stability must match the wires, with and without the
responder stalling ARREADY, and the hold must keep RVALID/RDATA/RRESP
stable. Data integrity is cross-checked through the lite
slave's backdoor preload so an ordering-only pass cannot mask a misrouted
response.
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
    observe_lite_read,
    scenario_rng,
    stall_cycles,
    start_clock_reset,
)

log = logging.getLogger("cocotb.tb.ocah_axi_lite_read_pair_hold_test")

# Directed (hold_cycles, ar_stall_cycles) corners: a plain hold with a free
# responder, the degenerate zero hold, a long hold under ARREADY stalls, and
# the minimum of both.
DIRECTED_CORNERS = ((4, 0), (0, 0), (8, 3), (1, 1))


async def run_paired_read(
    dut,
    seq,
    slave,
    *,
    index: int,
    addr_a: int,
    addr_b: int,
    expected: dict[int, int],
    hold: int,
    ar_stall: int,
) -> None:
    """Issue one paired read and judge the wire recording against the request."""
    log.info(
        "op %d: a=0x%08x b=0x%08x hold_cycles=%d ar_stall=%d", index, addr_a, addr_b, hold, ar_stall
    )
    if ar_stall > 0:
        slave.sequence.enable_backpressure(channels=("ar",), stall_cycles=ar_stall)
    else:
        slave.sequence.disable_backpressure()
    observer = cocotb.start_soon(observe_lite_read(dut, handshakes=2))
    result = await seq.read_pair_hold_result(addr_a, addr_b, hold)
    samples = await observer

    assert result.ok, f"op {index}: resp a=0x{result.first.resp:x} b=0x{result.second.resp:x}"
    assert result.first.data == expected[addr_a] and result.second.data == expected[addr_b], (
        f"op {index}: data a=0x{result.first.data:08x} b=0x{result.second.data:08x} != preloaded "
        f"0x{expected[addr_a]:08x}/0x{expected[addr_b]:08x}"
    )
    assert result.first.hold_stable is True, (
        f"op {index}: VIP reported hold_stable={result.first.hold_stable} on the held read"
    )
    assert result.second.hold_stable is None, "the second read must not report a hold window"

    ar_hs = handshake_cycles(samples, "arvalid", "arready")
    r_hs = handshake_cycles(samples, "rvalid", "rready")
    rvalid_first = first_cycle(samples, "rvalid")
    assert len(ar_hs) == 2 and len(r_hs) == 2 and rvalid_first is not None, (
        f"op {index}: incomplete pair on the wire: ar_hs={ar_hs} r_hs={r_hs} rvalid={rvalid_first}"
    )
    assert [samples[c]["araddr"] for c in ar_hs] == [addr_a, addr_b], (
        f"op {index}: AR order on the wire {[hex(samples[c]['araddr']) for c in ar_hs]}"
    )

    # The VIP's AR observation must equal the wire recording: the stall count,
    # and VALID/ARADDR held through every stall (IHI 0022 A3.2.1).
    wire_stall = stall_cycles(samples, "arvalid", "arready")
    log.info(
        "op %d: ar_hs=%s r_hs=%s rvalid@%d wire_stall=%d vip_stall=%d vip_stable=%s",
        index,
        ar_hs,
        r_hs,
        rvalid_first,
        wire_stall,
        result.ar_stall_cycles,
        result.ar_stable,
    )
    assert result.ar_stall_cycles == wire_stall, (
        f"op {index}: VIP ar_stall_cycles={result.ar_stall_cycles} != wire {wire_stall}"
    )
    assert result.ar_stable and address_stable_while_stalled(
        samples, "arvalid", "arready", "araddr"
    ), f"op {index}: AR channel changed while stalled (vip_stable={result.ar_stable})"
    if ar_stall > 0:
        assert wire_stall > 0, f"op {index}: ARREADY stalls requested but none observed"
    else:
        assert ar_hs[1] <= r_hs[0], (
            f"op {index}: second AR accepted at {ar_hs[1]} after the first R handshake {r_hs[0]}"
        )

    # The first accept trails RVALID by at least the requested hold with the
    # responder holding RVALID/RDATA/RRESP stable for the whole wait.
    assert r_hs[0] - rvalid_first >= hold, (
        f"op {index}: RREADY accepted {r_hs[0] - rvalid_first} cycles after RVALID, hold {hold}"
    )
    window = samples[rvalid_first : r_hs[0] + 1]
    assert all(row["rvalid"] for row in window), f"op {index}: RVALID dropped during the hold"
    assert len({(row["rdata"], row["rresp"]) for row in window}) == 1, (
        f"op {index}: RDATA/RRESP changed during the hold window"
    )


@cocotb.test()
async def ocah_axi_lite_read_pair_hold_test(dut) -> None:
    await start_clock_reset(dut)
    master, slave = build_lite_stack(dut)
    await master.start()
    seq = master.sequence
    rng = scenario_rng("read_pair_hold")

    n_ops = int(os.environ.get("OCAH_AXI_LITE_PAIR_OPS", "10"))
    log.info("=" * 70)
    log.info(
        "AXI-Lite paired read under RREADY hold: %d randomized ops plus directed corners", n_ops
    )
    log.info("=" * 70)

    # Preload the responder memory with unique random words at unique addresses.
    preload: dict[int, int] = {}
    while len(preload) < 2 * (n_ops + len(DIRECTED_CORNERS)) + 1:
        preload[rng.randrange(0, 2**14) & ~0x3] = rng.getrandbits(32)
    for addr, data in preload.items():
        slave.sequence.write32(addr, data)
    addrs = list(preload)

    index = 0
    for hold, ar_stall in DIRECTED_CORNERS:
        await run_paired_read(
            dut,
            seq,
            slave,
            index=index,
            addr_a=addrs[2 * index],
            addr_b=addrs[2 * index + 1],
            expected=preload,
            hold=hold,
            ar_stall=ar_stall,
        )
        index += 1

    for _ in range(n_ops):
        await run_paired_read(
            dut,
            seq,
            slave,
            index=index,
            addr_a=addrs[2 * index],
            addr_b=addrs[2 * index + 1],
            expected=preload,
            hold=rng.randrange(1, 9),
            ar_stall=rng.randrange(0, 5),
        )
        index += 1

    # A plain read afterwards proves the pair path leaves no pause or
    # backpressure behind.
    slave.sequence.disable_backpressure()
    last = addrs[-1]
    rres = await seq.read_result(last)
    assert rres.ok and rres.data == preload[last], (
        f"post-pair plain read failed: resp=0x{rres.resp:x} data=0x{rres.data:08x}"
    )
    assert rres.hold_stable is None, "plain read must not report a hold window"

    stats = seq.get_statistics()
    log.info("done: %d paired reads + 1 plain read, sequence stats=%s", index, stats)
    assert stats["read_transactions"] == 2 * index + 1
