# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART and Log Engine wrapper sanity: window decode, control pin, error responder.

Scenarios:

1. Reset defaults — a register in each of the three windows reads its RDL
   reset value.
2. Cross-window write/read law — distinct values land in the control CTRL,
   the UART SCR and IER, and the log engine LOG_REGION_SIZE and
   LOG_WRITE_ADDR before any readback, so a decode that folds two windows
   together cannot survive; each register keeps only its architected bits.
3. Control pin — CTRL.UART_EN drives the ``uart_en`` output.
4. Error responder — reads and writes to the gap past the wrapper map, the
   UART window and the log engine window return DECERR, the read payload is
   the responder's marker, and a mapped register is untouched by the errant
   write.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from ocah_axi_vip import RESP_DECERR
from uart_log_engine_wrap_base_test import (
    DECERR_RDATA,
    REG,
    UNMAPPED_ADDRS,
    UartLogEngineWrapTb,
    random_seed,
    reg_mask,
)


@cocotb.test()
async def uart_log_engine_wrap_sanity_test(dut) -> None:
    tb = UartLogEngineWrapTb(dut, name="uart_log_engine_wrap_sanity_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: reset defaults in every window")
    tb.log.info("=" * 70)
    defaults = {
        "CTRL": (REG.UART_LOG_ENGINE_CTRL_CTRL_REG_ADDR, REG.UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT),
        "UART.IIR": (REG.UART_IIR_REG_ADDR, REG.UART_16550_MAIN_IIR_REG_DEFAULT),
        "UART.LSR": (REG.UART_LSR_REG_ADDR, REG.UART_16550_MAIN_LSR_REG_DEFAULT),
        "LOG_ENGINE.CTRL": (REG.LOG_ENGINE_CTRL_REG_ADDR, REG.LOG_ENGINE_CTRL_REG_DEFAULT),
        "LOG_ENGINE.INTR_STATUS": (
            REG.LOG_ENGINE_INTR_STATUS_REG_ADDR,
            REG.LOG_ENGINE_INTR_STATUS_REG_DEFAULT,
        ),
    }
    for name, (addr, expected) in defaults.items():
        observed = await tb.read(addr)
        assert observed == expected, (
            f"{name} @0x{addr:x} reset default: expected 0x{expected:08x}, observed 0x{observed:08x}"
        )
    tb.log.info("%d registers across the three windows read their reset defaults", len(defaults))

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: cross-window write/read law (aliasing guard)")
    tb.log.info("=" * 70)
    law = {
        "CTRL": (
            REG.UART_LOG_ENGINE_CTRL_CTRL_REG_ADDR,
            reg_mask(REG.UART_LOG_ENGINE_CTRL_CTRL_reg_t),
        ),
        "UART.SCR": (REG.UART_SCR_REG_ADDR, reg_mask(REG.UART_16550_MAIN_SCR_reg_t)),
        "UART.IER": (REG.UART_IER_REG_ADDR, reg_mask(REG.UART_16550_MAIN_IER_reg_t)),
        "LOG_ENGINE.LOG_REGION_SIZE": (
            REG.LOG_ENGINE_LOG_REGION_SIZE_REG_ADDR,
            reg_mask(REG.LOG_ENGINE_LOG_REGION_SIZE_reg_t),
        ),
        "LOG_ENGINE.LOG_WRITE_ADDR": (REG.LOG_ENGINE_LOG_WRITE_ADDR_REG_ADDR, 0xFFFF_FFFF),
    }
    for pattern in ("random", "all-ones"):
        written = {}
        for name, (addr, _mask) in law.items():
            written[name] = random.getrandbits(32) if pattern == "random" else 0xFFFF_FFFF
            await tb.write(addr, written[name])
        for name, (addr, mask) in law.items():
            observed = await tb.read(addr)
            expected = written[name] & mask
            tb.log.info(
                "%-28s @0x%03x wrote 0x%08x readback 0x%08x", name, addr, written[name], observed
            )
            assert observed == expected, (
                f"{name}: wrote 0x{written[name]:08x}, expected 0x{expected:08x}, observed 0x{observed:08x}"
            )
    for addr, _mask in law.values():
        await tb.write(addr, 0)
    tb.log.info("no window aliases another; every register keeps its architected bits")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: CTRL.UART_EN drives uart_en")
    tb.log.info("=" * 70)
    for level in (1, 0, 1):
        await tb.write(REG.UART_LOG_ENGINE_CTRL_CTRL_REG_ADDR, level)
        await ClockCycles(dut.clk, 2)
        assert int(dut.uart_en.value) == level, (
            f"uart_en reads {int(dut.uart_en.value)} after CTRL.UART_EN={level}"
        )
    await tb.write(REG.UART_LOG_ENGINE_CTRL_CTRL_REG_ADDR, 0)
    tb.log.info("uart_en follows CTRL.UART_EN")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: unmapped addresses reach the error responder")
    tb.log.info("=" * 70)
    scr_value = random.getrandbits(8)
    await tb.write(REG.UART_SCR_REG_ADDR, scr_value)
    for addr in UNMAPPED_ADDRS:
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
        tb.log.info("0x%04x: read and write both answered DECERR", addr)
    observed = await tb.read(REG.UART_SCR_REG_ADDR)
    assert observed == scr_value, (
        f"UART.SCR changed to 0x{observed:02x} by writes to unmapped addresses"
    )
    tb.log.info("errant writes left UART.SCR at 0x%02x", scr_value)

    tb.log.info("uart_log_engine_wrap_sanity_test PASSED (seed=%d)", seed)
