# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""System Timer OCTS sanity: reset defaults, CSR law, mode bit, primary count.

Scenarios:

1. Reset defaults — every register of both instances reads its RDL reset
   value, and STATUS.MODE reports each instance's ``is_primary`` pin. The
   secondary's CREDIT_EXPIRED is the exception: it spends its (zero) credits
   from reset and counts idle cycles until the first credit edge arrives.
2. Write/read law with aliasing guard — distinct values land in every
   writable register of both instances before any readback; an all-ones
   write proves only the architected bits stick; TIMER_GPIO_ENABLE drives
   its pin; CREDIT_EXPIRED is zero on the primary and counting on the
   secondary, which has received no credit yet.
3. Primary free run — TIMER_START loads the preset, the count then advances
   by one per primary clock, STATUS.RUNNING is set, and the COUNT_HI/LO
   registers agree with the counter pin. The wired secondary starts on the
   primary's sync load.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge
from system_timer_octs_base_test import (
    PORTS,
    PRESET_PRIMARY,
    PRIMARY,
    REG,
    SECONDARY,
    SystemTimerOctsTb,
    random_seed,
    reg_mask,
)


@cocotb.test()
async def system_timer_octs_sanity_test(dut) -> None:
    tb = SystemTimerOctsTb(dut, name="system_timer_octs_sanity_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: reset defaults and STATUS.MODE on both instances")
    tb.log.info("=" * 70)
    defaults = {
        "TIMER_START": (REG.TIMER_START_REG_ADDR, REG.SYSTEM_TIMER_OCTS_TIMER_START_REG_DEFAULT),
        "CTRL": (REG.CTRL_REG_ADDR, REG.SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT),
        "TIMER_PRESET_LO": (
            REG.TIMER_PRESET_LO_REG_ADDR,
            REG.SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_REG_DEFAULT,
        ),
        "TIMER_PRESET_HI": (
            REG.TIMER_PRESET_HI_REG_ADDR,
            REG.SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_REG_DEFAULT,
        ),
        "TIMER_COUNT_LO": (
            REG.TIMER_COUNT_LO_REG_ADDR,
            REG.SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_REG_DEFAULT,
        ),
        "TIMER_COUNT_HI": (
            REG.TIMER_COUNT_HI_REG_ADDR,
            REG.SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_REG_DEFAULT,
        ),
        "CREDIT_EXPIRED": (
            REG.CREDIT_EXPIRED_REG_ADDR,
            REG.SYSTEM_TIMER_OCTS_CREDIT_EXPIRED_REG_DEFAULT,
        ),
        "TIMER_GPIO_ENABLE": (
            REG.TIMER_GPIO_ENABLE_REG_ADDR,
            REG.SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_REG_DEFAULT,
        ),
    }
    checks = 0
    for port in PORTS:
        for name, (addr, expected) in defaults.items():
            if name == "CREDIT_EXPIRED" and port == SECONDARY:
                continue
            observed = await tb.read(port, addr)
            assert observed == expected, (
                f"{port} {name} reset default: expected 0x{expected:08x}, observed 0x{observed:08x}"
            )
            checks += 1
        status = await tb.read_u(port, REG.SYSTEM_TIMER_OCTS_STATUS_reg_u, REG.STATUS_REG_ADDR)
        expected_mode = 0 if port == PRIMARY else 1
        assert status.f.mode == expected_mode, (
            f"{port} STATUS.MODE {status.f.mode}, expected {expected_mode}"
        )
        assert status.f.running == 0, f"{port} STATUS.RUNNING set at reset"
    tb.log.info(
        "%d registers read their defaults; MODE follows is_primary on both instances", checks
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: write/read law with distinct values (aliasing guard)")
    tb.log.info("=" * 70)
    law = {
        "CTRL": (REG.CTRL_REG_ADDR, reg_mask(REG.SYSTEM_TIMER_OCTS_CTRL_reg_t)),
        "TIMER_PRESET_LO": (REG.TIMER_PRESET_LO_REG_ADDR, 0xFFFF_FFFF),
        "TIMER_PRESET_HI": (REG.TIMER_PRESET_HI_REG_ADDR, 0xFFFF_FFFF),
        "TIMER_GPIO_ENABLE": (
            REG.TIMER_GPIO_ENABLE_REG_ADDR,
            reg_mask(REG.SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_reg_t),
        ),
    }
    for pattern in ("random", "all-ones"):
        written = {}
        for port in PORTS:
            for name, (addr, _mask) in law.items():
                written[(port, name)] = (
                    random.getrandbits(32) if pattern == "random" else 0xFFFF_FFFF
                )
                await tb.write(port, addr, written[(port, name)])
        for port in PORTS:
            for name, (addr, mask) in law.items():
                observed = await tb.read(port, addr)
                expected = written[(port, name)] & mask
                assert observed == expected, (
                    f"{port} {name}: wrote 0x{written[(port, name)]:08x}, "
                    f"expected 0x{expected:08x}, observed 0x{observed:08x}"
                )
            await ClockCycles(tb.clk(port), 2)
            gpio = int(getattr(dut, f"{port}_gpio_enable").value)
            assert gpio == (written[(port, "TIMER_GPIO_ENABLE")] & 1), (
                f"{port}_gpio_enable pin {gpio} disagrees with the register"
            )
        tb.log.info(
            "%s pattern: both instances keep their own values; gpio_enable pins follow", pattern
        )
    for port in PORTS:
        for name, (addr, _mask) in law.items():
            await tb.write(port, addr, 0)
        await tb.write(port, REG.CTRL_REG_ADDR, REG.SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT)
    assert await tb.read(PRIMARY, REG.CREDIT_EXPIRED_REG_ADDR) == 0, (
        "primary CREDIT_EXPIRED nonzero"
    )
    idle = await tb.read(SECONDARY, REG.CREDIT_EXPIRED_REG_ADDR)
    assert idle > 0, "secondary CREDIT_EXPIRED still 0 with no credit ever received"
    tb.log.info(
        "CREDIT_EXPIRED: primary holds 0; the unsynchronized secondary counts (%d so far)", idle
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: primary loads the preset on TIMER_START and counts one per clock")
    tb.log.info("=" * 70)
    preset = (random.getrandbits(8) << 32) | PRESET_PRIMARY
    await tb.configure(PRIMARY, preset=preset)
    assert tb.count(PRIMARY) == 0, f"primary count 0x{tb.count(PRIMARY):x} before start"
    await tb.start_primary()
    await FallingEdge(dut.clk_primary)
    first = tb.count(PRIMARY)
    assert preset <= first < preset + 16, (
        f"primary count 0x{first:x} right after start; preset 0x{preset:x}"
    )
    gap = random.randint(50, 200)
    await ClockCycles(dut.clk_primary, gap)
    await FallingEdge(dut.clk_primary)
    second = tb.count(PRIMARY)
    assert second - first == gap, f"primary advanced {second - first} in {gap} clocks"
    status = await tb.read_u(PRIMARY, REG.SYSTEM_TIMER_OCTS_STATUS_reg_u, REG.STATUS_REG_ADDR)
    assert status.f.running == 1, "primary STATUS.RUNNING clear while counting"
    hi = await tb.read(PRIMARY, REG.TIMER_COUNT_HI_REG_ADDR)
    lo = await tb.read(PRIMARY, REG.TIMER_COUNT_LO_REG_ADDR)
    pin = tb.count(PRIMARY)
    assert hi == pin >> 32, f"TIMER_COUNT_HI 0x{hi:x} vs pin 0x{pin >> 32:x}"
    assert 0 <= (pin & 0xFFFF_FFFF) - lo < 64, (
        f"TIMER_COUNT_LO 0x{lo:x} too far from pin 0x{pin & 0xFFFF_FFFF:x}"
    )
    tb.log.info(
        "primary: preset 0x%x loaded, +%d in %d clocks, RUNNING set, COUNT registers track the pin",
        preset,
        second - first,
        gap,
    )

    status = await tb.read_u(SECONDARY, REG.SYSTEM_TIMER_OCTS_STATUS_reg_u, REG.STATUS_REG_ADDR)
    assert status.f.running == 1, "secondary STATUS.RUNNING clear after the primary's sync load"
    assert tb.count(SECONDARY) > 0, "secondary count still 0 after the primary's sync load"
    tb.log.info(
        "secondary followed the primary's sync load: RUNNING set, count 0x%x", tb.count(SECONDARY)
    )

    tb.log.info("system_timer_octs_sanity_test PASSED (seed=%d)", seed)
