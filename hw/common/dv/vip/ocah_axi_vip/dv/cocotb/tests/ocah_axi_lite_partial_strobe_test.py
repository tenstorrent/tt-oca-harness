# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI-Lite VIP selftest: contiguous partial write strobes.

AXI4-Lite write strobes select which byte lanes of WDATA are written
(IHI 0022). The lite master maps a contiguous partial ``strb`` onto a
sub-word access; this test judges the mapping at the wires (observed WSTRB,
AWADDR, and enabled WDATA lanes), checks the byte-merge result through both
the bus and the responder backdoor, and pins the rejection of patterns the
mapping cannot express (zero and non-contiguous strobes).
"""

from __future__ import annotations

import logging
import os
import random

import cocotb
from ocah_axi_vip_harness import (
    build_lite_stack,
    handshake_cycle,
    observe_lite_write,
    start_clock_reset,
)

log = logging.getLogger("cocotb.tb.ocah_axi_lite_partial_strobe_test")

# All contiguous nonzero strobe patterns of a 4-byte lane: offset 0..3,
# length 1..(4-offset).
CONTIGUOUS_STROBES = [
    ((1 << length) - 1) << offset for offset in range(4) for length in range(1, 5 - offset)
]


def strobe_merge(base: int, data: int, strb: int) -> int:
    """Expected 32-bit word after a strobed write of ``data`` over ``base``."""
    merged = base
    for lane in range(4):
        if (strb >> lane) & 1:
            byte_mask = 0xFF << (8 * lane)
            merged = (merged & ~byte_mask) | (data & byte_mask)
    return merged


async def run_strobed_write(dut, seq, slave, *, index: int, addr: int, strb: int) -> None:
    """Preload a word over the bus, overwrite selected lanes, judge every view."""
    base = random.getrandbits(32)
    data = random.getrandbits(32)
    expected = strobe_merge(base, data, strb)
    offset = (strb & -strb).bit_length() - 1
    log.info(
        "op %d: addr=0x%08x strb=0x%x base=0x%08x data=0x%08x expected=0x%08x",
        index,
        addr,
        strb,
        base,
        data,
        expected,
    )

    wres = await seq.write_result(addr, base)
    assert wres.ok, f"op {index}: preload write resp=0x{wres.resp:x}"

    observer = cocotb.start_soon(observe_lite_write(dut))
    wres = await seq.write_result(addr, data, strb=strb)
    samples = await observer
    assert wres.ok, f"op {index}: strobed write resp=0x{wres.resp:x}"
    assert wres.address == addr and wres.length == bin(strb).count("1"), (
        f"op {index}: result address=0x{wres.address:08x} length={wres.length} "
        f"for addr=0x{addr:08x} strb=0x{strb:x}"
    )

    # Wire view: the W beat must carry exactly the requested strobe, the AW
    # address must carry the documented sub-word mapping, and every enabled
    # WDATA lane must carry the corresponding byte of ``data``.
    aw_hs = handshake_cycle(samples, "awvalid", "awready")
    w_hs = handshake_cycle(samples, "wvalid", "wready")
    assert aw_hs is not None and w_hs is not None, f"op {index}: incomplete write on the wire"
    observed_awaddr = samples[aw_hs]["awaddr"]
    observed_wstrb = samples[w_hs]["wstrb"]
    observed_wdata = samples[w_hs]["wdata"]
    log.info(
        "op %d: observed awaddr=0x%08x wstrb=0x%x wdata=0x%08x",
        index,
        observed_awaddr,
        observed_wstrb,
        observed_wdata,
    )
    assert observed_wstrb == strb, (
        f"op {index}: wire WSTRB 0x{observed_wstrb:x} != requested 0x{strb:x}"
    )
    assert observed_awaddr == addr + offset, (
        f"op {index}: wire AWADDR 0x{observed_awaddr:08x} != 0x{addr + offset:08x} "
        f"(sub-word mapping of strb=0x{strb:x})"
    )
    for lane in range(4):
        if (strb >> lane) & 1:
            observed_byte = (observed_wdata >> (8 * lane)) & 0xFF
            expected_byte = (data >> (8 * lane)) & 0xFF
            assert observed_byte == expected_byte, (
                f"op {index}: WDATA lane {lane} carries 0x{observed_byte:02x}, "
                f"expected 0x{expected_byte:02x}"
            )

    # Memory view: bus readback and responder backdoor must both show the
    # byte merge, so a wire-only pass cannot mask a data defect.
    readback = await seq.read(addr)
    backdoor = slave.sequence.read32(addr)
    assert readback == expected, (
        f"op {index}: readback 0x{readback:08x} != expected 0x{expected:08x} "
        f"(base=0x{base:08x} data=0x{data:08x} strb=0x{strb:x})"
    )
    assert backdoor == expected, (
        f"op {index}: backdoor 0x{backdoor:08x} != expected 0x{expected:08x}"
    )


@cocotb.test()
async def ocah_axi_lite_partial_strobe_test(dut) -> None:
    await start_clock_reset(dut)
    master, slave = build_lite_stack(dut)
    await master.start()
    seq = master.sequence

    n_ops = int(os.environ.get("OCAH_AXI_LITE_STROBE_OPS", "8"))
    log.info("=" * 70)
    log.info(
        "AXI-Lite partial strobes: deterministic sweep of %d patterns plus %d randomized ops",
        len(CONTIGUOUS_STROBES),
        n_ops,
    )
    log.info("=" * 70)

    # Deterministic sweep: every contiguous pattern of the 4-byte lane, so
    # no offset/length combination depends on the random draw.
    index = 0
    for strb in CONTIGUOUS_STROBES:
        addr = random.randrange(0, 2**14) & ~0x3
        await run_strobed_write(dut, seq, slave, index=index, addr=addr, strb=strb)
        index += 1

    # Randomized sweep across patterns and addresses.
    for _ in range(n_ops):
        addr = random.randrange(0, 2**14) & ~0x3
        strb = random.choice(CONTIGUOUS_STROBES)
        await run_strobed_write(dut, seq, slave, index=index, addr=addr, strb=strb)
        index += 1

    # write() forwards strb and returns only the response code.
    addr = random.randrange(0, 2**14) & ~0x3
    await seq.write(addr, 0xA5A5A5A5)
    resp = await seq.write(addr, 0xFFFF00FF, strb=0x2)
    assert resp == 0 and slave.sequence.read32(addr) == 0xA5A500A5, (
        f"write() strb path: resp={resp} word=0x{slave.sequence.read32(addr):08x}"
    )

    # Patterns the sub-word mapping cannot express must be rejected before
    # any bus activity.
    for bad_strb in (0x0, 0x5, 0x9, 0xB, 0x1F):
        try:
            await seq.write_result(addr, 0, strb=bad_strb)
        except ValueError as exc:
            log.info("strb=0x%x rejected as expected: %s", bad_strb, exc)
        else:
            raise AssertionError(f"strb=0x{bad_strb:x} must be rejected")

    stats = seq.get_statistics()
    log.info("done: %d strobed ops, sequence stats=%s", index, stats)
