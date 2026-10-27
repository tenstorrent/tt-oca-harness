# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART 16550 release of a latched reception timeout.

Reproduces #3388: a reception timeout latched in FIFO mode survives
FCR.FIFO_ENABLE=0 (irq stays high and IIR reads 0x0C, a state the 16550 has no
encoding for).

Each leg starts from a fresh FIFO-mode reception timeout (FIFOs enabled,
IER.ERBFI=1, one character received, four idle character times, IIR id 6 and
irq high) and then applies one software action:

(a) FCR.FIFO_ENABLE=0                        -> CHK-TO-FIFODIS (graded)
(b) FCR.RCVR_FIFO_RESET=1 with FIFOs enabled -> CHK-TO-RXRST   (observed only)
(c) IER=0 with FIFOs enabled                 -> CHK-TO-IERMASK (observed only)

Only leg (a) is graded: after FIFO_ENABLE=0 the timeout is released, so irq is
0 and IIR does not report id 6 with the FIFOs disabled. The basis is
``../doc/architecture.adoc``: changing ``FCR.FIFO_ENABLE`` clears both FIFOs
and the holding state (lines 24-26), and the timeout is a FIFO-mode request
cleared by an RBR read (lines 111-112), so nothing it reports can outlive FIFO
mode. Neither sentence states the release outright; #3388 asks the owner to
state it, and until then the golden is the 16550 standard. Leg (b) is observed
only because the 16550 does not say whether a receiver FIFO reset releases the
latch. Leg (c) is observed only because the same document states that the
timeout request is not gated by IER (lines 111-113 and 133), so the 16550
masking rule is a spec question for the owner, not a graded contract. Every
leg's precondition is asserted outright, and so is the control (FIFOs enabled,
an RBR read drops irq). The graded mismatch is reported on the first line of
the assertion message under its ``CHK-TO-FIFODIS FAIL`` tag.
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

    # ---- leg (a): FIFO_ENABLE=0 after a latched timeout ------------------
    await arm_timeout(tb, "leg-a")
    await fcr_write(tb, fifo_enable=0)
    await tb.wait_frames(1)
    iir_dis, irq_dis = await observe(tb, "leg-a after FIFO_ENABLE=0")
    fifodis_line = (
        f"CHK-TO-FIFODIS iir=0x{iir_dis:02x} irq={irq_dis} expected irq=0 and IIR not 0x0c"
    )
    tb.log.info(fifodis_line)
    fifodis_released = irq_dis == 0 and iir_dis != 0x0C
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

    # ---- leg (c): IER=0 with FIFOs enabled (observed only) ---------------
    await arm_timeout(tb, "leg-c")
    await tb.write(MAIN.IER_REG_ADDR, 0)
    await tb.wait_frames(1)
    iir_c, irq_c = await observe(tb, "leg-c after IER=0")
    tb.log.info("CHK-TO-IERMASK iir=0x%02x irq=%d (observed only)", iir_c, irq_c)

    # ---- control: FIFOs enabled, RBR read --------------------------------
    await tb.write(MAIN.IER_REG_ADDR, 1)
    await tb.read(MAIN.RBR_REG_ADDR)
    iir_ctrl, irq_ctrl = await observe(tb, "control after RBR read in FIFO mode")
    tb.log.info("CHK-TO-CTRL iir=0x%02x irq=%d", iir_ctrl, irq_ctrl)
    assert irq_ctrl == 0, "control: irq still high after RBR read in FIFO mode"

    assert fifodis_released, (
        "CHK-TO-FIFODIS FAIL: a latched reception timeout survives FIFO_ENABLE=0\n" + fifodis_line
    )
    tb.log.info("uart_16550_timeout_latch_release_test PASSED")
