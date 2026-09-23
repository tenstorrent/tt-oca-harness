# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reprogramming the AVSBus clock divider and measuring the clock it produces.

`AVS_CFG_1.AVS_CLOCK_SELECT` resets to a divided source (`avsbus_controller.rdl`
gives the field a reset of 3, "a divided version of refclk"), so the divider is
already in the AVS clock path and `AVS_CFG_1.CLK_DIVIDER_VALUE` sets its
divisor. The register reset of that field is 0, which the RDL describes as
keeping the hardware default of 4 by matching the reset value of the resynced
copy the divider compares against; the field takes a minimum of 2.

Every leaf so far leaves the divider at that reset, so nothing shows that a
written divisor reaches the clock at all. This one writes a divisor, measures
the period of `avs_clk` at the pad, and requires the measured period to scale
with the divisor. The duty-cycle numerator is then changed on its own and the
high fraction of the period measured, because the divider compares the two
settings separately and a change to either has to take effect.

`AVS_CFG_1.TURN_OFF_ALL_PREMUX_CLOCKS` is set around each change, which is the
order the register documentation prescribes: gate the clocks entering the mux,
change the divider settings, then turn them back on.

Writing the register's own reset value back does not return the clock to its
reset rate: both fields reset to 0, which is below the minimum the divider
assumes, so the leaf restores the hardware defaults the RDL names instead and
leaves them written.

The observable is `tb_avs_clk_from_dut`, the AVS clock the block drives onto
its pad. Nothing else in this leaf can move it.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Edge, First, Timer
from cocotb.utils import get_sim_time

from .smc_avsbus_protocol_utils import AVS_CFG_1, avs_field
from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_SELECT_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__AVS_CLOCK_SELECT_bm")
DIVIDER_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__CLK_DIVIDER_VALUE_bm")
DIVIDER_BP = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__CLK_DIVIDER_VALUE_bp")
NUMERATOR_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__CLK_DIVIDER_DUTY_CYCLE_NUMERATOR_bm")
NUMERATOR_BP = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__CLK_DIVIDER_DUTY_CYCLE_NUMERATOR_bp")
PREMUX_OFF_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__TURN_OFF_ALL_PREMUX_CLOCKS_bm")
STOP_ON_IDLE_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__STOP_AVS_CLOCK_ON_IDLE_bm")

#: The divided clock-select encodings, from the field description in the RDL.
DIVIDED_SELECTS = (1, 3)
#: The hardware default the RDL names for a divisor field left at its reset.
DEFAULT_DIVISOR = 4
#: The divisors written, each double the last so a wrong scaling cannot pass
#: as the right one.
DIVISORS = (8, 16)
#: A quarter duty cycle: the numerator is divided by 256 to give the high
#: fraction of the period.
QUARTER_NUMERATOR = 0x40
#: The hardware default numerator the RDL names for a numerator field left at
#: its reset, which is half of 256.
DEFAULT_NUMERATOR = 0x80
#: The divisor the RDL says is assumed for any written value below it.
MINIMUM_DIVISOR = 2
#: Edges timed per measurement. Several periods average out the one source
#: cycle the divider may take either way on an odd divisor.
MEASURE_PERIODS = 8
#: An AVS clock period is orders of magnitude shorter than this, so the bound
#: only catches a clock that has stopped.
EDGE_TIMEOUT_NS = 100_000
SETTLE_CYCLES = 200
#: The measured ratio is allowed this much slack against the programmed one,
#: which covers the sampling of the two edges that bound a measurement.
RATIO_TOLERANCE = 0.05


class smc_avsbus_clock_divider_test_seq(SmcCsrSeq):
    """A written divisor and duty cycle must reach the AVS clock at the pad."""

    def __init__(self, name: str = "smc_avsbus_clock_divider_test_seq") -> None:
        super().__init__(name)

    @staticmethod
    def _clk() -> int:
        raw = cocotb.top.tb_avs_clk_from_dut.value
        assert raw.is_resolvable, f"the AVS clock at the pad is not resolvable: {raw}"
        return int(raw)

    async def _next_edge(self, label: str) -> None:
        """Wait for either edge of the AVS clock, or fail if it has stopped."""
        result = await First(
            Edge(cocotb.top.tb_avs_clk_from_dut), Timer(EDGE_TIMEOUT_NS, unit="ns")
        )
        if not isinstance(result, Edge):
            raise AssertionError(
                f"{label}: the AVS clock at the pad did not change in {EDGE_TIMEOUT_NS} ns; "
                f"it reads {self._clk()} and the measurement below needs it running"
            )

    async def _measure(self, label: str) -> tuple[float, float]:
        """Mean period in ns, and the high fraction of it, over several periods."""
        while self._clk() != 0:
            await self._next_edge(f"{label} align low")
        await self._next_edge(f"{label} first rise")
        start = get_sim_time("ns")
        high_ns = 0.0
        rose = start
        for period in range(MEASURE_PERIODS):
            await self._next_edge(f"{label} fall {period}")
            high_ns += get_sim_time("ns") - rose
            await self._next_edge(f"{label} rise {period}")
            rose = get_sim_time("ns")
        span = rose - start
        assert span > 0, f"{label}: {MEASURE_PERIODS} AVS clock periods measured 0 ns"
        return span / MEASURE_PERIODS, high_ns / span

    async def _program(self, label: str, base: int, divisor: int, numerator: int) -> int:
        """Write one divider setting the way the register documentation prescribes."""
        want = base & ~(DIVIDER_BM | NUMERATOR_BM | PREMUX_OFF_BM)
        want |= (divisor << DIVIDER_BP) & DIVIDER_BM
        want |= (numerator << NUMERATOR_BP) & NUMERATOR_BM
        await self.csr_write(f"AVS_CFG_1_PREMUX_OFF_{label}", AVS_CFG_1, base | PREMUX_OFF_BM)
        await self.csr_write(f"AVS_CFG_1_{label}", AVS_CFG_1, want | PREMUX_OFF_BM)
        await self.csr_write(f"AVS_CFG_1_PREMUX_ON_{label}", AVS_CFG_1, want)
        await self.csr_read(f"AVS_CFG_1_{label}_RB", AVS_CFG_1, expected=want)
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        return want

    async def body(self) -> None:
        cfg1 = await self.csr_read("AVS_CFG_1_SAVE", AVS_CFG_1)
        select = cfg1 & CLOCK_SELECT_BM
        assert select in DIVIDED_SELECTS, (
            f"AVS_CLOCK_SELECT reads {select}, which is an undivided source; the divider is "
            f"then out of the clock path and nothing below could measure its effect"
        )
        assert (cfg1 & STOP_ON_IDLE_BM) == 0, (
            f"STOP_AVS_CLOCK_ON_IDLE is set (AVS_CFG_1=0x{cfg1:08x}); the clock would stop "
            f"between commands and a period measured across the gap would be meaningless"
        )
        numerator = (cfg1 & NUMERATOR_BM) >> NUMERATOR_BP

        # The reset divisor, measured before anything is written, is what the
        # written divisors are judged against.
        base_period, base_duty = await self._measure("DEFAULT")
        cocotb.log.info(
            "AVS clock at the reset divider setting: %.2f ns period, %.1f%% high",
            base_period,
            100 * base_duty,
        )

        measured: list[tuple[int, float]] = []
        for divisor in DIVISORS:
            await self._program(f"DIV{divisor}", cfg1, divisor, numerator)
            period, _ = await self._measure(f"DIV{divisor}")
            want = base_period * divisor / DEFAULT_DIVISOR
            ratio = period / want
            assert abs(ratio - 1.0) <= RATIO_TOLERANCE, (
                f"divisor {divisor}: the AVS clock period measured {period:.2f} ns, but a "
                f"divisor of {divisor} against the reset divisor of {DEFAULT_DIVISOR} at "
                f"{base_period:.2f} ns predicts {want:.2f} ns (off by {100 * (ratio - 1):.1f}%)"
            )
            measured.append((divisor, period))
        cocotb.log.info(
            "CHK-AVS-CLKDIV-PERIOD: each written divisor reached the AVS clock at the pad: "
            "%s, against %.2f ns at the reset divisor of %d",
            ", ".join(f"{d} -> {p:.2f} ns" for d, p in measured),
            base_period,
            DEFAULT_DIVISOR,
        )

        # Only the numerator changes now. The divider holds the previous
        # divisor and compares the two settings separately, so this leg moves
        # the duty cycle without moving the period.
        held_divisor = DIVISORS[-1]
        held_period = measured[-1][1]
        await self._program("DUTY", cfg1, held_divisor, QUARTER_NUMERATOR)
        duty_period, duty = await self._measure("DUTY")
        want_duty = QUARTER_NUMERATOR / 256
        assert abs(duty - want_duty) <= RATIO_TOLERANCE, (
            f"duty numerator 0x{QUARTER_NUMERATOR:02x} asks for {100 * want_duty:.1f}% high, "
            f"but the AVS clock measured {100 * duty:.1f}% high"
        )
        assert abs(duty_period / held_period - 1.0) <= RATIO_TOLERANCE, (
            f"the duty-cycle change moved the period too: {duty_period:.2f} ns against "
            f"{held_period:.2f} ns at the same divisor of {held_divisor}"
        )
        cocotb.log.info(
            "CHK-AVS-CLKDIV-DUTY: numerator 0x%02x on its own took the AVS clock to %.1f%% "
            "high at an unchanged %.2f ns period",
            QUARTER_NUMERATOR,
            100 * duty,
            duty_period,
        )

        # A divisor below the minimum. The RDL says 2 is assumed for anything
        # lower, so writing the field's own reset value of 0 does not return
        # the clock to its reset rate: it halves the source instead.
        await self._program("CLAMP", cfg1, 0, DEFAULT_NUMERATOR)
        clamped, _ = await self._measure("CLAMP")
        want_clamped = base_period * MINIMUM_DIVISOR / DEFAULT_DIVISOR
        assert abs(clamped / want_clamped - 1.0) <= RATIO_TOLERANCE, (
            f"a written divisor of 0 gave a {clamped:.2f} ns AVS clock period; the minimum "
            f"divisor of {MINIMUM_DIVISOR} against the reset divisor of {DEFAULT_DIVISOR} at "
            f"{base_period:.2f} ns predicts {want_clamped:.2f} ns"
        )
        cocotb.log.info(
            "CHK-AVS-CLKDIV-MINIMUM: a written divisor of 0 was taken as the minimum of %d, "
            "giving %.2f ns against %.2f ns at the reset divisor of %d",
            MINIMUM_DIVISOR,
            clamped,
            base_period,
            DEFAULT_DIVISOR,
        )

        # Back to the reset rate. It is reached by writing the hardware
        # defaults the RDL names, not by writing the register's reset value:
        # the divider compares what it is given, and 0 is below its minimum.
        await self._program("RESTORE", cfg1, DEFAULT_DIVISOR, DEFAULT_NUMERATOR)
        restored, restored_duty = await self._measure("RESTORE")
        assert abs(restored / base_period - 1.0) <= RATIO_TOLERANCE, (
            f"the AVS clock did not return to its reset period: {restored:.2f} ns against "
            f"{base_period:.2f} ns, after the hardware-default divisor of {DEFAULT_DIVISOR} "
            f"and numerator 0x{DEFAULT_NUMERATOR:02x} were written"
        )
        assert abs(restored_duty - base_duty) <= RATIO_TOLERANCE, (
            f"the AVS clock returned to its reset period at {100 * restored_duty:.1f}% high "
            f"against {100 * base_duty:.1f}% before any change"
        )
        cocotb.log.info(
            "CHK-AVS-CLKDIV-RESTORE: the hardware-default divisor %d and numerator 0x%02x "
            "returned the AVS clock to %.2f ns at %.1f%% high, against %.2f ns at %.1f%% "
            "before any change. AVS_CFG_1 is left holding them, because its own reset value "
            "of 0 in both fields is below the divider's minimum and would not",
            DEFAULT_DIVISOR,
            DEFAULT_NUMERATOR,
            restored,
            100 * restored_duty,
            base_period,
            100 * base_duty,
        )
