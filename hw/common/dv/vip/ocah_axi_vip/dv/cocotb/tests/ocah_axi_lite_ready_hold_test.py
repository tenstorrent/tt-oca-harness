# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI-Lite VIP selftest: delayed RREADY with response-stability check.

AXI requires the responder to hold RVALID with RDATA/RRESP unchanged until
the master accepts (IHI 0022, valid-before-ready). ``read_hold_result``
claims to withhold RREADY for the requested cycles and to report that
stability window in ``hold_stable``; both claims are judged against a
per-cycle wire recording of the l_axi nets. The hold path is also exercised
across a non-OKAY response (RRESP stability, not just RDATA).
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
    observe_lite_read,
    start_clock_reset,
)

log = logging.getLogger("cocotb.tb.ocah_axi_lite_ready_hold_test")

RESP_SLVERR = 0b10


async def run_held_read(
    dut, seq, *, index: int, addr: int, expected: int, hold: int, expect_resp_ok: bool = True
) -> None:
    """Issue one held read and judge the wire recording against the request."""
    log.info(
        "op %d: addr=0x%08x expected=0x%08x hold_cycles=%d expect_ok=%s",
        index,
        addr,
        expected,
        hold,
        expect_resp_ok,
    )
    observer = cocotb.start_soon(observe_lite_read(dut))
    result = await seq.read_hold_result(addr, hold, check_response=expect_resp_ok)
    samples = await observer

    assert result.hold_stable is True, (
        f"op {index}: VIP reported hold_stable={result.hold_stable} against the RAM responder"
    )
    if expect_resp_ok:
        assert result.ok, f"op {index}: read resp=0x{result.resp:x} addr=0x{addr:08x}"
        assert result.data == expected, (
            f"op {index}: read data 0x{result.data:08x} != preloaded 0x{expected:08x} "
            f"at 0x{addr:08x}"
        )
    else:
        assert result.resp == RESP_SLVERR, (
            f"op {index}: injected SLVERR not observed, resp=0x{result.resp:x}"
        )

    rvalid_first = first_cycle(samples, "rvalid")
    r_hs = handshake_cycle(samples, "rvalid", "rready")
    assert rvalid_first is not None and r_hs is not None, (
        f"op {index}: incomplete read on the wire: rvalid={rvalid_first} r_hs={r_hs}"
    )

    # The accept must trail RVALID by at least the requested hold, and the
    # responder must have held RVALID/RDATA/RRESP stable for the whole wait —
    # checked at the wires, independent of the VIP's own hold_stable claim.
    deferral = r_hs - rvalid_first
    log.info(
        "op %d: observed rvalid@%d handshake@%d (deferral=%d)", index, rvalid_first, r_hs, deferral
    )
    assert deferral >= hold, (
        f"op {index}: RREADY accepted {deferral} cycles after RVALID, requested hold {hold}"
    )
    window = samples[rvalid_first : r_hs + 1]
    assert all(row["rvalid"] for row in window), (
        f"op {index}: RVALID dropped during the hold window"
    )
    assert len({(row["rdata"], row["rresp"]) for row in window}) == 1, (
        f"op {index}: RDATA/RRESP changed during the hold window: "
        f"{[(hex(row['rdata']), row['rresp']) for row in window]}"
    )


@cocotb.test()
async def ocah_axi_lite_ready_hold_test(dut) -> None:
    await start_clock_reset(dut)
    master, slave = build_lite_stack(dut)
    await master.start()
    seq = master.sequence

    n_ops = int(os.environ.get("OCAH_AXI_LITE_HOLD_OPS", "10"))
    log.info("=" * 70)
    log.info("AXI-Lite RREADY hold: %d randomized ops plus directed corners", n_ops)
    log.info("=" * 70)

    # Preload the responder memory (the reference the reads are judged
    # against) with unique random words.
    preload = {}
    while len(preload) < n_ops + 3:
        addr = random.randrange(0, 2**14) & ~0x3
        preload[addr] = random.getrandbits(32)
    for addr, data in preload.items():
        slave.sequence.write32(addr, data)
    addrs = list(preload)

    # Directed corners: minimum hold, zero hold (degenerate plain read), and
    # a long hold.
    index = 0
    for hold in (1, 0, 12):
        addr = addrs[index]
        await run_held_read(dut, seq, index=index, addr=addr, expected=preload[addr], hold=hold)
        index += 1

    # Randomized hold sweep.
    for _ in range(n_ops):
        addr = random.choice(addrs)
        hold = random.randrange(1, 9)
        await run_held_read(dut, seq, index=index, addr=addr, expected=preload[addr], hold=hold)
        index += 1

    # RRESP stability across the hold: a one-shot injected SLVERR must stay
    # SLVERR for the whole window and reach the result unchanged.
    err_addr = addrs[0]
    slave.sequence.inject_error(err_addr, RESP_SLVERR, read=True, write=False)
    await run_held_read(
        dut,
        seq,
        index=index,
        addr=err_addr,
        expected=preload[err_addr],
        hold=4,
        expect_resp_ok=False,
    )
    index += 1
    slave.sequence.clear_errors()

    # A plain read afterwards proves the hold path leaves no pause behind and
    # the injected error was one-shot.
    rres = await seq.read_result(err_addr)
    assert rres.ok and rres.data == preload[err_addr], (
        f"post-hold plain read failed: resp=0x{rres.resp:x} data=0x{rres.data:08x}"
    )
    assert rres.hold_stable is None, "plain read must not report a hold window"

    stats = seq.get_statistics()
    log.info("done: %d held reads + 1 plain read, sequence stats=%s", index, stats)
    assert stats["read_transactions"] == index + 1
