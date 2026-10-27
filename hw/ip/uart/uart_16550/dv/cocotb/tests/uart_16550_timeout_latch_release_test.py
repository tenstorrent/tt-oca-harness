# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART 16550 release of a latched reception timeout.

Reproduces #3388: a reception timeout latched in FIFO mode survives
FCR.FIFO_ENABLE=0 (irq stays high and IIR reads 0x0C, a state the 16550 has no
encoding for) and is not masked by IER.ERBFI while the FIFOs stay on.

Each leg starts from a fresh FIFO-mode reception timeout (FIFOs enabled,
IER.ERBFI=1, one character received, four idle character times, IIR id 6 and
irq high) and then applies one software action:

(a) FCR.FIFO_ENABLE=0                        -> CHK-TO-FIFODIS
(b) FCR.RCVR_FIFO_RESET=1 with FIFOs enabled -> CHK-TO-RXRST
(c) IER=0 with FIFOs enabled                 -> CHK-TO-IERMASK

The 16550 contract graded here: after (a) the timeout is released, so irq is 0
and IIR does not report id 6 with the FIFOs disabled; after (c) IER masks the
timeout, so irq is 0. Leg (b) is observed and logged only: the 16550 does not
say whether a receiver FIFO reset releases the latch. Every leg's precondition
is asserted outright, and so is the control (FIFOs enabled, an RBR read drops
irq); the graded mismatches are collected and reported together so every leg
runs.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from uart_16550_base_test import (
    MAIN,
    TIMEOUT_CHAR_CNT,
    WO,
    Uart16550Tb,
)

IIR_TIMEOUT_LOW_NIBBLE = 0xC  # INTERRUPT_PENDING=0, INTERRUPT_ID=6


async def observe(tb: Uart16550Tb, tag: str) -> tuple[int, int]:
    """Return (IIR byte, irq) after a few settle cycles."""
    await ClockCycles(tb.dut.clk, 10)
    irq = int(tb.dut.irq.value)
    iir = await tb.read_iir()
    tb.log.info(
        "%s iir=0x%02x (id=0x%x pending=%d) irq=%d",
        tag,
        iir.val & 0xFF,
        iir.f.interrupt_id,
        iir.f.interrupt_pending,
        irq,
    )
    return iir.val & 0xFF, irq


async def arm_timeout(tb: Uart16550Tb, leg: str) -> None:
    """Fresh FIFO-mode timeout: one character, then four idle character times."""
    await tb.reset()
    await tb.configure(fifos=True)
    ier = MAIN.UART_16550_MAIN_IER_reg_u()
    ier.f.erbfi = 1
    await tb.write(MAIN.IER_REG_ADDR, ier.val)
    await tb.send_chars([0x5A])
    await tb.wait_frames(1)
    await tb.wait_frames(TIMEOUT_CHAR_CNT)
    iir, irq = await observe(tb, f"{leg} armed")
    assert irq == 1, f"{leg}: timeout precondition: irq not raised"
    assert (iir & 0xF) == IIR_TIMEOUT_LOW_NIBBLE, (
        f"{leg}: timeout precondition: IIR low nibble 0x{iir & 0xF:x}, expected 0xC"
    )


async def fcr_write(tb: Uart16550Tb, *, fifo_enable: int, rcvr_fifo_reset: int = 0) -> None:
    fcr = WO.UART_16550_MAIN_WO_FCR_reg_u()
    fcr.f.fifo_enable = fifo_enable
    fcr.f.rcvr_fifo_reset = rcvr_fifo_reset
    await tb.write(WO.FCR_REG_ADDR, fcr.val)


@cocotb.test()
async def uart_16550_timeout_latch_release_test(dut) -> None:
    tb = Uart16550Tb(dut, name="uart_16550_timeout_latch_release_test")
    await tb.start()
    mismatches: list[str] = []

    # ---- leg (a): FIFO_ENABLE=0 after a latched timeout ------------------
    await arm_timeout(tb, "leg-a")
    await fcr_write(tb, fifo_enable=0)
    await tb.wait_frames(1)
    iir_dis, irq_dis = await observe(tb, "leg-a after FIFO_ENABLE=0")
    line = f"CHK-TO-FIFODIS iir=0x{iir_dis:02x} irq={irq_dis} expected irq=0 and IIR not 0x0c"
    tb.log.info(line)
    if irq_dis != 0 or iir_dis == 0x0C:
        mismatches.append(line)
    # The only release path the RTL offers: FIFOs back on, then an RBR read.
    await fcr_write(tb, fifo_enable=1)
    await tb.read(MAIN.RBR_REG_ADDR)
    await observe(tb, "leg-a after FIFO_ENABLE=1 + RBR read")

    # ---- leg (b): RCVR_FIFO_RESET with FIFOs enabled (observed only) -----
    await arm_timeout(tb, "leg-b")
    await fcr_write(tb, fifo_enable=1, rcvr_fifo_reset=1)
    await tb.wait_frames(1)
    iir_b, irq_b = await observe(tb, "leg-b after RCVR_FIFO_RESET")
    tb.log.info("CHK-TO-RXRST iir=0x%02x irq=%d (observed only)", iir_b, irq_b)
    await tb.read(MAIN.RBR_REG_ADDR)
    await observe(tb, "leg-b after RBR read on the empty FIFO")

    # ---- leg (c): IER=0 with FIFOs enabled -------------------------------
    await arm_timeout(tb, "leg-c")
    await tb.write(MAIN.IER_REG_ADDR, 0)
    await tb.wait_frames(1)
    iir_c, irq_c = await observe(tb, "leg-c after IER=0")
    line = f"CHK-TO-IERMASK iir=0x{iir_c:02x} irq={irq_c} expected irq=0"
    tb.log.info(line)
    if irq_c != 0:
        mismatches.append(line)

    # ---- control: FIFOs enabled, RBR read --------------------------------
    await tb.write(MAIN.IER_REG_ADDR, 1)
    await tb.read(MAIN.RBR_REG_ADDR)
    iir_ctrl, irq_ctrl = await observe(tb, "control after RBR read in FIFO mode")
    tb.log.info("CHK-TO-CTRL iir=0x%02x irq=%d", iir_ctrl, irq_ctrl)
    assert irq_ctrl == 0, "control: irq still high after RBR read in FIFO mode"

    assert not mismatches, (
        "latched reception timeout deviates from the 16550 contract:\n" + "\n".join(mismatches)
    )
    tb.log.info("uart_16550_timeout_latch_release_test PASSED")
