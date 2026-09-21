# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log Engine transfers: multi-beat logs, arbitration, pacing, clamping.

Scenarios:

1. Multi-beat transfer — a random slot moves a random length spanning
   several fetch beats, including a partial last beat, byte-exact.
2. All slots pending — every slot is armed back to back with its own random
   length; the UART stream must be a concatenation of whole slot payloads
   (no interleaving inside a log) and every length register clears.
3. UART pacing — uart_tx_ready toggles randomly during a long transfer and
   the stream stays byte-exact.
4. Length clamp — a length above the slot capacity moves exactly the
   capacity, rounded down to whole fetch beats.
5. Unaligned region — a region size that is not a multiple of the slot
   alignment is unsupported programming the engine keeps safe: a slot armed
   for its whole stride moves only the stride rounded down to whole beats.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from log_engine_base_test import (
    CYCLES_PER_BYTE,
    FETCH_BEAT_BYTES,
    LOG_CTRL_ADDRS,
    LOG_LEN_MAX,
    LOG_REGION_ALIGNMENT,
    NUM_LOG_ENTRIES,
    LogEngineTb,
    random_seed,
    slot_capacity,
    slot_stride,
)


def partition_stream(stream: list[int], payloads: dict[int, bytes]) -> list[int]:
    """Split the stream into whole payloads; returns the slot order observed."""
    order: list[int] = []
    pending = dict(payloads)
    pos = 0
    while pos < len(stream):
        match = None
        for index, payload in pending.items():
            if stream[pos : pos + len(payload)] == list(payload):
                match = index
                break
        assert match is not None, (
            f"stream position {pos}: no pending slot payload matches "
            f"{bytes(stream[pos : pos + 8]).hex()}...; remaining slots {sorted(pending)}"
        )
        order.append(match)
        pos += len(pending.pop(match))
    assert not pending, f"slots {sorted(pending)} never appeared in the UART stream"
    return order


async def pace_uart(dut, stop: list[bool]) -> None:
    """Randomly withhold uart_tx_ready until told to stop."""
    while not stop:
        dut.uart_tx_ready.value = 0
        await ClockCycles(dut.clk, random.randint(1, 40))
        dut.uart_tx_ready.value = 1
        await ClockCycles(dut.clk, random.randint(1, 20))
    dut.uart_tx_ready.value = 1


@cocotb.test()
async def log_engine_transfer_test(dut) -> None:
    tb = LogEngineTb(dut, name="log_engine_transfer_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    region_size = 32 * LOG_REGION_ALIGNMENT
    capacity = slot_capacity(region_size)
    await tb.configure(region_size=region_size)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: multi-beat transfer with a partial last beat")
    tb.log.info("=" * 70)
    index = random.randrange(NUM_LOG_ENTRIES)
    length = random.randint(FETCH_BEAT_BYTES + 1, capacity)
    if length % FETCH_BEAT_BYTES == 0:
        length -= 1
    payload = random.randbytes(length)
    stream = await tb.transfer(index, payload, f"slot {index} x{length}")
    assert stream == list(payload), (
        f"slot {index}: {length} bytes, mismatch at {next(i for i, (a, b) in enumerate(zip(stream, payload)) if a != b) if len(stream) == length else f'length {len(stream)}'}"
    )
    tb.log.info(
        "slot %d moved %d bytes (%d beats + %d) byte-exact",
        index,
        length,
        length // FETCH_BEAT_BYTES,
        length % FETCH_BEAT_BYTES,
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: every slot armed back to back")
    tb.log.info("=" * 70)
    payloads = {i: random.randbytes(random.randint(1, capacity)) for i in range(NUM_LOG_ENTRIES)}
    for i, data in payloads.items():
        tb.load_slot(i, data)
    tb.written.clear()
    for i, data in payloads.items():
        await tb.arm(i, len(data))
    total = sum(len(data) for data in payloads.values())
    for i in range(NUM_LOG_ENTRIES):
        await tb.wait_done(i, CYCLES_PER_BYTE * total + 400, "all slots")
    await ClockCycles(dut.clk, 20)
    stream = tb.drain_written()
    assert len(stream) == total, (
        f"all slots: expected {total} bytes on the UART sink, observed {len(stream)}"
    )
    order = partition_stream(stream, payloads)
    tb.log.info(
        "%d bytes from %d slots arrived as whole logs in order %s", total, NUM_LOG_ENTRIES, order
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: uart_tx_ready pacing")
    tb.log.info("=" * 70)
    index = random.randrange(NUM_LOG_ENTRIES)
    payload = random.randbytes(capacity)
    stop: list[bool] = []
    pacer = cocotb.start_soon(pace_uart(dut, stop))
    tb.load_slot(index, payload)
    tb.written.clear()
    await tb.arm(index, len(payload))
    await tb.wait_done(index, 60 * CYCLES_PER_BYTE * len(payload), "paced")
    stop.append(True)
    await pacer
    await ClockCycles(dut.clk, 20)
    stream = tb.drain_written()
    assert stream == list(payload), (
        f"paced: {len(payload)} bytes, UART sink saw {len(stream)} with mismatches"
    )
    tb.log.info(
        "slot %d moved %d bytes byte-exact under random uart_tx_ready stalls", index, len(payload)
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: length above the slot capacity is clamped")
    tb.log.info("=" * 70)
    index = random.randrange(NUM_LOG_ENTRIES)
    payload = random.randbytes(capacity)
    length = min(capacity + random.randint(1, 3 * FETCH_BEAT_BYTES), LOG_LEN_MAX)
    stream = await tb.transfer(index, payload, f"clamp {length}", length=length)
    assert stream == list(payload), (
        f"clamp: armed {length} on a {capacity}-byte slot, UART sink saw {len(stream)} bytes"
    )
    tb.log.info("armed %d bytes on a %d-byte slot: exactly the capacity moved", length, capacity)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 5: unaligned region size")
    tb.log.info("=" * 70)
    # A slot stride that is not a whole number of fetch beats.
    stride = 2 * LOG_REGION_ALIGNMENT + random.randrange(1, 64)
    if stride % FETCH_BEAT_BYTES == 0:
        stride += 1
    region_size = stride * NUM_LOG_ENTRIES
    await tb.configure(region_size=region_size)
    assert slot_stride(region_size) == stride
    capacity = slot_capacity(region_size)
    assert capacity < stride, f"region {region_size}: stride {stride} is beat aligned"
    slots = random.sample(range(NUM_LOG_ENTRIES), 2)
    for i in slots:
        stream = await tb.transfer(i, random.randbytes(stride), f"unaligned slot {i}")
        assert len(stream) == capacity, (
            f"unaligned slot {i} (base 0x{tb.region_addr + stride * i:x}): armed {stride} bytes, "
            f"{len(stream)} moved, capacity {capacity}"
        )
    for i, addr in enumerate(LOG_CTRL_ADDRS):
        assert await tb.read(addr) == 0, f"LOG_CTRL[{i}] not clear after the unaligned transfers"
    tb.log.info(
        "region %d: slot stride %d, exactly %d bytes per transfer on slots %s",
        region_size,
        stride,
        capacity,
        slots,
    )

    tb.log.info("log_engine_transfer_test PASSED (seed=%d)", seed)
