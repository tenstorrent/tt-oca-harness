# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO interrupt OR halves to PLIC sources 284 and 285.

Spec sources: hw/sys/smc/doc/interrupts.adoc, hw/ip/gpio/doc/architecture.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

WRAPS = (4, 31, 32, 60)
LOWER = (4, 31)
UPPER = (32, 60)
LOWER_LINE = 28
UPPER_LINE = 29

_RX_ENABLE = 2 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_IRQ_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
_LSIO_DISABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_DISABLE_bm")
_LSIO_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm")
_PAD2CORE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__PAD2CORE_bm")
_TYPE_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bp")
_TYPE_LEVEL_HIGH = 0 << _TYPE_BP
_TYPE_RISING = 2 << _TYPE_BP

LINE_BOUND = 64
HOLD_CYCLES = 16
IDLE_CYCLES = 64
GATE_CYCLES = 32
PULSE_QUIET_CYCLES = 32

STEP_ORDER = ("BASELINE", "LOWER", "UPPER", "HOLD", "IDLE", "EDGE_PULSE", "RESTORE")
CHK_ORDER = (
    "CHK-OR-LOWER",
    "CHK-OR-UPPER",
    "CHK-OR-HOLD-UNTIL-ALL-CLEAR",
    "CHK-OR-IDLE",
    "CHK-OR-EDGE-PULSE",
)


def _data_ctrl(wrap: int) -> int:
    return smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", wrap)


class smc_gpio_irq_or_test_seq(SmcCsrSeq):
    """Raw GPIO interrupts of four wraps against the two OR-reduced lines."""

    def __init__(self, name: str = "smc_gpio_irq_or_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.lsio_dis: dict[int, int] = {}
        self.waits: list[tuple[str, int, str]] = []
        self.drive_en = 0
        self.drive_val = 0

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    @staticmethod
    def _sample(dut) -> tuple[int, int]:
        """Return (raw per-wrap vector, tb_peripheral_interrupts) for one cycle."""
        raw = dut.tb_gpio_interrupt.value
        per = dut.tb_peripheral_interrupts.value
        assert raw.is_resolvable, f"tb_gpio_interrupt unresolvable {raw}"
        assert per.is_resolvable, f"tb_peripheral_interrupts unresolvable {per}"
        return int(raw), int(per)

    @staticmethod
    def _bit(vec: int, idx: int) -> int:
        return (vec >> idx) & 1

    def _lines(self, dut) -> tuple[int, int]:
        _, per = self._sample(dut)
        return self._bit(per, LOWER_LINE), self._bit(per, UPPER_LINE)

    def _drive(self, dut, wrap: int, level: int | None) -> None:
        """Update the shadow of the bench drive vectors; reads would miss pending writes."""
        mask = 1 << wrap
        if level is None:
            self.drive_en &= ~mask
        else:
            self.drive_en |= mask
            self.drive_val = (self.drive_val | mask) if level else (self.drive_val & ~mask)
        dut.tb_gpio_ext_drive_en.value = self.drive_en
        dut.tb_gpio_ext_drive_value.value = self.drive_val

    async def _wait(self, name: str, cond, state) -> int:
        """Poll `cond()` once per clk_smc_i cycle; raise with `state()` on expiry."""
        dut = cocotb.top
        for cycle in range(LINE_BOUND + 1):
            if cond():
                self.waits.append((name, LINE_BOUND, f"met@{cycle}"))
                return cycle
            await ClockCycles(dut.clk_smc_i, 1)
        last = state()
        self.waits.append((name, LINE_BOUND, f"EXPIRED {last}"))
        raise AssertionError(f"{name}: not met within {LINE_BOUND} cycles, last {last}")

    async def _hold(self, label: str, want_lower: int | None, want_upper: int | None) -> None:
        dut = cocotb.top
        for cycle in range(HOLD_CYCLES):
            lo, up = self._lines(dut)
            assert want_lower is None or lo == want_lower, (
                f"{label}: [28]={lo} want {want_lower} at hold cycle {cycle}"
            )
            assert want_upper is None or up == want_upper, (
                f"{label}: [29]={up} want {want_upper} at hold cycle {cycle}"
            )
            await ClockCycles(dut.clk_smc_i, 1)

    def _cfg(self, wrap: int, irq_type: int, irq_enable: bool) -> int:
        word = _RX_ENABLE | _IF_ENABLE | irq_type | self.lsio_dis[wrap]
        return word | (_IRQ_ENABLE if irq_enable else 0)

    async def _program(self, wrap: int, irq_type: int, irq_enable: bool) -> None:
        word = self._cfg(wrap, irq_type, irq_enable)
        await self.csr_write(f"GPIO{wrap}_CFG", _data_ctrl(wrap), word)

    async def _arm_level(self, wrap: int) -> None:
        await self._program(wrap, _TYPE_LEVEL_HIGH, True)

    # ---- steps ----
    async def _s1(self) -> None:
        dut = cocotb.top
        for name in ("tb_gpio_interrupt", "tb_peripheral_interrupts", "tb_spi_enable"):
            assert hasattr(dut, name), f"tb_top probe {name} missing"
        assert int(dut.tb_spi_enable.value) == 0, "tb_spi_enable is not low"
        dut.tb_gpio_ext_drive_en.value = 0
        dut.tb_gpio_ext_drive_value.value = 0
        for wrap in WRAPS:
            self._drive(dut, wrap, 0)
            await self.csr_write(f"GPIO{wrap}_ZERO", _data_ctrl(wrap), 0)
            word = await self.csr_read(f"GPIO{wrap}_LSIO", _data_ctrl(wrap))
            self.lsio_dis[wrap] = 0
            if word & _LSIO_ENABLE:
                self.lsio_dis[wrap] = _LSIO_DISABLE
                await self.csr_write(f"GPIO{wrap}_LSIO_DIS", _data_ctrl(wrap), _LSIO_DISABLE)
                word = await self.csr_read(f"GPIO{wrap}_LSIO2", _data_ctrl(wrap))
                assert not word & _LSIO_ENABLE, f"wrap {wrap}: lsio_enable still 1 (0x{word:08x})"
        raw, per = self._sample(dut)
        assert self._bit(per, LOWER_LINE) == 0 and self._bit(per, UPPER_LINE) == 0, (
            f"baseline: tb_peripheral_interrupts[29:28]=0x{(per >> 28) & 3:x} want 0"
        )
        assert raw == 0, f"baseline: tb_gpio_interrupt=0x{raw:x} want 0"
        self._mark("BASELINE")

    async def _level_one(self, wrap: int, mine: int, other: int) -> str:
        """Assert one wrap, require its half and not the other, then release."""
        dut = cocotb.top
        await self._arm_level(wrap)
        self._drive(dut, wrap, 1)

        def lines() -> tuple[int, int]:
            return self._lines(dut)

        await self._wait(
            f"wrap{wrap}_raw",
            lambda: self._bit(self._sample(dut)[0], wrap) == 1,
            lambda: hex(self._sample(dut)[0]),
        )
        cyc = await self._wait(
            f"wrap{wrap}_line{mine}",
            lambda: self._bit(self._sample(dut)[1], mine) == 1,
            lambda: hex(self._sample(dut)[1]),
        )
        for i in range(HOLD_CYCLES):
            _, per = self._sample(dut)
            assert self._bit(per, mine) == 1, f"wrap {wrap}: [{mine}] dropped at hold {i}"
            assert self._bit(per, other) == 0, f"wrap {wrap}: [{other}] asserted at hold {i}"
            await ClockCycles(dut.clk_smc_i, 1)
        self._drive(dut, wrap, 0)
        await self._wait(
            f"wrap{wrap}_line{mine}_clear",
            lambda: self._bit(self._sample(dut)[1], mine) == 0,
            lambda: hex(self._sample(dut)[1]),
        )
        assert lines() == (0, 0), f"wrap {wrap}: lines {lines()} after clear"
        await self._program(wrap, _TYPE_LEVEL_HIGH, False)
        return f"wrap{wrap}:[{mine}] after {cyc} cycles"

    async def _s2(self) -> str:
        out = [await self._level_one(w, LOWER_LINE, UPPER_LINE) for w in LOWER]
        self._mark("LOWER")
        return "; ".join(out)

    async def _s3(self) -> str:
        out = [await self._level_one(w, UPPER_LINE, LOWER_LINE) for w in UPPER]
        self._mark("UPPER")
        return "; ".join(out)

    async def _s4(self) -> str:
        dut = cocotb.top
        for wrap in WRAPS:
            await self._arm_level(wrap)
        for wrap in WRAPS:
            self._drive(dut, wrap, 1)
        await self._wait(
            "all_lines_set",
            lambda: self._lines(dut) == (1, 1),
            lambda: hex(self._sample(dut)[1]),
        )
        contributors = {LOWER_LINE: set(LOWER), UPPER_LINE: set(UPPER)}
        half_of = {4: LOWER_LINE, 31: LOWER_LINE, 32: UPPER_LINE, 60: UPPER_LINE}
        trace = []
        for wrap in (4, 32, 31, 60):
            half = half_of[wrap]
            self._drive(dut, wrap, 0)
            await self._wait(
                f"wrap{wrap}_raw_clear",
                lambda w=wrap: self._bit(self._sample(dut)[0], w) == 0,
                lambda: hex(self._sample(dut)[0]),
            )
            contributors[half].discard(wrap)
            other = UPPER_LINE if half == LOWER_LINE else LOWER_LINE
            if contributors[half]:
                await self._hold(
                    f"after clear {wrap}",
                    1 if half == LOWER_LINE else None,
                    1 if half == UPPER_LINE else None,
                )
            else:
                await self._wait(
                    f"half{half}_drop_after_{wrap}",
                    lambda h=half: self._bit(self._sample(dut)[1], h) == 0,
                    lambda: hex(self._sample(dut)[1]),
                )
            if contributors[other]:
                assert self._bit(self._sample(dut)[1], other) == 1, (
                    f"after clear {wrap}: [{other}] dropped while "
                    f"{sorted(contributors[other])} asserted"
                )
            lo, up = self._lines(dut)
            trace.append(f"clear{wrap}->[28]={lo},[29]={up}")
        assert self._lines(dut) == (0, 0), f"lines {self._lines(dut)} after all cleared"
        for wrap in WRAPS:
            await self._program(wrap, _TYPE_LEVEL_HIGH, False)
        self._mark("HOLD")
        return ", ".join(trace) + f"; hold window {HOLD_CYCLES} cycles"

    async def _s5(self) -> str:
        dut = cocotb.top
        for wrap in (4, 60):
            await self._arm_level(wrap)
            self._drive(dut, wrap, 1)
            line = LOWER_LINE if wrap in LOWER else UPPER_LINE
            await self._wait(
                f"control{wrap}_set",
                lambda ln=line: self._bit(self._sample(dut)[1], ln) == 1,
                lambda: hex(self._sample(dut)[1]),
            )
            self._drive(dut, wrap, 0)
            await self._wait(
                f"control{wrap}_release",
                lambda ln=line: self._bit(self._sample(dut)[1], ln) == 0,
                lambda: hex(self._sample(dut)[1]),
            )
            await self._program(wrap, _TYPE_LEVEL_HIGH, False)
        for wrap in (4, 60):
            line = LOWER_LINE if wrap in LOWER else UPPER_LINE
            self._drive(dut, wrap, 1)
            for i in range(GATE_CYCLES):
                per = self._sample(dut)[1]
                assert self._bit(per, line) == 0, (
                    f"wrap {wrap} pad high with interrupt_enable clear: line [{line}] rose at "
                    f"cycle {i} ({hex(per)})"
                )
                await ClockCycles(dut.clk_smc_i, 1)
            self._drive(dut, wrap, 0)
            await ClockCycles(dut.clk_smc_i, HOLD_CYCLES)
        for i in range(IDLE_CYCLES):
            raw, per = self._sample(dut)
            assert raw == 0, f"idle cycle {i}: tb_gpio_interrupt=0x{raw:x}"
            assert (per >> 28) & 3 == 0, f"idle cycle {i}: [29:28]=0x{(per >> 28) & 3:x}"
            await ClockCycles(dut.clk_smc_i, 1)
        self._mark("IDLE")
        return (
            f"interrupt_enable clear on wraps {WRAPS}: pads 4 and 60 driven high for {GATE_CYCLES} "
            f"cycles each left their line 0; then pads low, [29:28]=0 and raw vector 0 for "
            f"{IDLE_CYCLES} cycles, after positive controls on wraps 4 and 60 set and released"
        )

    async def _pulse(self, wrap: int) -> tuple[int, int, int]:
        dut = cocotb.top
        line = LOWER_LINE if wrap in LOWER else UPPER_LINE
        other = UPPER_LINE if line == LOWER_LINE else LOWER_LINE
        await self._program(wrap, _TYPE_RISING, True)
        raw_tr: list[int] = []
        line_tr: list[int] = []

        def take() -> None:
            raw, per = self._sample(dut)
            raw_tr.append(self._bit(raw, wrap))
            line_tr.append(self._bit(per, line))
            assert self._bit(per, other) == 0, f"wrap {wrap}: [{other}] asserted on edge pulse"

        take()
        assert raw_tr[0] == 0 and line_tr[0] == 0, f"wrap {wrap}: pre-edge raw/line not 0"
        self._drive(dut, wrap, 1)
        for _ in range(LINE_BOUND + 1):
            await ClockCycles(dut.clk_smc_i, 1)
            take()
            if 1 in raw_tr and raw_tr[-1] == 0 and 1 in line_tr and line_tr[-1] == 0:
                break
        else:
            self.waits.append((f"pulse{wrap}", LINE_BOUND, "EXPIRED"))
            raise AssertionError(f"wrap {wrap}: pulse incomplete raw={raw_tr} line={line_tr}")
        self.waits.append((f"pulse{wrap}", LINE_BOUND, f"done@{len(raw_tr)}"))
        for _ in range(PULSE_QUIET_CYCLES):
            await ClockCycles(dut.clk_smc_i, 1)
            take()

        def pulses(tr: list[int]) -> list[int]:
            widths, run = [], 0
            for v in tr:
                if v:
                    run += 1
                elif run:
                    widths.append(run)
                    run = 0
            if run:
                widths.append(run)
            return widths

        rw, lw = pulses(raw_tr), pulses(line_tr)
        assert len(lw) == 1, f"wrap {wrap}: line pulses {lw}, want exactly one"
        assert len(rw) == 1, f"wrap {wrap}: raw pulses {rw}, want exactly one"
        assert lw[0] <= rw[0], f"wrap {wrap}: line width {lw[0]} wider than raw {rw[0]}"
        assert lw[0] == rw[0], f"wrap {wrap}: line width {lw[0]} != raw width {rw[0]}"
        assert not any(line_tr[-PULSE_QUIET_CYCLES:]), f"wrap {wrap}: line not 0 after pulse"
        self._drive(dut, wrap, 0)
        await self._program(wrap, _TYPE_LEVEL_HIGH, False)
        return line, rw[0], lw[0]

    async def _s6(self) -> str:
        out = []
        for wrap in (4, 60):
            line, rw, lw = await self._pulse(wrap)
            out.append(
                f"wrap{wrap} type2 pulse: [{line}] pulsed once, width {lw} clk_smc_i cycles, "
                f"raw bit width {rw} clk_smc_i cycles, equal"
            )
        self._mark("EDGE_PULSE")
        return "; ".join(out) + f"; line 0 for {PULSE_QUIET_CYCLES} cycles after each"

    async def _s7(self) -> None:
        dut = cocotb.top
        dut.tb_gpio_ext_drive_en.value = 0
        dut.tb_gpio_ext_drive_value.value = 0
        mask = ~(_PAD2CORE | _LSIO_ENABLE) & 0xFFFFFFFF
        for wrap in WRAPS:
            await self.csr_write(f"GPIO{wrap}_RESTORE", _data_ctrl(wrap), 0)
            word = await self.csr_read(f"GPIO{wrap}_RESTORE_RB", _data_ctrl(wrap))
            assert word & mask == 0, f"wrap {wrap}: DATA_CTRL 0x{word:08x} after restore"
        self._mark("RESTORE")

    async def body(self) -> None:
        await self._s1()
        self._chk("LOWER", "CHK-OR-LOWER", await self._text2())
        self._chk("UPPER", "CHK-OR-UPPER", await self._text3())
        self._chk("HOLD", "CHK-OR-HOLD-UNTIL-ALL-CLEAR", await self._s4())
        self._chk("IDLE", "CHK-OR-IDLE", await self._s5())
        self._chk("EDGE_PULSE", "CHK-OR-EDGE-PULSE", await self._s6())
        await self._s7()
        self.assert_all_reachable(self.accesses, "GPIO_IRQ_OR")
        self._nonvac()

    async def _text2(self) -> str:
        return "level type 0 one wrap at a time, " + await self._s2() + "; the other line stayed 0"

    async def _text3(self) -> str:
        return "level type 0 one wrap at a time, " + await self._s3() + "; the other line stayed 0"

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(c for _, c in self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        step_ids = [s for s, _ in self.chk_steps]
        assert step_ids == ["LOWER", "UPPER", "HOLD", "IDLE", "EDGE_PULSE"], (
            f"checker steps {step_ids}"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BASELINE < LOWER < UPPER < HOLD < IDLE < EDGE_PULSE < "
            "RESTORE; checker lines %s; stamps %s",
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
