# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART 16550 interrupt priority and receiver line errors.

Scenarios:

1. Layered interrupts — sources are raised one at a time in ascending
   priority (modem status, THR empty, received data, reception timeout,
   receiver line status) and IIR must report the highest pending one each
   time; the RX trigger level is re-programmed under a pending burst and the
   received-data interrupt follows it; clearing every source drops irq.
2. Receiver line errors — in system loopback, stick parity forces a parity
   error and SET_BREAK forces a framing error with break indication, each
   reported through LSR together with ERROR_IN_RCVR_FIFO.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from uart_16550_base_test import (
    MAIN,
    RX_FIFO_DEPTH,
    RX_TRIGGER_LEVELS,
    TIMEOUT_CHAR_CNT,
    WAIT_MARGIN,
    WO,
    IntrId,
    Uart16550Tb,
    parity_of,
    random_seed,
    word_mask,
)


def odd_parity_char(word_length: int) -> int:
    """A random character of ``word_length`` bits with an odd number of ones."""
    char = random.getrandbits(word_length) & word_mask(word_length)
    if parity_of(char) == 0:
        char ^= 1
    return char


async def send_break_in_loopback(tb: Uart16550Tb, what: str):
    """Pulse LCR.SET_BREAK for a frame time under MCR.LOOP; return the LSR that saw it."""
    lcr = await tb.read_u(MAIN.UART_16550_MAIN_LCR_reg_u, MAIN.LCR_REG_ADDR)
    lcr.f.set_break = 1
    await tb.write(MAIN.LCR_REG_ADDR, lcr.val)
    await ClockCycles(tb.dut.clk, tb.fmt.frame_cycles)
    lsr = await tb.wait_data_ready(what)
    lcr.f.set_break = 0
    await tb.write(MAIN.LCR_REG_ADDR, lcr.val)
    return lsr


@cocotb.test()
async def uart_16550_interrupt_test(dut) -> None:
    tb = Uart16550Tb(dut, name="uart_16550_interrupt_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: layered interrupts in priority order")
    tb.log.info("=" * 70)
    fifos = bool(random.getrandbits(1))
    fmt = await tb.configure(
        word_length=random.randint(5, 8),
        stop_bits=random.randint(1, 2),
        parity_enable=bool(random.getrandbits(1)),
        even_parity=bool(random.getrandbits(1)),
        fifos=fifos,
    )
    iir = await tb.read_iir()
    assert iir.f.fifos_enabled == (0b11 if fifos else 0b00), (
        f"IIR.FIFOS_ENABLED 0b{iir.f.fifos_enabled:02b} does not reflect FCR.FIFO_ENABLE={int(fifos)}"
    )
    ier = MAIN.UART_16550_MAIN_IER_reg_u()

    ier.f.edssi = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    dut.ri_n.value = 0
    await ClockCycles(dut.clk, random.randint(1, 10) + 5)
    dut.ri_n.value = 1
    await tb.expect_irq(IntrId.MODEM_STATUS, "modem status (RI trailing edge)")

    ier.f.etbei = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    await tb.expect_irq(
        IntrId.TRANSMITTER_HOLDING_REGISTER_EMPTY, "THR empty layered on modem status"
    )

    ier.f.erbfi = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    count = random.randint(1, RX_FIFO_DEPTH) if fifos else 1
    chars = [random.getrandbits(fmt.word_length) for _ in range(count)]
    await tb.send_chars(chars)
    await tb.wait_frames(count)
    await tb.expect_irq(
        IntrId.RECEIVED_DATA_READY, f"received data ({count} chars) layered on THR empty"
    )

    if fifos:
        level = random.choice(list(RX_TRIGGER_LEVELS))
        fcr = WO.UART_16550_MAIN_WO_FCR_reg_u()
        fcr.f.fifo_enable = 1
        fcr.f.rcvr_trigger = RX_TRIGGER_LEVELS[level]
        await tb.write(WO.FCR_REG_ADDR, fcr.val)
        await ClockCycles(dut.clk, 4)
        iir = await tb.read_iir()
        if count >= level:
            assert iir.f.interrupt_id == IntrId.RECEIVED_DATA_READY, (
                f"{count} chars >= trigger {level}: received-data interrupt should stay pending"
            )
        else:
            assert iir.f.interrupt_id != IntrId.RECEIVED_DATA_READY, (
                f"{count} chars < trigger {level}: received-data interrupt should clear"
            )
        tb.log.info(
            "RX trigger level %d with %d chars pending: IIR id 0x%x",
            level,
            count,
            iir.f.interrupt_id,
        )

    await ClockCycles(dut.clk, int(WAIT_MARGIN * TIMEOUT_CHAR_CNT * fmt.frame_cycles))
    iir = await tb.read_iir()
    if fifos:
        assert int(dut.irq.value) == 1, "reception timeout: irq not raised"
        assert iir.f.interrupt_id == IntrId.RECEPTION_TIMEOUT, (
            f"reception timeout: IIR id 0x{iir.f.interrupt_id:x} after {TIMEOUT_CHAR_CNT} idle character times"
        )
        tb.log.info("reception timeout raised after %d idle character times", TIMEOUT_CHAR_CNT)
    else:
        assert iir.f.interrupt_id != IntrId.RECEPTION_TIMEOUT, (
            "reception timeout raised in non-FIFO mode"
        )
        tb.log.info("non-FIFO mode: no reception timeout, as architected")

    fcr = WO.UART_16550_MAIN_WO_FCR_reg_u()
    fcr.f.fifo_enable = 1
    fcr.f.rcvr_fifo_reset = 1
    await tb.write(WO.FCR_REG_ADDR, fcr.val)
    ier.f.elsi = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    mcr = MAIN.UART_16550_MAIN_MCR_reg_u()
    mcr.f.loop = 1
    await tb.write(MAIN.MCR_REG_ADDR, mcr.val)
    lsr = await send_break_in_loopback(tb, "line status via break")
    mcr.f.loop = 0
    await tb.write(MAIN.MCR_REG_ADDR, mcr.val)
    assert lsr.f.bi == 1, "line status: break not flagged in LSR"
    await tb.expect_irq(IntrId.RECEIVER_LINE_STATUS, "receiver line status layered on the rest")

    fcr.f.rcvr_fifo_reset = 1
    await tb.write(WO.FCR_REG_ADDR, fcr.val)
    await tb.read(MAIN.LSR_REG_ADDR)
    await tb.read(MAIN.RBR_REG_ADDR)
    await tb.read(MAIN.IIR_REG_ADDR)
    await tb.read(MAIN.MSR_REG_ADDR)
    await ClockCycles(dut.clk, 4)
    assert int(dut.irq.value) == 0, "irq still high after every source was cleared"
    iir = await tb.read_iir()
    assert iir.f.interrupt_pending == 1, (
        "IIR still reports a pending interrupt after clearing every source"
    )
    tb.log.info("every source cleared: irq low, IIR reports none pending")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: receiver line errors through the loopback")
    tb.log.info("=" * 70)
    await tb.reset()
    fmt = await tb.configure(
        word_length=random.randint(5, 8),
        stop_bits=random.randint(1, 2),
        parity_enable=True,
        even_parity=bool(random.getrandbits(1)),
        loopback=True,
    )
    lcr = await tb.read_u(MAIN.UART_16550_MAIN_LCR_reg_u, MAIN.LCR_REG_ADDR)
    lcr.f.stick_parity = 1
    await tb.write(MAIN.LCR_REG_ADDR, lcr.val)
    # The transmitter sticks the parity bit at the level EPS selects; the
    # receiver still checks true parity, so a character with an odd number of
    # ones mismatches under both EPS settings.
    char = odd_parity_char(fmt.word_length)
    await tb.write(WO.THR_REG_ADDR, char)
    lsr = await tb.wait_data_ready("stick parity")
    lcr.f.stick_parity = 0
    await tb.write(MAIN.LCR_REG_ADDR, lcr.val)
    assert lsr.f.pe == 1, f"stick parity on 0x{char:02x}: LSR.PE not set"
    assert lsr.f.error_in_rcvr_fifo == 1, "stick parity: LSR.ERROR_IN_RCVR_FIFO not set"
    await tb.read(MAIN.RBR_REG_ADDR)
    tb.log.info("stick parity on 0x%02x reported PE and ERROR_IN_RCVR_FIFO", char)

    lsr = await send_break_in_loopback(tb, "break")
    assert lsr.f.fe == 1, "break: LSR.FE not set"
    assert lsr.f.bi == 1, "break: LSR.BI not set"
    assert lsr.f.error_in_rcvr_fifo == 1, "break: LSR.ERROR_IN_RCVR_FIFO not set"
    tb.log.info("break reported FE, BI and ERROR_IN_RCVR_FIFO")

    tb.log.info("uart_16550_interrupt_test PASSED (seed=%d)", seed)
