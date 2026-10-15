# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_reset_pin_deglitch_test.

Spec: clk_rst.adoc (Power-Good and Cold Reset), port_table.adoc (SMC Port Declaration).

``rst_cold_ni`` and ``rst_cool_ni`` each pass a 32-sample de-glitcher on ``clk_ref_i``. A pulse
of exactly 31 low samples is therefore ignored: a 400-sample (cold) or 100-sample (cool) hold
monitor keeps the outputs released at every sample. The pulse length is measured by counting
``clk_ref_i`` rising edges between the pin drives. A held cool pulse and a held cold pulse then
assert the primary resets (and the stable cold reset), so the monitored outputs are known to move
in this run.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp

from .smc_reset_seq_base import SmcResetSeqBase

PULSE_SAMPLES = 31
COLD_WINDOW_SAMPLES = 400
COOL_WINDOW_SAMPLES = 100
_EDGE_HISTORY = 1024


def _now_ps() -> int:
    return int(round(get_sim_time("ps")))


class _EdgeLog:
    """Rising-edge timestamps (ps) of one clock, kept in a bounded list."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.times: list[int] = []

    async def run(self, clk) -> None:
        while True:
            await RisingEdge(clk)
            self.times.append(_now_ps())
            if len(self.times) > _EDGE_HISTORY:
                del self.times[: len(self.times) - _EDGE_HISTORY]

    def edges_in(self, lo_ps: int, hi_ps: int) -> int:
        """Rising edges with ``lo < t <= hi``."""
        return sum(1 for t in self.times if lo_ps < t <= hi_ps)


class smc_reset_pin_deglitch_test_seq(SmcResetSeqBase):
    """31-sample pulses on the cold and cool pins are ignored by the de-glitchers."""

    ASSERT_BOUND_REF_CYCLES = 200
    RELEASE_BOUND_REF_CYCLES = 1000
    STEPS = ("S1", "S2", "S3")
    CHECKERS = ("CHK-COLD-31-IGNORED", "CHK-COOL-31-IGNORED")

    def __init__(self, name: str = "smc_reset_pin_deglitch_test_seq") -> None:
        super().__init__(name)
        self.cold_pulse_samples: int | None = None
        self.cool_pulse_samples: int | None = None
        self.cold_checked: int | None = None
        self.cool_checked: int | None = None
        self._step_stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_stamps.append((step_id, _now_ps()))
        cocotb.log.info("STEP %s: %s", step_id, detail)

    def _log_chk(self, chk_id: str, text: str) -> None:
        self._chk_marks.append((chk_id, _now_ps()))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _pulse(self, pin, ref_log: _EdgeLog) -> int:
        """Drive ``pin`` low for PULSE_SAMPLES clk_ref_i edges; return the measured edge count."""
        dut = cocotb.top
        third_ps = int(round(self.cfg.ref_clk_period_ns * 1000)) // 3
        await RisingEdge(dut.clk_ref_i)
        await Timer(third_ps, unit="ps")
        t_low = _now_ps()
        pin.value = 0
        for _ in range(PULSE_SAMPLES):
            await RisingEdge(dut.clk_ref_i)
        await Timer(third_ps, unit="ps")
        t_high = _now_ps()
        pin.value = 1
        measured = ref_log.edges_in(t_low, t_high)
        assert measured == PULSE_SAMPLES, (
            f"{pin._name} low pulse spanned {measured} clk_ref_i rising edges, "
            f"expected {PULSE_SAMPLES} (low at {t_low} ps, high at {t_high} ps)"
        )
        return measured

    async def body(self) -> None:
        dut = cocotb.top
        ref_log = _EdgeLog("clk_ref_i")
        ref_task = cocotb.start_soon(ref_log.run(dut.clk_ref_i))
        try:
            await self._scenario(dut, ref_log)
        finally:
            ref_task.cancel()

    async def _scenario(self, dut, ref_log: _EdgeLog) -> None:
        # S1 -- bring-up done by smc_base_test; all five observables released.
        s1 = await self._send(SmcResetOp.SAMPLE)
        assert s1.resolvable, s1
        assert s1.powergood_stable == 1, s1
        assert s1.rst_cold_stable_ref_clk_n == 1, s1
        assert s1.rst_primary_ref_clk_n == 1, s1
        assert s1.rst_primary_smc_clk_n == 1, s1
        assert s1.rst_wdt_smc_clk_n == 1, s1
        self._mark_step("S1", "SETUP all five reset observables released")

        # S2 -- 31-sample rst_cold_ni pulse inside a 400-sample hold monitor.
        monitor = cocotb.start_soon(
            self._hold_raw(
                "COLD_31_HOLD",
                hold=COLD_WINDOW_SAMPLES,
                expect_powergood_stable=1,
                expect_rst_cold_stable_ref_clk_n=1,
                expect_rst_primary_ref_clk_n=1,
                expect_rst_primary_smc_clk_n=1,
            )
        )
        self.cold_pulse_samples = await self._pulse(dut.rst_cold_ni, ref_log)
        self.cold_checked = (await monitor).hold_samples
        self._mark_step("S2", "rst_cold_ni 31-sample pulse, 400-sample hold")
        self._log_chk(
            "CHK-COLD-31-IGNORED",
            f"rst_cold_ni low for {self.cold_pulse_samples} clk_ref_i samples (expected "
            f"{PULSE_SAMPLES}); powergood_stable_o, rst_cold_stable_ref_clk_no, "
            f"rst_primary_ref_clk_no, rst_primary_smc_clk_no read 1 at all {COLD_WINDOW_SAMPLES} "
            f"clk_ref_i samples "
            f"({self.cold_checked} samples checked)",
        )

        # S3 -- 31-sample rst_cool_ni pulse inside a 100-sample hold monitor.
        monitor = cocotb.start_soon(
            self._hold_raw(
                "COOL_31_HOLD",
                hold=COOL_WINDOW_SAMPLES,
                expect_rst_cold_stable_ref_clk_n=1,
                expect_rst_primary_ref_clk_n=1,
                expect_rst_primary_smc_clk_n=1,
            )
        )
        self.cool_pulse_samples = await self._pulse(dut.rst_cool_ni, ref_log)
        self.cool_checked = (await monitor).hold_samples
        self._mark_step("S3", "rst_cool_ni 31-sample pulse, 100-sample hold")
        self._log_chk(
            "CHK-COOL-31-IGNORED",
            f"rst_cool_ni low for {self.cool_pulse_samples} clk_ref_i samples (expected "
            f"{PULSE_SAMPLES}); rst_primary_ref_clk_no and rst_primary_smc_clk_no read 1 at "
            f"all {COOL_WINDOW_SAMPLES} clk_ref_i samples",
        )

        # Positive controls: a held cool pin asserts the primary resets, and a held cold pin
        # asserts the stable cold reset and the primary resets.
        await self._send(SmcResetOp.COOL_RST_LO)
        asserted = await self._wait_state(
            "COOL_ASSERT_CONTROL",
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COOL_RST_HI)
        await self._wait_released("COOL_RELEASE_CONTROL")
        cocotb.log.info(
            "SETUP-POSITIVE-CONTROL: a held rst_cool_ni (>=32 samples) asserted the primary "
            "resets within %s ref cycles and released",
            asserted.wait_ref_cycles,
        )

        await self._send(SmcResetOp.COLD_RST_LO)
        cold_asserted = await self._wait_state(
            "COLD_ASSERT_CONTROL",
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("COLD_RELEASE_CONTROL")
        cocotb.log.info(
            "SETUP-POSITIVE-CONTROL: a held rst_cold_ni (>=32 samples) asserted the stable cold "
            "reset and the primary resets within %s ref cycles and released",
            cold_asserted.wait_ref_cycles,
        )

        self._finish_fence()

    def _finish_fence(self) -> None:
        ids = [s for s, _ in self._step_stamps]
        assert ids == list(self.STEPS), f"step order {ids}, expected {list(self.STEPS)}"
        stamps = [t for _, t in self._step_stamps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        chk_ids = [c for c, _ in self._chk_marks]
        assert chk_ids == list(self.CHECKERS), f"checker order {chk_ids}"
        step_time = dict(self._step_stamps)
        for (chk, t_chk), step in zip(self._chk_marks, ("S2", "S3")):
            assert t_chk >= step_time[step], f"{chk} printed at {t_chk} before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<PASS (positive controls after S3); checker lines "
            "%s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._step_stamps),
        )
