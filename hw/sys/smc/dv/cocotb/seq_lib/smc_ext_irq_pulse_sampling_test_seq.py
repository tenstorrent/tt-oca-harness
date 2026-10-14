# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Pulses on tb_ext_interrupt_0_i against raw bit 0 of tb_cpu_interrupts.

Spec sources: port_table.adoc smc_ext_interrupts_i, interrupts.adoc SMC interrupts and PLIC.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
# TB ceiling in clk_smc_i rises for every pin-to-raw-bit wait; not a latency claim.
CEILING_RISES = 64
WIDE_WIDTH_CYCLES = (4, 8, 16)
SHORT_WIDTH_QUARTERS = (1, 2, 3)
PHASE_QUARTERS = (0, 1, 2, 3)
LATENCY_REPEATS = 8
LATENCY_HOLD_RISES = 32
_STEPS = ("S1", "S2", "S3", "S4")
_CHECKERS = (
    "CHK-EXTPULSE-WIDE-LOG",
    "CHK-EXTPULSE-SHORT-NOLATCH",
    "CHK-EXTPULSE-SHORT-SEEN-LOG",
    "CHK-EXTPULSE-LATENCY-LOG",
)
_CHECK_STEP = ("S2", "S3", "S3", "S4")


class smc_ext_irq_pulse_sampling_test_seq(SmcCsrSeq):
    """Drive pin pulses of chosen width and phase and sample raw bit 0 each clk_smc_i rise."""

    def __init__(self, name: str = "smc_ext_irq_pulse_sampling_test_seq") -> None:
        super().__init__(name)
        self.wide_runs = 0
        self.short_runs = 0
        self.latency_runs = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}
        self._period_ps = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _vector(label: str) -> int:
        sig = cocotb.top.tb_cpu_interrupts
        assert sig.value.is_resolvable, f"{label}: tb_cpu_interrupts is X/Z ({sig.value})"
        return int(sig.value)

    async def _measure_period_ps(self) -> int:
        clk = cocotb.top.clk_smc_i
        await RisingEdge(clk)
        first = int(get_sim_time("ps"))
        await RisingEdge(clk)
        period = int(get_sim_time("ps")) - first
        assert period > 0, f"clk_smc_i period {period} ps"
        return period

    @staticmethod
    def _drive(value: int, why: str) -> None:
        cocotb.top.tb_ext_interrupt_0_i.value = value
        cocotb.log.info(
            "DRIVE tb_ext_interrupt_0_i=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    async def _sample_rises(self, count: int, out: list[int], label: str) -> None:
        for n in range(count):
            await RisingEdge(cocotb.top.clk_smc_i)
            out.append(self._vector(f"{label}[{n}]"))

    async def _pulse(self, width_fs: int, phase_q: int, window: int, label: str) -> list[int]:
        """Drive one pulse after a clk_smc_i rise and return the vector at `window` rises."""
        await RisingEdge(cocotb.top.clk_smc_i)
        samples: list[int] = []
        sampler = cocotb.start_soon(self._sample_rises(window, samples, label))
        if phase_q:
            await Timer(phase_q * self._period_ps * 250, unit="fs")
        self._drive(1, f"{label} rise")
        await Timer(width_fs, unit="fs")
        self._drive(0, f"{label} fall")
        await sampler
        assert len(samples) == window, f"{label}: {len(samples)} samples, want {window}"
        return samples

    @staticmethod
    def _high_runs(bits: list[int]) -> int:
        return sum(1 for i, b in enumerate(bits) if b and (i == 0 or not bits[i - 1]))

    async def _rises_until(self, name: str, want: int, bound: int) -> tuple[int, int]:
        """Count clk_smc_i rises until raw bit 0 equals want; returns (rises, vector)."""
        last = self._vector(f"{name} entry")
        self._waits[name] = (bound, f"bit0={last & 1} vector=0x{last:x}")
        for n in range(1, bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            last = self._vector(f"{name}[{n}]")
            self._waits[name] = (bound, f"bit0={last & 1} vector=0x{last:x} after {n} rises")
            if last & 1 == want:
                return n, last
        raise AssertionError(
            f"{name}: raw bit 0 did not reach {want} within {bound} clk_smc_i rises "
            f"(last vector 0x{last:x})"
        )

    async def _wide_pulses(self, base: int) -> str:
        parts = []
        for cycles in WIDE_WIDTH_CYCLES:
            for phase_q in PHASE_QUARTERS:
                window = cycles + CEILING_RISES
                label = f"WIDE w={cycles}cyc ph={phase_q}/4"
                samples = await self._pulse(cycles * self._period_ps * 1000, phase_q, window, label)
                bits = [v & 1 for v in samples]
                high = sum(bits)
                moved = [hex(v) for v in samples if v & ~1 != base & ~1]
                assert not moved, f"{label}: another raw bit moved {moved[:2]} (base 0x{base:x})"
                assert bits[-1] == 0, f"{label}: raw bit 0 still 1 at the {window}-rise window end"
                self.wide_runs += 1
                parts.append(f"w{cycles}/ph{phase_q}:pulsed={int(high > 0)},high={high}")
                cocotb.log.info(
                    "WIDE %s pulsed=%d high_samples=%d window=%d",
                    label,
                    int(high > 0),
                    high,
                    window,
                )
        return "; ".join(parts)

    async def _short_pulses(self, base: int) -> tuple[str, str]:
        parts = []
        seen = []
        for quarters in SHORT_WIDTH_QUARTERS:
            for phase_q in PHASE_QUARTERS:
                label = f"SHORT w={quarters}/4T ph={phase_q}/4"
                width_fs = quarters * self._period_ps * 250
                samples = await self._pulse(width_fs, phase_q, 2 * CEILING_RISES, label)
                bits = [v & 1 for v in samples]
                first = samples[:CEILING_RISES]
                assert bits[CEILING_RISES - 1] == 0, (
                    f"{label}: raw bit 0 still 1 at the {CEILING_RISES}-rise ceiling"
                )
                assert self._high_runs(bits) <= 1, f"{label}: raw bit 0 re-rose, bits {bits}"
                bad = [hex(v) for v in first if v & ~1 != base & ~1]
                assert not bad, f"{label}: another raw bit moved {bad[:2]} (base 0x{base:x})"
                for n, v in enumerate(samples[CEILING_RISES:], start=1):
                    assert v == base, (
                        f"{label}: vector 0x{v:x} != baseline 0x{base:x} at hold rise {n}"
                    )
                high = sum(bits)
                self.short_runs += 1
                kind = "nothing" if high == 0 else f"pulse of {high} samples"
                parts.append(f"w{quarters}/4T/ph{phase_q}/4")
                seen.append(f"w{quarters}/4T/ph{phase_q}/4:{kind}")
                cocotb.log.info("SHORT %s width_fs=%d seen=%s", label, width_fs, kind)
        return "; ".join(parts), "; ".join(seen)

    async def _latency(self) -> str:
        rises, falls = [], []
        clk = cocotb.top.clk_smc_i
        for rep in range(LATENCY_REPEATS):
            await RisingEdge(clk)
            self._drive(1, f"latency repeat {rep} rise")
            n_rise, _ = await self._rises_until("LATENCY-RISE", 1, CEILING_RISES)
            for _ in range(max(0, LATENCY_HOLD_RISES - n_rise)):
                await RisingEdge(clk)
            self._drive(0, f"latency repeat {rep} fall")
            n_fall, _ = await self._rises_until("LATENCY-FALL", 0, CEILING_RISES)
            for _ in range(max(0, LATENCY_HOLD_RISES - n_fall)):
                await RisingEdge(clk)
            rises.append(n_rise)
            falls.append(n_fall)
            self.latency_runs += 1
            cocotb.log.info(
                "LATENCY repeat %d rise=%d fall=%d clk_smc_i rises", rep, n_rise, n_fall
            )
        return (
            f"rise rises {rises} min={min(rises)} max={max(rises)}; "
            f"fall rises {falls} min={min(falls)} max={max(falls)}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_ext_interrupt_0_i"), "tb_ext_interrupt_0_i missing"
        assert hasattr(dut, "tb_cpu_interrupts"), "tb_cpu_interrupts missing"
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info(
            "SEED RANDOM_SEED=%s SCRATCH_COLD_WARM_0=0x%x", os.environ.get("RANDOM_SEED", "1"), got
        )
        self._drive(0, "idle before baseline")
        self._period_ps = await self._measure_period_ps()
        base = self._vector("baseline")
        assert base & 1 == 0, f"baseline raw bit 0 reads 1 (vector 0x{base:x})"
        cocotb.log.info("BASELINE vector=0x%x clk_smc_i period=%d ps", base, self._period_ps)
        self._mark_step("S1")

        wide = await self._wide_pulses(base)
        assert self.wide_runs == len(WIDE_WIDTH_CYCLES) * len(PHASE_QUARTERS)
        self._mark_step("S2")
        self._log_chk("CHK-EXTPULSE-WIDE-LOG", f"{self.wide_runs} wide pulses logged: {wide}")

        short, seen = await self._short_pulses(base)
        assert self.short_runs == len(SHORT_WIDTH_QUARTERS) * len(PHASE_QUARTERS)
        self._mark_step("S3")
        cocotb.log.info(
            "LIFECYCLE CHK-EXTPULSE-SHORT-NOLATCH set: %d sub-period pulses driven", self.short_runs
        )
        cocotb.log.info(
            "LIFECYCLE CHK-EXTPULSE-SHORT-NOLATCH observed: tb_cpu_interrupts[0] each rise"
        )
        cocotb.log.info("LIFECYCLE CHK-EXTPULSE-SHORT-NOLATCH cleared: pin back at 0")
        cocotb.log.info(
            "LIFECYCLE CHK-EXTPULSE-SHORT-NOLATCH checked_cleared: vector 0x%x for %d rises",
            base,
            CEILING_RISES,
        )
        self._log_chk(
            "CHK-EXTPULSE-SHORT-NOLATCH",
            f"{self.short_runs} short pulses ({short}) left raw bit 0 at 0 by the "
            f"{CEILING_RISES}-rise ceiling and vector 0x{base:x} for {CEILING_RISES} further rises",
        )
        self._log_chk("CHK-EXTPULSE-SHORT-SEEN-LOG", f"{self.short_runs} short pulses seen: {seen}")

        lat = await self._latency()
        assert self.latency_runs == LATENCY_REPEATS
        self._mark_step("S4")
        self._log_chk("CHK-EXTPULSE-LATENCY-LOG", f"{self.latency_runs} repeats: {lat}")

        self._nonvac_fence()
        self._log_timeout_paths()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _CHECK_STEP):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BASELINE<WIDE-PULSES<SHORT-PULSES<LATENCY-REPEATS; "
            "checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    def _log_timeout_paths(self) -> None:
        waits = "; ".join(
            f"{name} bound={bound} rises last[{last}]"
            for name, (bound, last) in self._waits.items()
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every expiry raises AssertionError with the last vector; "
            "ceiling %d clk_smc_i rises; %s",
            CEILING_RISES,
            waits,
        )
