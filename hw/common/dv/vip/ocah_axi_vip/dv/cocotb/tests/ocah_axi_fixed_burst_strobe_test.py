# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI VIP selftest: a narrow FIXED burst keeps its byte lanes.

A FIXED burst repeats one address on every beat, so every W beat drives
the byte lanes of that address and every R beat carries them (IHI 0022
A3.4.1 and A3.4.3). On the 32-bit ``s_axi`` stack the master issues a
four-beat, one-byte FIXED write at word offset 1 and a four-beat FIXED read
of the same byte. The test judges WSTRB and the WDATA lane on every beat at
the wires, the responder word through the backdoor (the last beat's byte
lands, the other three bytes keep the preload), and the bytes the read
returns (every beat is the stored byte). A master that rotates its lanes
on FIXED bursts fails the strobe, data and read checks.
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from ocah_axi_vip_harness import build_full_stack, scenario_rng, start_clock_reset
from ocah_checker import OcahChecker

log = logging.getLogger("cocotb.tb.ocah_axi_fixed_burst_strobe_test")

CHK_STRB = "CHK-AXI-FIXED-STRB-LANES"
CHK_WDATA = "CHK-AXI-FIXED-WDATA-LANE"
CHK_RESP = "CHK-AXI-FIXED-WRITE-RESP"
CHK_MEM = "CHK-AXI-FIXED-MEM-BYTE"
CHK_READ = "CHK-AXI-FIXED-READ-LANES"
CTRL_BEATS = "CHK-AXI-FIXED-BEATS"

BURST_FIXED = 0
BEATS = 4
LANE = 1
WORD = 0x1000
ADDR = WORD + LANE
WATCH_CYCLES = 400


def _high(handle) -> bool:
    value = handle.value
    return value.is_resolvable and bool(int(value))


async def observe_w_beats(dut, count: int) -> list[tuple[int, int]]:
    """Collect (wstrb, wdata) of the next ``count`` W handshakes on s_axi."""
    beats: list[tuple[int, int]] = []
    for _ in range(WATCH_CYCLES):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if _high(dut.s_axi_wvalid) and _high(dut.s_axi_wready):
            beats.append((int(dut.s_axi_wstrb.value), int(dut.s_axi_wdata.value)))
            if len(beats) == count:
                break
    return beats


@cocotb.test()
async def ocah_axi_fixed_burst_strobe_test(dut) -> None:
    await start_clock_reset(dut)
    master, slave = build_full_stack(dut)
    await master.start()
    seq = master.sequence
    rng = scenario_rng("fixed_burst_strobe")
    checker = OcahChecker(
        name="ocah_axi_fixed_burst_strobe",
        required_ids=(CHK_STRB, CHK_WDATA, CHK_RESP, CHK_MEM, CHK_READ, CTRL_BEATS),
        logger=log,
    )

    base = rng.getrandbits(32)
    payload = [rng.getrandbits(8) for _ in range(BEATS)]
    log.info(
        "FIXED burst: addr=0x%08x size=0 beats=%d base=0x%08x bytes=%s",
        ADDR,
        BEATS,
        base,
        " ".join(f"{b:02x}" for b in payload),
    )

    preload = await seq.write_result(WORD, base)
    assert preload.ok, f"preload write resp=0x{preload.resp:x}"

    observer = cocotb.start_soon(observe_w_beats(dut, BEATS))
    wres = await seq.burst_write_result(ADDR, payload, size=0, burst=BURST_FIXED)
    beats = await observer

    checker.expect_equal(CTRL_BEATS, len(beats), BEATS, context="W handshakes observed")
    checker.expect_true(CHK_RESP, wres.ok, context=f"resp=0x{wres.resp:x}")
    expected_strb = 1 << LANE
    for index, (strb, wdata) in enumerate(beats):
        checker.expect_equal(
            CHK_STRB, strb, expected_strb, context=f"beat {index} wstrb=0x{strb:x}"
        )
        lane_byte = (wdata >> (8 * LANE)) & 0xFF
        checker.expect_equal(
            CHK_WDATA,
            lane_byte,
            payload[index],
            context=f"beat {index} wdata lane {LANE}",
        )

    expected_word = (base & ~(0xFF << (8 * LANE))) | (payload[-1] << (8 * LANE))
    checker.expect_equal(
        CHK_MEM,
        slave.sequence.read32(WORD),
        expected_word,
        context="responder word after the FIXED burst",
    )

    rres = await seq.burst_read_result(ADDR, BEATS, size=0, burst=BURST_FIXED)
    read_bytes = list(rres.data_words)
    checker.expect_equal(
        CHK_READ,
        read_bytes,
        [payload[-1]] * BEATS,
        context="bytes a FIXED read returns, one per beat",
    )

    checker.finalize()
    await master.stop()
