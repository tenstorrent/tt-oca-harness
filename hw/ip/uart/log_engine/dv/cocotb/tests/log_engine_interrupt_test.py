# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log Engine interrupts: test register, enable gating, clear, real bus errors.

Scenarios:

1. Interrupt test register — each INTR_TEST bit sets its INTR_STATUS bit
   and raises irq while enabled; writing the status bit clears both.
2. Enable gating — a forced status bit with its enable clear leaves irq low
   until the enable is set.
3. Fetch error — a SLVERR injected on the slot's first fetch beat sets
   LOG_FETCH_ERR and irq; disabling and re-enabling the engine recovers it
   and a clean transfer follows.
4. Write error — a SLVERR injected on the UART sink write sets
   LOG_WRITE_ERR and irq, with the same recovery.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from log_engine_base_test import (
    CYCLES_PER_BYTE,
    LOG_REGION_ALIGNMENT,
    NUM_LOG_ENTRIES,
    REG,
    WRITE_ADDR,
    LogEngineTb,
    random_seed,
)
from ocah_axi_vip import RESP_SLVERR

SOURCES = ("log_fetch_err", "log_write_err")


def status_word(**bits: int) -> int:
    reg = REG.LOG_ENGINE_INTR_STATUS_reg_u()
    for name, value in bits.items():
        setattr(reg.f, name, value)
    return reg.val


async def wait_status(tb: LogEngineTb, source: str, budget_cycles: int, what: str):
    """Poll INTR_STATUS until ``source`` is set."""
    waited = 0
    while True:
        status = await tb.read_u(REG.LOG_ENGINE_INTR_STATUS_reg_u, REG.INTR_STATUS_REG_ADDR)
        if getattr(status.f, source):
            return status
        assert waited < budget_cycles, f"{what}: INTR_STATUS.{source} not set after {waited} cycles"
        await ClockCycles(tb.dut.clk, 20)
        waited += 20


async def recover(tb: LogEngineTb, source: str, what: str) -> None:
    """Disable the engine (resets its FSMs), clear the status, re-enable, and prove a transfer."""
    dut = tb.dut
    await tb.write(REG.CTRL_REG_ADDR, 0)
    await tb.write(REG.INTR_STATUS_REG_ADDR, status_word(**{source: 1}))
    await ClockCycles(dut.clk, 4)
    assert int(dut.irq.value) == 0, f"{what}: irq still high after clearing {source}"
    await tb.write(REG.CTRL_REG_ADDR, 1)
    index = random.randrange(NUM_LOG_ENTRIES)
    payload = random.randbytes(random.randint(1, 24))
    stream = await tb.transfer(index, payload, f"{what} recovery")
    assert stream == list(payload), f"{what}: transfer after recovery lost data"
    status = await tb.read_u(REG.LOG_ENGINE_INTR_STATUS_reg_u, REG.INTR_STATUS_REG_ADDR)
    assert status.val == 0, f"{what}: INTR_STATUS 0x{status.val:x} after a clean recovery transfer"
    tb.log.info("%s: recovered; slot %d moved %d bytes cleanly", what, index, len(payload))


@cocotb.test()
async def log_engine_interrupt_test(dut) -> None:
    tb = LogEngineTb(dut, name="log_engine_interrupt_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    await tb.configure(region_size=32 * LOG_REGION_ALIGNMENT)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: interrupt test register and write-one-to-clear")
    tb.log.info("=" * 70)
    await tb.write(REG.INTR_ENABLE_REG_ADDR, status_word(log_fetch_err=1, log_write_err=1))
    for source in SOURCES:
        await tb.write(REG.INTR_TEST_REG_ADDR, status_word(**{source: 1}))
        await ClockCycles(dut.clk, 4)
        assert int(dut.irq.value) == 1, f"INTR_TEST.{source}: irq not raised"
        status = await tb.read_u(REG.LOG_ENGINE_INTR_STATUS_reg_u, REG.INTR_STATUS_REG_ADDR)
        assert status.val == status_word(**{source: 1}), (
            f"INTR_TEST.{source}: INTR_STATUS 0x{status.val:x}"
        )
        await tb.write(REG.INTR_STATUS_REG_ADDR, status_word(**{source: 1}))
        await ClockCycles(dut.clk, 4)
        assert int(dut.irq.value) == 0, (
            f"INTR_STATUS.{source}: irq still high after write-one-to-clear"
        )
        status = await tb.read_u(REG.LOG_ENGINE_INTR_STATUS_reg_u, REG.INTR_STATUS_REG_ADDR)
        assert status.val == 0, f"INTR_STATUS.{source}: 0x{status.val:x} after write-one-to-clear"
        tb.log.info("%s: forced, reported, raised irq, and cleared", source)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: enable gating")
    tb.log.info("=" * 70)
    await tb.write(REG.INTR_ENABLE_REG_ADDR, 0)
    source = random.choice(SOURCES)
    await tb.write(REG.INTR_TEST_REG_ADDR, status_word(**{source: 1}))
    await ClockCycles(dut.clk, 4)
    status = await tb.read_u(REG.LOG_ENGINE_INTR_STATUS_reg_u, REG.INTR_STATUS_REG_ADDR)
    assert getattr(status.f, source) == 1, f"{source}: status not set while disabled"
    assert int(dut.irq.value) == 0, f"{source}: irq raised with INTR_ENABLE clear"
    await tb.write(REG.INTR_ENABLE_REG_ADDR, status_word(**{source: 1}))
    await ClockCycles(dut.clk, 4)
    assert int(dut.irq.value) == 1, f"{source}: irq not raised once enabled with status pending"
    await tb.write(REG.INTR_STATUS_REG_ADDR, status_word(**{source: 1}))
    await tb.write(REG.INTR_ENABLE_REG_ADDR, status_word(log_fetch_err=1, log_write_err=1))
    await ClockCycles(dut.clk, 4)
    assert int(dut.irq.value) == 0, "irq high with no status pending"
    tb.log.info("%s: status latched while masked, irq followed the enable", source)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: fetch bus error")
    tb.log.info("=" * 70)
    index = random.randrange(NUM_LOG_ENTRIES)
    payload = random.randbytes(random.randint(1, 16))
    base = tb.load_slot(index, payload)
    tb.fetch_ram.inject_error(base, RESP_SLVERR, read=True, write=False)
    await tb.arm(index, len(payload))
    await wait_status(tb, "log_fetch_err", CYCLES_PER_BYTE * len(payload) + 400, "fetch error")
    await ClockCycles(dut.clk, 4)
    assert int(dut.irq.value) == 1, "fetch error: irq not raised"
    tb.log.info("SLVERR on the slot %d fetch at 0x%x reported LOG_FETCH_ERR and irq", index, base)
    tb.fetch_ram.clear_errors()
    await recover(tb, "log_fetch_err", "fetch error")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: write bus error")
    tb.log.info("=" * 70)
    index = random.randrange(NUM_LOG_ENTRIES)
    payload = random.randbytes(random.randint(1, 16))
    tb.load_slot(index, payload)
    tb.write_ram.inject_error(WRITE_ADDR, RESP_SLVERR, read=False, write=True)
    await tb.arm(index, len(payload))
    await wait_status(tb, "log_write_err", CYCLES_PER_BYTE * len(payload) + 400, "write error")
    await ClockCycles(dut.clk, 4)
    assert int(dut.irq.value) == 1, "write error: irq not raised"
    tb.log.info("SLVERR on the UART sink write reported LOG_WRITE_ERR and irq")
    tb.write_ram.clear_errors()
    await recover(tb, "log_write_err", "write error")

    tb.log.info("log_engine_interrupt_test PASSED (seed=%d)", seed)
