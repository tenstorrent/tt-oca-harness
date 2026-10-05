# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART 16550 sanity: reset defaults, CSR law, line bring-up, interrupt test register.

Scenarios:

1. Reset defaults — the readable registers report their RDL reset values.
2. Scratch register write/read law — random values and an all-ones write
   prove only the architected bits stick.
3. TX bring-up — one character written to THR appears on tx as a clean
   frame of the programmed format.
4. RX bring-up — one character driven on rx lands in RBR with LSR.DR set
   and no line-status error.
5. System loopback — with MCR.LOOP set, tx stays idle, a THR write returns
   through RBR masked to the word length, and the modem outputs fold back
   into MSR including the delta bits.
6. Interrupt test register — each ITR bit raises irq and IIR reports the
   matching identifier.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from uart_16550_base_test import (
    MAIN,
    WO,
    IntrId,
    Uart16550Tb,
    random_seed,
    reg_mask,
    word_mask,
)


@cocotb.test()
async def uart_16550_sanity_test(dut) -> None:
    tb = Uart16550Tb(dut, name="uart_16550_sanity_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: reset defaults")
    tb.log.info("=" * 70)
    defaults = {
        "IER": (MAIN.IER_REG_ADDR, MAIN.UART_16550_MAIN_IER_REG_DEFAULT),
        "IIR": (MAIN.IIR_REG_ADDR, MAIN.UART_16550_MAIN_IIR_REG_DEFAULT),
        "LCR": (MAIN.LCR_REG_ADDR, MAIN.UART_16550_MAIN_LCR_REG_DEFAULT),
        "MCR": (MAIN.MCR_REG_ADDR, MAIN.UART_16550_MAIN_MCR_REG_DEFAULT),
        "LSR": (MAIN.LSR_REG_ADDR, MAIN.UART_16550_MAIN_LSR_REG_DEFAULT),
        "MSR": (MAIN.MSR_REG_ADDR, MAIN.UART_16550_MAIN_MSR_REG_DEFAULT),
        "SCR": (MAIN.SCR_REG_ADDR, MAIN.UART_16550_MAIN_SCR_REG_DEFAULT),
    }
    for name, (addr, expected) in defaults.items():
        observed = await tb.read(addr)
        assert observed == expected, (
            f"{name} reset default: expected 0x{expected:08x}, observed 0x{observed:08x}"
        )
    tb.log.info("%d registers read their reset defaults", len(defaults))

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: scratch register write/read law")
    tb.log.info("=" * 70)
    scr_mask = reg_mask(MAIN.UART_16550_MAIN_SCR_reg_t)
    for value in [random.getrandbits(32) for _ in range(4)] + [0xFFFF_FFFF, 0]:
        await tb.write(MAIN.SCR_REG_ADDR, value)
        observed = await tb.read(MAIN.SCR_REG_ADDR)
        assert observed == value & scr_mask, (
            f"SCR: wrote 0x{value:08x}, expected 0x{value & scr_mask:08x}, observed 0x{observed:08x}"
        )
    tb.log.info("SCR keeps exactly its %d-bit field", scr_mask.bit_length())

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: TX bring-up (THR -> line)")
    tb.log.info("=" * 70)
    fmt = await tb.configure(word_length=8, stop_bits=1, parity_enable=True)
    tx_char = random.getrandbits(8)
    await tb.write(WO.THR_REG_ADDR, tx_char)
    frames = await tb.expect_frames(1, "tx bring-up")
    assert frames[0].data == tx_char, (
        f"tx bring-up: sent 0x{tx_char:02x}, sampled 0x{frames[0].data:02x}"
    )
    tb.log.info(
        "THR 0x%02x sampled on tx as a clean %d%s%d frame",
        tx_char,
        fmt.word_length,
        fmt.parity[0].upper(),
        fmt.stop_bits,
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: RX bring-up (line -> RBR)")
    tb.log.info("=" * 70)
    rx_char = random.getrandbits(8)
    await tb.send_chars([rx_char])
    lsr = await tb.wait_data_ready("rx bring-up")
    assert lsr.f.pe == 0 and lsr.f.fe == 0 and lsr.f.bi == 0 and lsr.f.oe == 0, (
        f"rx bring-up: LSR reports a line error (0x{lsr.val:02x})"
    )
    observed = await tb.read(MAIN.RBR_REG_ADDR)
    assert observed == rx_char, f"rx bring-up: drove 0x{rx_char:02x}, RBR read 0x{observed:02x}"
    tb.log.info("rx 0x%02x received into RBR with a clean LSR", rx_char)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 5: system loopback with a random line format")
    tb.log.info("=" * 70)
    await tb.reset()
    fmt = await tb.configure(
        word_length=random.randint(5, 8),
        stop_bits=random.randint(1, 2),
        parity_enable=bool(random.getrandbits(1)),
        even_parity=bool(random.getrandbits(1)),
        loopback=True,
    )
    tx_char = random.getrandbits(8)
    expected = tx_char & word_mask(fmt.word_length)
    await tb.write(WO.THR_REG_ADDR, tx_char)
    for _ in range(8):
        await ClockCycles(dut.clk, fmt.frame_cycles // 8)
        assert int(dut.tx.value) == 1, "loopback: tx left the idle level while MCR.LOOP is set"
    lsr = await tb.wait_data_ready("loopback")
    assert lsr.f.pe == 0 and lsr.f.fe == 0 and lsr.f.bi == 0 and lsr.f.error_in_rcvr_fifo == 0, (
        f"loopback: LSR reports a line error (0x{lsr.val:02x})"
    )
    observed = await tb.read(MAIN.RBR_REG_ADDR)
    assert observed == expected, (
        f"loopback: wrote 0x{tx_char:02x} at {fmt.word_length} bits, expected RBR 0x{expected:02x}, observed 0x{observed:02x}"
    )
    tb.log.info("loopback data path returned 0x%02x", observed)

    mcr = await tb.read_u(MAIN.UART_16550_MAIN_MCR_reg_u, MAIN.MCR_REG_ADDR)
    mcr.f.dtr = random.getrandbits(1)
    mcr.f.rts = random.getrandbits(1)
    mcr.f.out1 = random.getrandbits(1)
    mcr.f.out2 = random.getrandbits(1)
    await tb.write(MAIN.MCR_REG_ADDR, mcr.val)
    msr = await tb.read_u(MAIN.UART_16550_MAIN_MSR_reg_u, MAIN.MSR_REG_ADDR)
    assert msr.f.dsr == mcr.f.dtr, "loopback: MSR.DSR does not follow MCR.DTR"
    assert msr.f.cts == mcr.f.rts, "loopback: MSR.CTS does not follow MCR.RTS"
    assert msr.f.ri == mcr.f.out1, "loopback: MSR.RI does not follow MCR.OUT1"
    assert msr.f.dcd == mcr.f.out2, "loopback: MSR.DCD does not follow MCR.OUT2"
    # Every modem control flips, and OUT1 pulses 1 -> 0 so TERI sees a
    # trailing edge of RI; the MSR read above cleared the delta bits.
    mcr.f.dtr ^= 1
    mcr.f.rts ^= 1
    mcr.f.out1 = 1
    mcr.f.out2 ^= 1
    await tb.write(MAIN.MCR_REG_ADDR, mcr.val)
    mcr.f.out1 = 0
    await tb.write(MAIN.MCR_REG_ADDR, mcr.val)
    msr = await tb.read_u(MAIN.UART_16550_MAIN_MSR_reg_u, MAIN.MSR_REG_ADDR)
    assert msr.f.ddsr == 1, "loopback: MSR.DDSR not set after DTR changed"
    assert msr.f.dcts == 1, "loopback: MSR.DCTS not set after RTS changed"
    assert msr.f.teri == 1, "loopback: MSR.TERI not set after OUT1 fell"
    assert msr.f.ddcd == 1, "loopback: MSR.DDCD not set after OUT2 changed"
    tb.log.info("loopback modem path: MSR status and delta bits follow MCR")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 6: interrupt test register raises every source")
    tb.log.info("=" * 70)
    await tb.reset()
    await tb.configure(fifos=True)
    ier = MAIN.UART_16550_MAIN_IER_reg_u()
    itr = MAIN.UART_16550_MAIN_ITR_reg_u()

    ier.f.edssi = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    itr.f.tdssi = 1
    await tb.write(MAIN.ITR_REG_ADDR, itr.val)
    await tb.expect_irq(IntrId.MODEM_STATUS, "ITR modem status")

    ier.f.etbei = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    itr.f.ttbei = 1
    await tb.write(MAIN.ITR_REG_ADDR, itr.val)
    await tb.expect_irq(IntrId.TRANSMITTER_HOLDING_REGISTER_EMPTY, "ITR THR empty")

    ier.f.erbfi = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    itr.f.trbfi = 1
    await tb.write(MAIN.ITR_REG_ADDR, itr.val)
    await tb.expect_irq(IntrId.RECEIVED_DATA_READY, "ITR received data ready")

    itr.f.trti = 1
    await tb.write(MAIN.ITR_REG_ADDR, itr.val)
    await tb.expect_irq(IntrId.RECEPTION_TIMEOUT, "ITR reception timeout")

    ier.f.elsi = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    itr.f.tlsi = 1
    await tb.write(MAIN.ITR_REG_ADDR, itr.val)
    await tb.expect_irq(IntrId.RECEIVER_LINE_STATUS, "ITR receiver line status")

    ier.f.efei = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    itr.f.tfei = 1
    await tb.write(MAIN.ITR_REG_ADDR, itr.val)
    await tb.expect_irq(IntrId.FIFO_ERROR, "ITR FIFO error")

    tb.log.info("uart_16550_sanity_test PASSED (seed=%d)", seed)
