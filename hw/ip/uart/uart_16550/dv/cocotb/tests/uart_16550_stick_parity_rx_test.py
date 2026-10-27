# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART 16550 stick parity on receive, driven from the external line.

Reproduces #3387: with stick parity enabled the receiver flags LSR.PE from the
parity of the data bits instead of comparing the sampled parity bit with the
stuck level.

With LCR.PEN and LCR.STICK_PARITY set, a 16550 receiver checks that the
received parity bit equals the stuck level (0 when LCR.EPS selects even,
1 when it selects odd) regardless of the data bits. For each EPS setting the
line driver sends a character with an even number of ones and one with an odd
number of ones, each once with the parity bit at the stuck level and once at
the wrong level. LSR.PE is expected 0 for the stuck level and 1 for the wrong
level. Each case logs one ``CHK-STICK`` line with the observed PE and the
expected value; mismatches are collected and reported together so every case
runs.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from uart_16550_base_test import MAIN, Uart16550Tb, parity_of

EVEN_ONES_CHAR = 0x33  # four ones
ODD_ONES_CHAR = 0x37  # five ones


async def drive_with_parity_level(tb: Uart16550Tb, char: int, level: int) -> None:
    """Send ``char`` on rx with the parity bit at ``level``.

    The VIP computes the parity bit from the data; selecting even or odd mode
    makes that computed bit equal to ``level`` exactly.
    """
    mode = "even" if parity_of(char) == level else "odd"
    tb.line_driver.configure(parity=mode)
    await tb.line_driver.write([char])
    await tb.line_driver.wait()


async def read_pe(tb: Uart16550Tb, what: str) -> int:
    lsr = await tb.wait_data_ready(what)
    pe = int(lsr.f.pe)
    await tb.read(MAIN.RBR_REG_ADDR)
    # LSR.PE is read-to-clear; leave LSR clean for the next case.
    await tb.read(MAIN.LSR_REG_ADDR)
    return pe


@cocotb.test()
async def uart_16550_stick_parity_rx_test(dut) -> None:
    tb = Uart16550Tb(dut, name="uart_16550_stick_parity_rx_test")
    await tb.start()

    mismatches: list[str] = []
    for eps in (0, 1):
        await tb.reset()
        await tb.configure(
            word_length=8, stop_bits=1, parity_enable=True, even_parity=bool(eps), loopback=False
        )
        lcr = await tb.read_u(MAIN.UART_16550_MAIN_LCR_reg_u, MAIN.LCR_REG_ADDR)
        lcr.f.stick_parity = 1
        await tb.write(MAIN.LCR_REG_ADDR, lcr.val)
        await ClockCycles(dut.clk, 4)
        stuck = 0 if eps else 1

        cases = [
            ("even", "ok", EVEN_ONES_CHAR, stuck, 0),
            ("odd", "ok", ODD_ONES_CHAR, stuck, 0),
            ("even", "wrong", EVEN_ONES_CHAR, stuck ^ 1, 1),
            ("odd", "wrong", ODD_ONES_CHAR, stuck ^ 1, 1),
        ]
        for ones, pbit, char, level, expected in cases:
            await drive_with_parity_level(tb, char, level)
            pe = await read_pe(tb, f"eps={eps} ones={ones} pbit={pbit}")
            line = (
                f"CHK-STICK eps={eps} ones={ones} pbit={pbit} pe={pe} expected={expected}"
                f" (char=0x{char:02x} parity_bit_sent={level})"
            )
            tb.log.info(line)
            if pe != expected:
                mismatches.append(line)

    assert not mismatches, (
        "stick parity receive check deviates from the 16550 contract:\n" + "\n".join(mismatches)
    )
    tb.log.info("uart_16550_stick_parity_rx_test PASSED")
