# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART wrapper serial lines and log paths, instance by instance.

Scenarios:

1. Transmit — a character written to each instance's THR appears on that
   instance's tx pin as a clean 8N1 frame while every other tx pin stays
   idle.
2. Receive — a character driven on each instance's rx pin lands in that
   instance's RBR, raises only that instance's received-data interrupt bit,
   and leaves the other instances' LSR.DR clear.
3. Log path — each instance's log engine, pointed at its own region of the
   shared fetch memory and at its own UART, drives its log onto its own tx
   pin; the fetch port is shared through the wrapper's mux.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from uart_wrap_base_test import (
    FETCH_BEAT_BYTES,
    NUM_LOG_ENTRIES,
    NUM_UARTS,
    REG,
    REGION_ADDR,
    UartWrapTb,
    bit,
    random_seed,
    win,
)

REGION_SIZE = NUM_LOG_ENTRIES * 32  # 32-byte slots per engine
REGION_STRIDE = 0x1000  # one region per instance in the fetch memory


@cocotb.test()
async def uart_wrap_line_test(dut) -> None:
    tb = UartWrapTb(dut, name="uart_wrap_line_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    for index in range(NUM_UARTS):
        await tb.configure_uart(index)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: THR -> own tx pin, other lines idle")
    tb.log.info("=" * 70)
    for index in random.sample(range(NUM_UARTS), NUM_UARTS):
        char = random.getrandbits(8)
        await tb.write(win(index, "UART_RBR_REG_ADDR"), char)
        frames = await tb.expect_frames(index, 1, f"uart{index} tx")
        assert frames[0].data == char, (
            f"uart{index}: wrote 0x{char:02x}, tx carried 0x{frames[0].data:02x}"
        )
        busy = tb.idle_lines(index)
        assert not busy, f"uart{index} transmit disturbed tx lines {busy}"
        for other in range(NUM_UARTS):
            if other != index:
                assert tb.line_samplers[other].count() == 0, (
                    f"uart{other} sampled a frame while uart{index} transmitted"
                )
        tb.log.info(
            "uart%d: 0x%02x on its own tx; the other %d lines stayed idle",
            index,
            char,
            NUM_UARTS - 1,
        )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: rx pin -> own RBR and interrupt bit")
    tb.log.info("=" * 70)
    for index in range(NUM_UARTS):
        ier = REG.UART_16550_MAIN_IER_reg_u()
        ier.f.erbfi = 1
        await tb.write(win(index, "UART_IER_REG_ADDR"), ier.val)
    for index in random.sample(range(NUM_UARTS), NUM_UARTS):
        char = random.getrandbits(8)
        await tb.line_drivers[index].write([char])
        await tb.wait_data_ready(index, f"uart{index} rx")
        await ClockCycles(dut.clk, 4)
        irq = int(dut.uart_irq.value)
        assert irq == (1 << index), (
            f"uart_irq 0b{irq:0{NUM_UARTS}b} while only uart{index} holds data"
        )
        for other in range(NUM_UARTS):
            if other != index:
                lsr = await tb.read_u(
                    REG.UART_16550_MAIN_LSR_reg_u, win(other, "UART_LSR_REG_ADDR")
                )
                assert lsr.f.dr == 0, f"uart{other} reports data ready while uart{index} received"
        observed = await tb.read(win(index, "UART_RBR_REG_ADDR"))
        assert observed == char, f"uart{index}: drove 0x{char:02x}, RBR read 0x{observed:02x}"
        await ClockCycles(dut.clk, 4)
        assert bit(dut.uart_irq, index) == 0, f"uart{index} interrupt still pending after RBR read"
        tb.log.info(
            "uart%d: 0x%02x received on its own line, interrupt bit %d only", index, char, index
        )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: each log engine drives its own UART through the shared fetch port")
    tb.log.info("=" * 70)
    for index in range(NUM_UARTS):
        await tb.write(win(index, "UART_IER_REG_ADDR"), 0)
        await tb.configure_log_engine(
            index, REGION_SIZE, region_addr=REGION_ADDR + REGION_STRIDE * index
        )
    capacity = (REGION_SIZE // NUM_LOG_ENTRIES // FETCH_BEAT_BYTES) * FETCH_BEAT_BYTES
    payloads = {}
    for index in range(NUM_UARTS):
        slot = random.randrange(NUM_LOG_ENTRIES)
        payload = random.randbytes(random.randint(9, capacity))
        base = REGION_ADDR + REGION_STRIDE * index + (REGION_SIZE // NUM_LOG_ENTRIES) * slot
        tb.fetch_ram.write(base, payload)
        payloads[index] = (slot, payload)
        tb.line_samplers[index].clear()
    for index, (slot, payload) in payloads.items():
        await tb.write(win(index, f"LOG_ENGINE_LOG_CTRL_{slot}__REG_ADDR"), len(payload))
    for index, (slot, payload) in payloads.items():
        frames = await tb.expect_frames(index, len(payload), f"uart{index} log", slack_frames=8)
        observed = [frame.data for frame in frames]
        assert observed == list(payload), (
            f"uart{index} slot {slot}: line carried {bytes(observed).hex()}"
        )
        remaining = await tb.read(win(index, f"LOG_ENGINE_LOG_CTRL_{slot}__REG_ADDR"))
        assert remaining == 0, f"uart{index} slot {slot} still reports {remaining} bytes"
        status = await tb.read(win(index, "LOG_ENGINE_INTR_STATUS_REG_ADDR"))
        assert status == 0, f"uart{index} log engine INTR_STATUS 0x{status:x}"
        tb.log.info("uart%d: slot %d moved %d bytes onto its own tx pin", index, slot, len(payload))
    assert int(dut.log_engine_irq.value) == 0, (
        f"log_engine_irq 0b{int(dut.log_engine_irq.value):0{NUM_UARTS}b}"
    )

    tb.log.info("uart_wrap_line_test PASSED (seed=%d)", seed)
