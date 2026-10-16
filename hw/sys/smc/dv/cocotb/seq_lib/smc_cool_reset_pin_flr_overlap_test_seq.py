# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ``rst_cool_ni`` pin overlapping the FLR cool-reset sequence.

Spec sources: hw/sys/smc/doc/clk_rst.adoc (Power-Good and Cold Reset: the cool-reset pin passes
a 32-bit shift register; the primary reset is the AND of the stable cold reset, the de-glitched
cool-reset pin and the FLR cool reset; the FLR sequencer waits the pre-reset count, asserts cool
reset for the hold count and releases it), hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl
(ISOLATE_REQ_FLR_COUNTER_VALUE, ISOLATE_REQ_FLR_RESET_COUNTER_VALUE).

The pin is driven and every probe sampled on reference-clock edges. Absolute offsets include
the synchroniser latencies and are logged as measured; only deltas between runs with the same or
differing programming, equalities and orderings are compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_addr
from .smc_cool_reset_deglitch_window_test_seq import (
    _ASSERT_BOUND,
    _ISO_BOUND,
    _RECOVERY_SMC,
    _RELEASE_BOUND,
    DEGLITCH_SAMPLES,
    OUTPUTS,
    smc_cool_reset_deglitch_window_test_seq,
)
from .smc_isolate_pin_utils import await_skip_mem_repair, drive_isolate_pin

FLR_DELAY = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")

PIN_ALONE_LOW = 48
PIN_PAST_HOLD = 56
PIN_IN_HOLD_LOW = 40
PIN_PRE_COUNT_OFFSET = 8
PIN_AFTER_FALL = 4
# Two programmed (pre-reset count, hold count) pairs that differ in both counts.
_P1, _H1 = 0x20, 0x60
_P2, _H2 = 0x50, 0xA0
# Reference-clock edges the counter values are given to cross into the reference domain.
_CDC_REF = 64
_COOL_FALL_BOUND = _P2 + 128
_COOL_RISE_BOUND = _H2 + 128
# Bench bound on the release after the last reset source ends; not a specified latency.
_BENCH_RELEASE_BOUND = 256

STEPS = ("S1", "S2", "S3", "S4", "S5")
CHK_ORDER = (
    "CHK-COOLRST-FLR-PRE-COUNT",
    "CHK-COOLRST-FLR-HOLD-COUNT",
    "CHK-COOLRST-BP-LEVEL",
    "CHK-COOLRST-FLR-ALONE-PRIMARY",
    "CHK-COOLRST-PIN-ALONE-PRIMARY",
    "CHK-COOLRST-COLD-STABLE",
    "CHK-COOLRST-COLLISION-PRE",
    "CHK-COOLRST-COLLISION-HOLD",
    "CHK-COOLRST-PIN-EARLY-RELEASE",
    "CHK-COOLRST-HOLD-INVARIANT",
)
FENCE_TERMS = {
    "S1": "FLR_ALONE_TWICE",
    "S2": "PIN_ALONE",
    "S3": "PIN_IN_PRE_COUNT",
    "S4": "PIN_OUTLASTS_HOLD",
    "S5": "PIN_RELEASED_EARLY",
}
COLD_PROBES = ("rst_cold_n_o", "rst_cold_stable_ref_clk_no")


class smc_cool_reset_pin_flr_overlap_test_seq(smc_cool_reset_deglitch_window_test_seq):
    """Pin alone, FLR alone with two count pairs, and the pin overlapping the FLR sequence."""

    def __init__(self, name: str = "smc_cool_reset_pin_flr_overlap_test_seq") -> None:
        super().__init__(name)
        self.overlap_ok: bool = False
        self._cold: dict[int, tuple[int, int]] = {}

    async def _tick(self) -> int:
        tick = await super()._tick()
        dut = cocotb.top
        self._cold[tick] = tuple(self._int(getattr(dut, p)) & 1 for p in COLD_PROBES)
        return tick

    def _last_state(self) -> str:
        cold = self._cold[self._tick_no]
        return f"{super()._last_state()} cold_n={cold[0]} cold_stable={cold[1]}"

    def _assert_fence(self) -> None:
        steps = [e for e in self._events if e[0] == "step"]
        assert [e[1] for e in steps] == list(STEPS), f"step order {[e[1] for e in steps]}"
        stamps = [e[2] for e in steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        chks = [e for e in self._events if e[0] == "chk"]
        assert [c[1] for c in chks] == list(CHK_ORDER), f"checker order {[c[1] for c in chks]}"
        index = {e: i for i, e in enumerate(self._events)}
        assert all(index[c] > index[steps[-1]] for c in chks), "checker line before step stamp"
        assert all(c[2] >= stamps[-1] for c in chks), "a checker printed before the last step"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[e[1]] for e in steps),
            ", ".join(c[1] for c in chks),
            ",".join(str(s) for s in stamps),
        )

    async def _program(self, label: str, delay: int, hold: int) -> None:
        await self.csr_write(f"{label}_DELAY", FLR_DELAY, delay)
        await self.csr_read(f"{label}_DELAY_RB", FLR_DELAY, expected=delay)
        await self.csr_write(f"{label}_HOLD", FLR_HOLD, hold)
        await self.csr_read(f"{label}_HOLD_RB", FLR_HOLD, expected=hold)
        await self._ticks(_CDC_REF)
        self._waits.append(f"{label}_cdc_allowance={_CDC_REF}ref")

    def _flr_raise(self, label: str) -> dict:
        cocotb.top.tb_cfg_flr_pf_active.value = 1
        return {"label": label, "set": self._tick_no}

    async def _flr_fall(self, flr: dict) -> None:
        label = flr["label"]
        flr["fall"] = await self._until(
            f"{label}_COOL_FALL", _COOL_FALL_BOUND, lambda t: self._samples[t][2] == 0
        )
        cocotb.top.tb_cfg_flr_pf_active.value = 0

    async def _flr_rise(self, flr: dict) -> None:
        label = flr["label"]
        flr["rise"] = await self._until(
            f"{label}_COOL_RISE", _COOL_RISE_BOUND, lambda t: self._samples[t][2] == 1
        )

    def _cold_released(self, start: int, stop: int) -> int:
        """Count the samples in [start, stop] at which both cold outputs read deasserted."""
        window = range(start, stop + 1)
        bad = [t for t in window if self._cold[t] != (1, 1)]
        assert not bad, (
            f"cold reset asserted at ticks {bad[:8]} of {start}..{stop}: "
            f"{[self._cold[t] for t in bad[:4]]}"
        )
        return len(window)

    def _require_primary_asserted(self, flr: dict) -> None:
        for o in OUTPUTS:
            assert self._first(o, 0, flr["set"]) is not None, (
                f"{flr['label']}: {o} never asserted from the FLR edge {flr['set']} to the "
                f"cool rise {flr['rise']}; {self._last_state()}"
            )

    def _flr_summary(self, run: dict) -> str:
        return (
            f"set={run['set']} fall={run['fall']} rise={run['rise']} "
            f"low={run['rise'] - run['fall']}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_cfg_flr_pf_active"), "tb_cfg_flr_pf_active missing"
        dut.tb_cfg_flr_pf_active.value = 0
        dut.rst_cool_ni.value = 1
        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "isolate pin low, no FLR")

        # S1: FLR alone with two count pairs.
        await self._program("PAIR1", _P1, _H1)
        await self._tick()
        assert self._samples[self._tick_no] == (1, 1, 1), (
            f"resets not released before the first run: {self._last_state()}"
        )
        flr1 = self._flr_raise("S1A")
        await self._flr_fall(flr1)
        await self._flr_rise(flr1)
        self._require_primary_asserted(flr1)
        await self._flr_finish(flr1)
        await self._program("PAIR2", _P2, _H2)
        flr2 = self._flr_raise("S1B")
        await self._flr_fall(flr2)
        await self._flr_rise(flr2)
        self._require_primary_asserted(flr2)
        await self._flr_finish(flr2)
        self._step_done("S1")

        # S2: pin alone.
        pin2 = await self._pin_run("S2", [(0, PIN_ALONE_LOW)])
        await self._settle_pin(pin2)
        self._step_done("S2")

        # S3: pin low inside the pre-reset count, held past its end.
        flr3 = self._flr_raise("S3")
        await self._ticks(PIN_PRE_COUNT_OFFSET)
        pin3_low = self._pin(0)
        await self._flr_fall(flr3)
        await self._ticks(PIN_AFTER_FALL)
        pin3_high = self._pin(1)
        await self._flr_rise(flr3)
        await self._flr_finish(flr3)
        self._step_done("S3")

        # S4: pin low inside the hold, held past its end.
        flr4 = self._flr_raise("S4")
        await self._flr_fall(flr4)
        await self._ticks(PIN_AFTER_FALL)
        pin4_low = self._pin(0)
        await self._flr_rise(flr4)
        await self._ticks(PIN_PAST_HOLD)
        pin4_high = self._pin(1)
        await self._flr_finish(flr4)
        self._step_done("S4")

        # S5: pin low inside the hold, released well before it ends.
        flr5 = self._flr_raise("S5")
        await self._flr_fall(flr5)
        await self._ticks(PIN_AFTER_FALL)
        pin5_low = self._pin(0)
        await self._ticks(PIN_IN_HOLD_LOW)
        pin5_high = self._pin(1)
        await self._flr_rise(flr5)
        await self._flr_finish(flr5)
        self._step_done("S5")
        await ClockCycles(dut.clk_ref_i, 2)

        # CHK-COOLRST-FLR-PRE-COUNT
        off1 = flr1["fall"] - flr1["set"]
        off2 = flr2["fall"] - flr2["set"]
        assert _P2 != _P1
        assert off2 - off1 == _P2 - _P1, (
            f"fall offset delta {off2 - off1}, programmed pre-reset count delta {_P2 - _P1} "
            f"(offsets {off1}, {off2})"
        )
        self._chk(
            "CHK-COOLRST-FLR-PRE-COUNT",
            f"counters read back as written (0x{_P1:x}/0x{_H1:x} and 0x{_P2:x}/0x{_H2:x}); "
            f"measured fall offset from the FLR edge {off1} for pre-reset count 0x{_P1:x} and "
            f"{off2} for 0x{_P2:x}; delta {off2 - off1} == {_P2 - _P1}",
        )

        # CHK-COOLRST-FLR-HOLD-COUNT
        low1 = flr1["rise"] - flr1["fall"]
        low2 = flr2["rise"] - flr2["fall"]
        assert _H2 != _H1
        assert low2 - low1 == _H2 - _H1, (
            f"low duration delta {low2 - low1}, programmed hold count delta {_H2 - _H1} "
            f"(durations {low1}, {low2})"
        )
        self._chk(
            "CHK-COOLRST-FLR-HOLD-COUNT",
            f"measured cool-reset low duration {low1} for hold count 0x{_H1:x} and {low2} for "
            f"0x{_H2:x}; delta {low2 - low1} == {_H2 - _H1}; released after the hold at "
            f"ticks {flr1['rise']} and {flr2['rise']}",
        )

        # CHK-COOLRST-BP-LEVEL
        runs = (flr1, flr2, flr3, flr4, flr5)
        in_low = set()
        for run in runs:
            in_low.update(range(run["fall"], run["rise"]))
        wrong = [t for t in self._samples if (self._samples[t][2] == 0) != (t in in_low)]
        assert not wrong, f"rst_cool_no level disagrees with the FLR hold at ticks {wrong[:8]}"
        self._chk(
            "CHK-COOLRST-BP-LEVEL",
            f"rst_cool_no low at all {len(in_low)} samples inside the {len(runs)} FLR holds "
            f"{[(r['fall'], r['rise']) for r in runs]} and high at the other "
            f"{len(self._samples) - len(in_low)} samples, including the pin-alone window "
            f"{pin2['first_low']}..{pin2['release']['ref']}",
        )

        # CHK-COOLRST-FLR-ALONE-PRIMARY
        alone = {}
        for run in (flr1, flr2):
            for o in OUTPUTS:
                a, r = run["assert"][o], run["release"][o]
                assert run["set"] < a <= run["fall"], (
                    f"{o}: asserted at {a}, outside the FLR edge {run['set']} to the cool fall "
                    f"{run['fall']}"
                )
                bad = [t for t in range(a, run["rise"]) if self._level(t, o) != 0]
                assert not bad, f"{o}: released samples {bad[:8]} inside the hold"
                assert self._first(o, 1, a) == r, (
                    f"{o}: first release after the assertion at {self._first(o, 1, a)}, "
                    f"release after the cool rise at {r}"
                )
            alone[run["label"]] = {o: run["release"][o] - run["rise"] for o in OUTPUTS}
        self._chk(
            "CHK-COOLRST-FLR-ALONE-PRIMARY",
            f"FLR alone (0x{_P2:x}/0x{_H2:x}): primary reset asserted smc={flr2['assert']['smc']} "
            f"ref={flr2['assert']['ref']} after the FLR edge at {flr2['set']} and released "
            f"smc={flr2['release']['smc']} ref={flr2['release']['ref']}, at or after the cool "
            f"rise at "
            f"{flr2['rise']} (release offset to the rise smc={alone['S1B']['smc']} "
            f"ref={alone['S1B']['ref']} kept as baseline; first run smc={alone['S1A']['smc']} "
            f"ref={alone['S1A']['ref']})",
        )

        # CHK-COOLRST-PIN-ALONE-PRIMARY
        pin_off = {o: pin2["assert"][o] - pin2["first_low"] for o in OUTPUTS}
        pin_rel = {o: pin2["release"][o] - pin2["high"] for o in OUTPUTS}
        for o in OUTPUTS:
            assert pin_off[o] >= DEGLITCH_SAMPLES, (
                f"{o}: asserted {pin_off[o]} cycles after the first low, before "
                f"{DEGLITCH_SAMPLES} consecutive lows"
            )
            assert pin2["release"][o] > pin2["high"], f"{o}: released before the pin"
        window = range(pin2["first_low"], pin2["release"]["ref"] + 1)
        cool_low = [t for t in window if self._samples[t][2] == 0]
        assert not cool_low, f"rst_cool_no low at ticks {cool_low[:8]} of the pin-alone window"
        high_samples = len(window)
        self._chk(
            "CHK-COOLRST-PIN-ALONE-PRIMARY",
            f"after {PIN_ALONE_LOW} low samples from tick {pin2['first_low']} primary reset "
            f"asserted measured smc={pin_off['smc']} ref={pin_off['ref']} cycles after the first "
            f"low and released smc={pin_rel['smc']} ref={pin_rel['ref']} cycles after the first "
            f"high; rst_cool_no high at all {high_samples} samples of the window",
        )

        # CHK-COOLRST-COLD-STABLE
        windows = {
            "S2": (pin2["first_low"], max(pin2["release"].values())),
            "S3": (flr3["set"] + 1, max(flr3["release"].values())),
            "S4": (flr4["set"] + 1, max(flr4["release"].values())),
        }
        counts = {}
        for step, (start, stop) in windows.items():
            counts[step] = self._cold_released(start, stop)
        control = {
            o: sum(1 for t in range(*windows["S2"]) if self._level(t, o) == 0) for o in OUTPUTS
        }
        assert all(control[o] > 0 for o in OUTPUTS), f"no asserted primary sample in S2: {control}"
        self._chk(
            "CHK-COOLRST-COLD-STABLE",
            f"rst_cold_n_o and rst_cold_stable_ref_clk_no deasserted at all {counts['S2']}, "
            f"{counts['S3']} and {counts['S4']} samples of the S2, S3 and S4 windows; positive "
            f"control: primary reset asserted at smc={control['smc']} ref={control['ref']} "
            f"samples of the S2 window",
        )

        # CHK-COOLRST-COLLISION-PRE
        pre_off = flr3["fall"] - flr3["set"]
        assert pre_off == off2, f"fall offset {pre_off} with the pin, {off2} FLR alone"
        # The pin ends PIN_AFTER_FALL cycles after the cool fall, so the cool rise is the later
        # source and the FLR-alone release offset from the rise is the exact expectation.
        assert pin3_high < flr3["rise"], (
            f"pin released at {pin3_high} after the rise {flr3['rise']}"
        )
        pre_rel = {o: flr3["release"][o] - flr3["rise"] for o in OUTPUTS}
        for o in OUTPUTS:
            assert flr3["assert"][o] < flr3["fall"], (
                f"{o}: primary asserted at {flr3['assert'][o]}, not before the cool fall "
                f"{flr3['fall']}"
            )
            assert pre_rel[o] == alone["S1B"][o], (
                f"{o}: release {pre_rel[o]} cycles after the cool rise, {alone['S1B'][o]} FLR alone"
            )
        self._chk(
            "CHK-COOLRST-COLLISION-PRE",
            f"pin low at tick {pin3_low} ({pin3_low - flr3['set']} after the FLR edge) to "
            f"{pin3_high}: primary reset asserted smc={flr3['assert']['smc']} "
            f"ref={flr3['assert']['ref']} before the cool fall at {flr3['fall']}; fall offset "
            f"{pre_off} equals the FLR-alone {off2} (delta 0); released smc={pre_rel['smc']} "
            f"ref={pre_rel['ref']} cycles after the cool rise, the later source, equal to the "
            f"FLR-alone smc={alone['S1B']['smc']} ref={alone['S1B']['ref']} (delta 0)",
        )

        # CHK-COOLRST-COLLISION-HOLD
        hold_rel = {o: flr4["release"][o] - pin4_high for o in OUTPUTS}
        for o in OUTPUTS:
            first = flr4["assert"][o]
            bad = [t for t in range(first, pin4_high) if self._level(t, o) != 0]
            assert not bad, f"{o}: released samples {bad[:8]} before the pin release {pin4_high}"
            assert flr4["rise"] < flr4["release"][o], f"{o}: released before the cool rise"
            assert hold_rel[o] == pin_rel[o], (
                f"{o}: release {hold_rel[o]} cycles after the pin release, {pin_rel[o]} pin alone"
            )
            assert hold_rel[o] <= _BENCH_RELEASE_BOUND, f"{o}: release {hold_rel[o]} past bound"
        self._chk(
            "CHK-COOLRST-COLLISION-HOLD",
            f"pin low from {pin4_low} to {pin4_high}, {pin4_high - flr4['rise']} cycles past the "
            f"cool rise at {flr4['rise']}: primary reset asserted at every sample from "
            f"smc={flr4['assert']['smc']} ref={flr4['assert']['ref']} to the pin release and "
            f"released smc={hold_rel['smc']} ref={hold_rel['ref']} cycles after it, equal to the "
            f"pin-alone smc={pin_rel['smc']} ref={pin_rel['ref']} (delta 0)",
        )

        # CHK-COOLRST-PIN-EARLY-RELEASE
        early_rel = {o: flr5["release"][o] - flr5["rise"] for o in OUTPUTS}
        for o in OUTPUTS:
            bad = [t for t in range(flr5["assert"][o], flr5["rise"]) if self._level(t, o) != 0]
            assert not bad, f"{o}: released samples {bad[:8]} before the cool rise"
            assert early_rel[o] == alone["S1B"][o], (
                f"{o}: release {early_rel[o]} cycles after the cool rise, "
                f"{alone['S1B'][o]} FLR alone"
            )
        assert pin5_high + 16 <= flr5["rise"], "pin released less than 16 cycles before the end"
        self._chk(
            "CHK-COOLRST-PIN-EARLY-RELEASE",
            f"pin low from {pin5_low} to {pin5_high}, {flr5['rise'] - pin5_high} cycles before the "
            f"cool rise at {flr5['rise']}: primary reset asserted at every sample until the rise "
            f"and released smc={early_rel['smc']} ref={early_rel['ref']} cycles after it, equal "
            f"to the FLR-alone smc={alone['S1B']['smc']} ref={alone['S1B']['ref']} (delta 0)",
        )

        # CHK-COOLRST-HOLD-INVARIANT
        lows = {
            "FLR alone": low2,
            "pin in pre-reset count": flr3["rise"] - flr3["fall"],
            "pin outlasting hold": flr4["rise"] - flr4["fall"],
            "pin released early": flr5["rise"] - flr5["fall"],
        }
        assert all(v == low2 for v in lows.values()), f"cool-reset low durations {lows}"
        self._chk(
            "CHK-COOLRST-HOLD-INVARIANT",
            "rst_cool_no low duration in reference-clock cycles "
            + ", ".join(f"{k}={v}" for k, v in lows.items())
            + "; all equal",
        )

        drive_isolate_pin(dut, None)
        await self.csr_write("FLR_HOLD_CLR", FLR_HOLD, 0)
        await self.csr_read("FLR_HOLD_CLR_RB", FLR_HOLD, expected=0)
        cocotb.log.info(
            "measured: S1A %s; S1B %s; S3 %s; S4 %s; S5 %s; S2 pin edges %s",
            self._flr_summary(flr1),
            self._flr_summary(flr2),
            self._flr_summary(flr3),
            self._flr_summary(flr4),
            self._flr_summary(flr5),
            pin2["sets"],
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; assert_wait=%d release_wait=%d "
            "cool_fall=%d cool_rise=%d warm=%d smc latch_clear=%d polls enforced-by=this sequence "
            "fail-on-expiry=AssertionError with the last sampled levels",
            len(self._waits),
            " ".join(self._waits),
            _ASSERT_BOUND,
            _RELEASE_BOUND,
            _COOL_FALL_BOUND,
            _COOL_RISE_BOUND,
            _RECOVERY_SMC,
            _ISO_BOUND,
        )
        self._assert_fence()
        self.overlap_ok = True
