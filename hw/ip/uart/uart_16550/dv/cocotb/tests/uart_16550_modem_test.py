# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART 16550 modem control/status and line loopback.

Scenarios:

1. Modem control outputs — each MCR control bit drives its active-low pin.
2. Modem status inputs — MSR reports the (inverted) pin levels, the delta
   bits flag a change since the last MSR read, and TERI flags a trailing
   edge of RI.
3. Line loopback — with MCR.LINE_LOOPBACK set, a frame driven on rx is
   echoed on tx unchanged, the modem outputs follow the modem inputs, and
   the MSR status bits read as deasserted.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from uart_16550_base_test import MAIN, Uart16550Tb, random_seed

# Cycles for a modem input to pass the DUT's two-flop synchronizer.
MODEM_SYNC_CYCLES = 5


@cocotb.test()
async def uart_16550_modem_test(dut) -> None:
    tb = Uart16550Tb(dut, name="uart_16550_modem_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    await tb.configure()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: MCR control bits drive the modem output pins")
    tb.log.info("=" * 70)
    for _ in range(4):
        mcr = MAIN.UART_16550_MAIN_MCR_reg_u()
        mcr.f.dtr = random.getrandbits(1)
        mcr.f.rts = random.getrandbits(1)
        mcr.f.out1 = random.getrandbits(1)
        mcr.f.out2 = random.getrandbits(1)
        await tb.write(MAIN.MCR_REG_ADDR, mcr.val)
        await ClockCycles(dut.clk, MODEM_SYNC_CYCLES)
        pins = {
            "dtr_n": (int(dut.dtr_n.value), mcr.f.dtr),
            "rts_n": (int(dut.rts_n.value), mcr.f.rts),
            "out1_n": (int(dut.out1_n.value), mcr.f.out1),
            "out2_n": (int(dut.out2_n.value), mcr.f.out2),
        }
        for pin, (observed, control) in pins.items():
            assert observed == (control ^ 1), f"{pin}: MCR bit {control} but pin reads {observed}"
        tb.log.info(
            "MCR 0x%02x drives dtr_n/rts_n/out1_n/out2_n = %s",
            mcr.val,
            [v[0] for v in pins.values()],
        )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: MSR status, delta and TERI bits")
    tb.log.info("=" * 70)
    initial = {name: random.getrandbits(1) for name in ("cts", "dsr", "dcd")}
    dut.cts_n.value = initial["cts"] ^ 1
    dut.dsr_n.value = initial["dsr"] ^ 1
    dut.dcd_n.value = initial["dcd"] ^ 1
    dut.ri_n.value = 1
    await ClockCycles(dut.clk, MODEM_SYNC_CYCLES)
    msr = await tb.read_u(MAIN.UART_16550_MAIN_MSR_reg_u, MAIN.MSR_REG_ADDR)
    assert (msr.f.cts, msr.f.dsr, msr.f.dcd) == (initial["cts"], initial["dsr"], initial["dcd"]), (
        f"MSR status bits 0x{msr.val:02x} do not follow the modem inputs {initial}"
    )
    tb.log.info("MSR status follows cts/dsr/dcd = %s; delta bits cleared by the read", initial)

    await ClockCycles(dut.clk, random.randint(1, 10))
    final = {name: random.getrandbits(1) for name in ("cts", "dsr", "dcd")}
    dut.cts_n.value = final["cts"] ^ 1
    dut.dsr_n.value = final["dsr"] ^ 1
    dut.dcd_n.value = final["dcd"] ^ 1
    await ClockCycles(dut.clk, MODEM_SYNC_CYCLES)
    msr = await tb.read_u(MAIN.UART_16550_MAIN_MSR_reg_u, MAIN.MSR_REG_ADDR)
    for name, delta in (("cts", msr.f.dcts), ("dsr", msr.f.ddsr), ("dcd", msr.f.ddcd)):
        expected = int(initial[name] != final[name])
        assert delta == expected, (
            f"MSR delta for {name}: {initial[name]} -> {final[name]} expected {expected}, observed {delta}"
        )
    tb.log.info("MSR delta bits report exactly the inputs that changed (%s -> %s)", initial, final)

    dut.ri_n.value = 0
    await ClockCycles(dut.clk, random.randint(1, 10) + MODEM_SYNC_CYCLES)
    dut.ri_n.value = 1
    await ClockCycles(dut.clk, MODEM_SYNC_CYCLES)
    msr = await tb.read_u(MAIN.UART_16550_MAIN_MSR_reg_u, MAIN.MSR_REG_ADDR)
    assert msr.f.teri == 1, "MSR.TERI not set after RI returned inactive"
    msr = await tb.read_u(MAIN.UART_16550_MAIN_MSR_reg_u, MAIN.MSR_REG_ADDR)
    assert msr.f.teri == 0, "MSR.TERI not cleared by the MSR read"
    tb.log.info("TERI flags the trailing edge of RI and clears on read")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: line loopback echoes rx on tx and folds the modem pins")
    tb.log.info("=" * 70)
    await tb.reset()
    fmt = await tb.configure(word_length=8, stop_bits=1, parity_enable=True)
    mcr = MAIN.UART_16550_MAIN_MCR_reg_u()
    mcr.f.line_loopback = 1
    await tb.write(MAIN.MCR_REG_ADDR, mcr.val)

    chars = [random.getrandbits(8) for _ in range(random.randint(1, 4))]
    await tb.send_chars(chars)
    frames = await tb.expect_frames(len(chars), "line loopback")
    observed = [frame.data for frame in frames]
    assert observed == chars, (
        f"line loopback: drove {[hex(c) for c in chars]}, tx echoed {[hex(c) for c in observed]}"
    )
    lsr = await tb.read_u(MAIN.UART_16550_MAIN_LSR_reg_u, MAIN.LSR_REG_ADDR)
    assert lsr.f.dr == 0, "line loopback: the receiver captured data although rx bypasses it"
    tb.log.info(
        "%d frames echoed rx -> tx at %d%s%d; receiver stayed idle",
        len(chars),
        fmt.word_length,
        fmt.parity[0].upper(),
        fmt.stop_bits,
    )

    for _ in range(4):
        levels = {name: random.getrandbits(1) for name in ("cts_n", "dsr_n", "ri_n", "dcd_n")}
        for name, level in levels.items():
            getattr(dut, name).value = level
        await ClockCycles(dut.clk, 2)
        assert int(dut.rts_n.value) == levels["cts_n"], "line loopback: rts_n does not follow cts_n"
        assert int(dut.dtr_n.value) == levels["dsr_n"], "line loopback: dtr_n does not follow dsr_n"
        assert int(dut.out1_n.value) == levels["ri_n"], "line loopback: out1_n does not follow ri_n"
        assert int(dut.out2_n.value) == levels["dcd_n"], (
            "line loopback: out2_n does not follow dcd_n"
        )
    await ClockCycles(dut.clk, MODEM_SYNC_CYCLES)
    msr = await tb.read_u(MAIN.UART_16550_MAIN_MSR_reg_u, MAIN.MSR_REG_ADDR)
    assert (msr.f.cts, msr.f.dsr, msr.f.ri, msr.f.dcd) == (0, 0, 0, 0), (
        f"line loopback: MSR status bits not deasserted (0x{msr.val:02x})"
    )
    tb.log.info("line loopback folds the modem inputs onto the outputs and blanks MSR")

    tb.log.info("uart_16550_modem_test PASSED (seed=%d)", seed)
