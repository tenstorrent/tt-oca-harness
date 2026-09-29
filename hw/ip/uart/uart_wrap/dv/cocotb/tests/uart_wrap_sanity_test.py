# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART wrapper sanity: per-instance windows, control pins, error responders.

Scenarios:

1. Reset defaults — each instance's UART IIR/LSR and log engine CTRL read
   their RDL reset values.
2. Cross-instance write/read law — distinct values land in every instance's
   UART SCR, UART IER and log engine LOG_REGION_SIZE before any readback, so
   a decode that folds two instances together cannot survive; each register
   keeps only its architected bits.
3. Control pins — each instance's CTRL.UART_EN drives its own ``uart_en``
   bit and no other.
4. Error responders — the gap inside an instance window and the space past
   the last window both answer DECERR with the responder's marker, and a
   mapped register is untouched by the errant writes.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from ocah_axi_vip import RESP_DECERR
from uart_wrap_base_test import (
    DECERR_RDATA,
    NUM_UARTS,
    REG,
    WINDOW_BASES,
    WINDOW_STRIDE,
    UartWrapTb,
    random_seed,
    reg_mask,
    win,
)


@cocotb.test()
async def uart_wrap_sanity_test(dut) -> None:
    tb = UartWrapTb(dut, name="uart_wrap_sanity_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: reset defaults in every instance window")
    tb.log.info("=" * 70)
    checks = 0
    for index in range(NUM_UARTS):
        for name, expected in (
            ("UART_IIR_REG_ADDR", REG.UART_16550_MAIN_IIR_REG_DEFAULT),
            ("UART_LSR_REG_ADDR", REG.UART_16550_MAIN_LSR_REG_DEFAULT),
            ("LOG_ENGINE_CTRL_REG_ADDR", REG.LOG_ENGINE_CTRL_REG_DEFAULT),
            ("UART_LOG_ENGINE_CTRL_CTRL_REG_ADDR", REG.UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT),
        ):
            observed = await tb.read(win(index, name))
            assert observed == expected, (
                f"uart{index} {name}: expected 0x{expected:08x}, observed 0x{observed:08x}"
            )
            checks += 1
    tb.log.info("%d registers across %d instances read their reset defaults", checks, NUM_UARTS)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: cross-instance write/read law (aliasing guard)")
    tb.log.info("=" * 70)
    law = (
        ("UART_SCR_REG_ADDR", reg_mask(REG.UART_16550_MAIN_SCR_reg_t)),
        ("UART_IER_REG_ADDR", reg_mask(REG.UART_16550_MAIN_IER_reg_t)),
        ("LOG_ENGINE_LOG_REGION_SIZE_REG_ADDR", reg_mask(REG.LOG_ENGINE_LOG_REGION_SIZE_reg_t)),
    )
    for pattern in ("random", "all-ones"):
        written = {}
        for index in range(NUM_UARTS):
            for name, _mask in law:
                written[(index, name)] = (
                    random.getrandbits(32) if pattern == "random" else 0xFFFF_FFFF
                )
                await tb.write(win(index, name), written[(index, name)])
        for index in range(NUM_UARTS):
            for name, mask in law:
                observed = await tb.read(win(index, name))
                expected = written[(index, name)] & mask
                assert observed == expected, (
                    f"uart{index} {name}: wrote 0x{written[(index, name)]:08x}, expected 0x{expected:08x}, observed 0x{observed:08x}"
                )
        tb.log.info(
            "%s pattern: %d registers in %d windows kept their own values",
            pattern,
            len(law),
            NUM_UARTS,
        )
    for index in range(NUM_UARTS):
        for name, _mask in law:
            await tb.write(win(index, name), 0)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: each CTRL.UART_EN drives its own uart_en bit")
    tb.log.info("=" * 70)
    for index in range(NUM_UARTS):
        await tb.write(win(index, "UART_LOG_ENGINE_CTRL_CTRL_REG_ADDR"), 1)
        await ClockCycles(dut.clk, 2)
        observed = int(dut.uart_en.value)
        assert observed == (1 << index), (
            f"uart_en 0b{observed:0{NUM_UARTS}b} after enabling only uart{index}"
        )
        await tb.write(win(index, "UART_LOG_ENGINE_CTRL_CTRL_REG_ADDR"), 0)
        await ClockCycles(dut.clk, 2)
        assert int(dut.uart_en.value) == 0, (
            f"uart_en still 0b{int(dut.uart_en.value):0{NUM_UARTS}b} after disabling uart{index}"
        )
    tb.log.info("uart_en bits follow their instance's CTRL.UART_EN one at a time")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: unmapped addresses reach the error responders")
    tb.log.info("=" * 70)
    scr = {index: random.getrandbits(8) for index in range(NUM_UARTS)}
    for index, value in scr.items():
        await tb.write(win(index, "UART_SCR_REG_ADDR"), value)
    victim = random.randrange(NUM_UARTS)
    unmapped = (
        WINDOW_BASES[victim]
        + REG.UART_LOG_ENGINE_WRAP_0__REG_MAP_SIZE,  # gap inside the instance window
        WINDOW_BASES[victim] + WINDOW_STRIDE - 4,  # last word of the instance window
        WINDOW_BASES[-1] + WINDOW_STRIDE,  # past the last instance
        REG.UART_WRAP_REG_MAP_SIZE + 0x400,  # past the wrapper map
    )
    for addr in unmapped:
        read = await tb.read_result(addr)
        assert read.resp == RESP_DECERR, (
            f"read 0x{addr:x}: expected DECERR, observed resp 0x{read.resp:x}"
        )
        assert read.data == DECERR_RDATA, (
            f"read 0x{addr:x}: expected 0x{DECERR_RDATA:08x}, observed 0x{read.data:08x}"
        )
        write = await tb.write_result(addr, random.getrandbits(32))
        assert write.resp == RESP_DECERR, (
            f"write 0x{addr:x}: expected DECERR, observed resp 0x{write.resp:x}"
        )
        tb.log.info("0x%05x: read and write both answered DECERR", addr)
    for index, value in scr.items():
        observed = await tb.read(win(index, "UART_SCR_REG_ADDR"))
        assert observed == value, (
            f"uart{index} SCR changed to 0x{observed:02x} by writes to unmapped addresses"
        )
    tb.log.info("errant writes left every instance's SCR untouched")

    tb.log.info("uart_wrap_sanity_test PASSED (seed=%d)", seed)
