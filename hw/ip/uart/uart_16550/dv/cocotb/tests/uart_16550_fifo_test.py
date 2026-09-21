# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART 16550 FIFO and DMA-ready scenarios.

Scenarios:

1. TX FIFO — a random burst of up to TX_FIFO_DEPTH characters written back to
   back into THR leaves tx as clean frames in order, with LSR.TEMT set once
   the line is idle again.
2. RX FIFO — a random burst of up to RX_FIFO_DEPTH characters driven on rx
   drains from RBR in order with LSR.OE never set.
3. DMA mode 0 and mode 1 — in system loopback, characters are pushed only
   while txrdy is high and pulled only while rxrdy is high, in the non-FIFO
   and the FIFO DMA signalling modes.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from uart_16550_base_test import (
    MAIN,
    RX_FIFO_DEPTH,
    TX_FIFO_DEPTH,
    WO,
    DmaMode,
    Uart16550Tb,
    random_seed,
)


async def dma_transfer(tb: Uart16550Tb, mode: DmaMode, count: int) -> None:
    """Move ``count`` random characters through the loopback under DMA pacing."""
    dut = tb.dut
    fcr = WO.UART_16550_MAIN_WO_FCR_reg_u()
    fcr.f.fifo_enable = int(mode == DmaMode.MODE_1)
    fcr.f.dma_mode_select = int(mode)
    await tb.write(WO.FCR_REG_ADDR, fcr.val)

    tx_chars = [random.getrandbits(8) for _ in range(count)]
    rx_chars: list[int] = []
    sent = 0
    idle_polls = 0
    while len(rx_chars) < count:
        progressed = False
        if sent < count and int(dut.txrdy.value) == 1:
            await tb.write(WO.THR_REG_ADDR, tx_chars[sent])
            sent += 1
            progressed = True
        if int(dut.rxrdy.value) == 1:
            rx_chars.append(await tb.read(MAIN.RBR_REG_ADDR))
            progressed = True
        if not progressed:
            idle_polls += 1
            assert idle_polls < 8 * count + 16, (
                f"DMA {mode.name}: ready pins stalled after {sent} sent / {len(rx_chars)} received"
            )
            await ClockCycles(dut.clk, tb.fmt.frame_cycles)
    assert rx_chars == tx_chars, (
        f"DMA {mode.name}: sent {[hex(c) for c in tx_chars]}, received {[hex(c) for c in rx_chars]}"
    )
    tb.log.info(
        "DMA %s: %d characters paced by txrdy/rxrdy round-tripped in order", mode.name, count
    )


@cocotb.test()
async def uart_16550_fifo_test(dut) -> None:
    tb = Uart16550Tb(dut, name="uart_16550_fifo_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: TX FIFO burst")
    tb.log.info("=" * 70)
    await tb.configure(fifos=True)
    count = random.randint(1, TX_FIFO_DEPTH)
    tx_chars = [random.getrandbits(8) for _ in range(count)]
    for char in tx_chars:
        await tb.write(WO.THR_REG_ADDR, char)
    frames = await tb.expect_frames(count, "tx fifo")
    observed = [frame.data for frame in frames]
    assert observed == tx_chars, (
        f"tx fifo: wrote {[hex(c) for c in tx_chars]}, sampled {[hex(c) for c in observed]}"
    )
    await tb.wait_frames(1)
    lsr = await tb.read_u(MAIN.UART_16550_MAIN_LSR_reg_u, MAIN.LSR_REG_ADDR)
    assert lsr.f.thre == 1 and lsr.f.temt == 1, (
        f"tx fifo: THRE/TEMT not set after the burst (LSR 0x{lsr.val:02x})"
    )
    tb.log.info("%d characters left the TX FIFO in order; transmitter empty", count)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: RX FIFO burst")
    tb.log.info("=" * 70)
    await tb.reset()
    await tb.configure(fifos=True)
    count = random.randint(1, RX_FIFO_DEPTH)
    rx_chars = [random.getrandbits(8) for _ in range(count)]
    await tb.send_chars(rx_chars)
    await tb.wait_frames(count)
    observed = []
    for _ in range(count):
        lsr = await tb.wait_data_ready("rx fifo")
        assert lsr.f.oe == 0, "rx fifo: LSR.OE set during a burst within the FIFO depth"
        observed.append(await tb.read(MAIN.RBR_REG_ADDR))
    assert observed == rx_chars, (
        f"rx fifo: drove {[hex(c) for c in rx_chars]}, read {[hex(c) for c in observed]}"
    )
    lsr = await tb.read_u(MAIN.UART_16550_MAIN_LSR_reg_u, MAIN.LSR_REG_ADDR)
    assert lsr.f.dr == 0, "rx fifo: LSR.DR still set after draining every character"
    tb.log.info("%d characters drained from the RX FIFO in order without overrun", count)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: DMA ready signalling in mode 0 and mode 1")
    tb.log.info("=" * 70)
    await tb.reset()
    await tb.configure(loopback=True)
    await dma_transfer(tb, DmaMode.MODE_0, random.randint(1, min(TX_FIFO_DEPTH, RX_FIFO_DEPTH)))
    await dma_transfer(tb, DmaMode.MODE_1, random.randint(1, min(TX_FIFO_DEPTH, RX_FIFO_DEPTH)))

    tb.log.info("uart_16550_fifo_test PASSED (seed=%d)", seed)
