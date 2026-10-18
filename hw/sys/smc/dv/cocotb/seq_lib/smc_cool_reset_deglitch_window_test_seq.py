# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ``rst_cool_ni`` de-glitch window and its collision with the FLR hold.

Spec sources: hw/sys/smc/doc/clk_rst.adoc (Power-Good and Cold Reset: the cool-reset pin passes
a 32-bit shift register, assertion needs 32 consecutive low reference-clock samples; the primary
reset is the AND of the stable cold reset, the de-glitched cool-reset pin and the FLR cool
reset; the FLR sequencer asserts cool reset and releases it after the hold countdown).

The pin is driven on reference-clock edges and the primary resets and the FLR cool-reset output
are sampled on every reference-clock edge. Measured offsets from a pin edge to a probe include
the synchroniser latency and are logged; only equalities between runs and orderings are compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_isolate_pin_utils import await_skip_mem_repair, drive_isolate_pin

SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
FLR_DELAY = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
SMC_BIT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")

# Consecutive low samples the pin de-glitcher needs.
DEGLITCH_SAMPLES = 32
GLITCH_LOW = DEGLITCH_SAMPLES - 1
CONTROL_LOW = 40
LONG_LOW = 100
SEGMENT_LOW = 20
GLITCH_AFTER_HIGH = 64
# FLR counters: the hold covers three 20-sample low segments, two single high samples and
# a release.
_DELAY = 0x20
_HOLD = 0xC0
# Reference-clock edges the counter values are given to cross into the reference domain.
_CDC_REF = 64
_ISO_BOUND = 64
_ASSERT_BOUND = 128
_RELEASE_BOUND = 512
_COOL_FALL_BOUND = _DELAY + 128
_COOL_RISE_BOUND = _HOLD + 128
# Bench bound on the release after the last reset source ends; not a specified latency.
_BENCH_RELEASE_BOUND = 256
_RECOVERY_SMC = 50_000

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
CHK_ORDER = (
    "CHK-COOLRST-GLITCH-REJECT",
    "CHK-COOLRST-REASSERT-RESTART",
    "CHK-COOLRST-RELEASE-NO-EXTENSION",
    "CHK-COOLRST-REASSERT-IN-HOLD",
    "CHK-COOLRST-RELEASE-REASSERT-HOLD",
)
FENCE_TERMS = {
    "S1": "COUNTERS_PROGRAMMED",
    "S2": "POSITIVE_CONTROL",
    "S3": "GLITCH_31",
    "S4": "REASSERT_IN_WINDOW",
    "S5": "RELEASE_100",
    "S6": "FLR_ALONE",
    "S7": "SUB32_SEGMENTS_IN_HOLD",
    "S8": "RELEASE_REASSERT_IN_HOLD",
}
OUTPUTS = ("smc", "ref")


class smc_cool_reset_deglitch_window_test_seq(SmcCsrSeq):
    """Pin de-glitch window below and at 32 samples, and pin segments inside the FLR hold."""

    def __init__(self, name: str = "smc_cool_reset_deglitch_window_test_seq") -> None:
        super().__init__(name)
        self.window_ok: bool = False
        self._tick_no: int = 0
        self._samples: dict[int, tuple[int, int, int]] = {}
        self._events: list[tuple[str, str, int]] = []
        self._waits: list[str] = []
        self._chk_text: dict[str, str] = {}

    def _int(self, pin) -> int:
        if not pin.value.is_resolvable:
            raise AssertionError(f"X/Z on pin: {pin.value}")
        return int(pin.value)

    async def _tick(self) -> int:
        """Advance one reference-clock edge and record the three probes sampled on it."""
        dut = cocotb.top
        await RisingEdge(dut.clk_ref_i)
        self._tick_no += 1
        self._samples[self._tick_no] = (
            self._int(dut.rst_primary_smc_clk_no) & 1,
            self._int(dut.rst_primary_ref_clk_no) & 1,
            self._int(dut.tb_rst_cool_from_flr) & 1,
        )
        return self._tick_no

    async def _ticks(self, count: int) -> None:
        for _ in range(count):
            await self._tick()

    def _pin(self, level: int) -> int:
        cocotb.top.rst_cool_ni.value = level
        return self._tick_no

    def _level(self, tick: int, probe: str) -> int:
        return self._samples[tick][("smc", "ref", "cool").index(probe)]

    def _first(self, probe: str, level: int, start: int, stop: int | None = None) -> int | None:
        last = self._tick_no if stop is None else stop
        for tick in range(start, last + 1):
            if self._level(tick, probe) == level:
                return tick
        return None

    def _last_state(self) -> str:
        smc, ref, cool = self._samples[self._tick_no]
        return f"tick={self._tick_no} smc={smc} ref={ref} cool={cool}"

    async def _until(self, label: str, bound: int, pred) -> int:
        for _ in range(bound):
            tick = await self._tick()
            if pred(tick):
                self._waits.append(f"{label}={bound}ref last={self._last_state()}")
                return tick
        raise AssertionError(f"{label}: no match in {bound} clk_ref_i edges; {self._last_state()}")

    def _step_done(self, step: str) -> None:
        self._events.append(("step", step, int(get_sim_time("ps"))))

    def _chk(self, cid: str, text: str) -> None:
        cocotb.log.info("%s: %s", cid, text)
        self._events.append(("chk", cid, int(get_sim_time("ps"))))

    def _assert_fence(self) -> None:
        steps = [e for e in self._events if e[0] == "step"]
        assert [e[1] for e in steps] == list(STEPS), f"step order {[e[1] for e in steps]}"
        stamps = [e[2] for e in steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        chks = [e for e in self._events if e[0] == "chk"]
        assert [c[1] for c in chks] == list(CHK_ORDER), f"checker order {[c[1] for c in chks]}"
        assert all(c[2] >= stamps[-1] for c in chks), "a checker printed before the last step"
        index = {e: i for i, e in enumerate(self._events)}
        assert all(index[c] > index[steps[-1]] for c in chks), "checker line before step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[e[1]] for e in steps),
            ", ".join(c[1] for c in chks),
            ",".join(str(s) for s in stamps),
        )

    async def _pin_run(self, label: str, segments: list[tuple[int, int]]) -> dict:
        """Drive the pin through ``segments`` then high, and wait for primary reset to release.

        Returns the driven edges and, per primary output, the assertion and release ticks.
        """
        run = {"label": label, "sets": []}
        for level, count in segments:
            run["sets"].append((level, self._pin(level)))
            await self._ticks(count)
        run["high"] = self._pin(1)
        run["first_low"] = run["sets"][0][1]
        return run

    async def _settle_pin(self, run: dict) -> None:
        start = run["first_low"]
        label = run["label"]
        both = lambda: all(self._first(o, 0, start) is not None for o in OUTPUTS)  # noqa: E731
        if not both():
            await self._until(f"{label}_ASSERT", _ASSERT_BOUND, lambda t: both())
        asserted = max(self._first(o, 0, start) for o in OUTPUTS)
        await self._until(
            f"{label}_RELEASE",
            _RELEASE_BOUND,
            lambda t: t > asserted and self._samples[t][0] == 1 and self._samples[t][1] == 1,
        )
        run["assert"] = {o: self._first(o, 0, start) for o in OUTPUTS}
        run["release"] = {o: self._first(o, 1, run["assert"][o]) for o in OUTPUTS}

    async def _flr(self, label: str) -> dict:
        """Pulse the FLR request and return its tick and the cool-reset fall tick."""
        dut = cocotb.top
        flr = {"label": label, "set": self._tick_no}
        dut.tb_cfg_flr_pf_active.value = 1
        flr["fall"] = await self._until(
            f"{label}_COOL_FALL", _COOL_FALL_BOUND, lambda t: self._samples[t][2] == 0
        )
        dut.tb_cfg_flr_pf_active.value = 0
        return flr

    async def _flr_finish(self, flr: dict) -> None:
        label = flr["label"]
        rose = self._first("cool", 1, flr["fall"])
        if rose is None:
            rose = await self._until(
                f"{label}_COOL_RISE", _COOL_RISE_BOUND, lambda t: self._samples[t][2] == 1
            )
        flr["rise"] = rose
        start = flr["set"]
        asserted = max(self._first(o, 0, start) for o in OUTPUTS)
        await self._until(
            f"{label}_RELEASE",
            _RELEASE_BOUND,
            lambda t: (
                t > max(asserted, rose) and self._samples[t][0] == 1 and self._samples[t][1] == 1
            ),
        )
        flr["assert"] = {o: self._first(o, 0, start) for o in OUTPUTS}
        flr["release"] = {o: self._first(o, 1, rose) for o in OUTPUTS}
        await self._await_warm(label)
        await self._clear_latch(label)

    async def _await_warm(self, label: str) -> None:
        dut = cocotb.top
        last = None
        for _ in range(_RECOVERY_SMC):
            await RisingEdge(dut.clk_smc_i)
            last = self._int(dut.tb_rst_warm_smc_clk_n) & 1
            if last == 1:
                self._waits.append(f"{label}_WARM={_RECOVERY_SMC}smc last={last}")
                return
        raise AssertionError(f"{label}: warm smc clk still {last} after {_RECOVERY_SMC} cycles")

    async def _clear_latch(self, label: str) -> None:
        await self.csr_write(f"{label}_SMC_REG_CLR", SMC_REG, 0)
        last = SMC_BIT
        for _ in range(_ISO_BOUND):
            last = await self.csr_read(f"{label}_SMC_REG_RB", SMC_REG)
            if not last & SMC_BIT:
                self._waits.append(f"{label}_LATCH_CLR={_ISO_BOUND}polls last=0x{last:x}")
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(f"{label}: SMC_REG=0x{last:x} still set after {_ISO_BOUND} polls")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_cfg_flr_pf_active"), "tb_cfg_flr_pf_active missing"
        dut.tb_cfg_flr_pf_active.value = 0
        dut.rst_cool_ni.value = 1
        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "isolate pin low, no FLR")

        await self.csr_write("FLR_DELAY", FLR_DELAY, _DELAY)
        await self.csr_read("FLR_DELAY_RB", FLR_DELAY, expected=_DELAY)
        await self.csr_write("FLR_HOLD", FLR_HOLD, _HOLD)
        await self.csr_read("FLR_HOLD_RB", FLR_HOLD, expected=_HOLD)
        await self._tick()
        assert self._samples[self._tick_no] == (1, 1, 1), (
            f"resets not released before the first pattern: {self._last_state()}"
        )
        await self._ticks(_CDC_REF)
        self._waits.append(f"cdc_allowance={_CDC_REF}ref")
        self._step_done("S1")

        # S2: positive control.
        control = await self._pin_run("S2", [(0, CONTROL_LOW)])
        await self._settle_pin(control)
        self._step_done("S2")

        # S3: 31 low samples, then 64 reference-clock cycles with the pin high.
        glitch_low = self._pin(0)
        await self._ticks(GLITCH_LOW)
        glitch_high = self._pin(1)
        await self._ticks(GLITCH_AFTER_HIGH)
        glitch_end = self._tick_no
        self._step_done("S3")

        # S4: low 20, high 1, low 40.
        reassert = await self._pin_run("S4", [(0, SEGMENT_LOW), (1, 1), (0, CONTROL_LOW)])
        await self._settle_pin(reassert)
        self._step_done("S4")

        # S5: 100 low samples.
        long_low = await self._pin_run("S5", [(0, LONG_LOW)])
        await self._settle_pin(long_low)
        self._step_done("S5")

        # S6: FLR alone.
        base = await self._flr("S6")
        await self._flr_finish(base)
        self._step_done("S6")

        # S7: three sub-32 low segments inside the hold.
        seg = [(0, SEGMENT_LOW), (1, 1), (0, SEGMENT_LOW), (1, 1), (0, SEGMENT_LOW)]
        hold7 = await self._flr("S7")
        pins7 = await self._pin_run("S7", seg)
        await self._flr_finish(hold7)
        self._step_done("S7")

        # S8: release and re-assert inside the hold.
        hold8 = await self._flr("S8")
        pins8 = await self._pin_run("S8", [(0, CONTROL_LOW), (1, 10), (0, CONTROL_LOW)])
        await self._flr_finish(hold8)
        self._step_done("S8")
        await ClockCycles(dut.clk_ref_i, 2)

        # CHK-COOLRST-GLITCH-REJECT
        control_off = {o: control["assert"][o] - control["first_low"] for o in OUTPUTS}
        released = [
            t
            for t in range(glitch_low, glitch_end + 1)
            if self._samples[t][0] != 1 or self._samples[t][1] != 1
        ]
        assert not released, (
            f"primary reset asserted at ticks {released[:8]} after a {GLITCH_LOW}-cycle low "
            f"(pin low at tick {glitch_low}, high at {glitch_high})"
        )
        self._chk(
            "CHK-COOLRST-GLITCH-REJECT",
            f"positive control: a {CONTROL_LOW}-cycle low asserted primary reset "
            f"smc={control_off['smc']} ref={control_off['ref']} cycles after the first low; a "
            f"{GLITCH_LOW}-cycle low left rst_primary_smc_clk_no and rst_primary_ref_clk_no "
            f"released at all {glitch_end - glitch_low + 1} samples from the first low until "
            f"{GLITCH_AFTER_HIGH} cycles after the pin returned high",
        )

        # CHK-COOLRST-REASSERT-RESTART
        re_low = reassert["sets"][2][1]
        re_off = {o: reassert["assert"][o] - re_low for o in OUTPUTS}
        for o in OUTPUTS:
            assert re_off[o] >= DEGLITCH_SAMPLES, (
                f"{o}: primary reset asserted {re_off[o]} cycles after the re-assert low, "
                f"before {DEGLITCH_SAMPLES} consecutive lows"
            )
            assert re_off[o] == control_off[o], (
                f"{o}: assertion {re_off[o]} cycles after the re-assert low, "
                f"{control_off[o]} after the first low of the control"
            )
        self._chk(
            "CHK-COOLRST-REASSERT-RESTART",
            f"low {SEGMENT_LOW}, high 1, low {CONTROL_LOW}: primary reset asserted "
            f"smc={re_off['smc']} ref={re_off['ref']} cycles after the re-assert low, equal to "
            f"the control's smc={control_off['smc']} ref={control_off['ref']} cycles after its "
            f"first low, and not before {DEGLITCH_SAMPLES} consecutive lows",
        )

        # CHK-COOLRST-RELEASE-NO-EXTENSION
        ctl_rel = {o: control["release"][o] - control["high"] for o in OUTPUTS}
        long_rel = {o: long_low["release"][o] - long_low["high"] for o in OUTPUTS}
        for o in OUTPUTS:
            assert ctl_rel[o] == long_rel[o], (
                f"{o}: release {ctl_rel[o]} cycles after the first high for a "
                f"{CONTROL_LOW}-cycle low, {long_rel[o]} for a {LONG_LOW}-cycle low"
            )
        self._chk(
            "CHK-COOLRST-RELEASE-NO-EXTENSION",
            f"measured release offsets from the first high sample: {CONTROL_LOW}-cycle low "
            f"smc={ctl_rel['smc']} ref={ctl_rel['ref']}, {LONG_LOW}-cycle low "
            f"smc={long_rel['smc']} ref={long_rel['ref']}, equal",
        )

        # CHK-COOLRST-REASSERT-IN-HOLD
        base_rel = {o: base["release"][o] - base["rise"] for o in OUTPUTS}
        hold_rel = {o: hold7["release"][o] - hold7["rise"] for o in OUTPUTS}
        first7 = min(hold7["assert"].values())
        for o in OUTPUTS:
            bad = [t for t in range(first7, hold7["rise"]) if self._level(t, o) != 0]
            assert not bad, (
                f"{o}: released samples {bad[:8]} inside the hold {first7}..{hold7['rise']}"
            )
            assert hold_rel[o] == base_rel[o], (
                f"{o}: release {hold_rel[o]} cycles after the cool rise with the pin segments, "
                f"{base_rel[o]} for FLR alone"
            )
            assert hold_rel[o] <= _BENCH_RELEASE_BOUND, f"{o}: release {hold_rel[o]} past bound"
        self._chk(
            "CHK-COOLRST-REASSERT-IN-HOLD",
            f"three {SEGMENT_LOW}-cycle low segments in the hold (pin edges "
            f"{[t for _, t in pins7['sets']]}): primary reset asserted at all "
            f"{hold7['rise'] - first7} samples from tick {first7} to the cool rise at "
            f"{hold7['rise']}; release smc={hold_rel['smc']} ref={hold_rel['ref']} cycles after "
            f"the cool rise, FLR alone smc={base_rel['smc']} ref={base_rel['ref']} (delta 0), "
            f"inside the bench bound of {_BENCH_RELEASE_BOUND} ref cycles",
        )

        # CHK-COOLRST-RELEASE-REASSERT-HOLD
        last_high = pins8["high"]
        end8 = {o: max(hold8["rise"], last_high + ctl_rel[o]) for o in OUTPUTS}
        first8 = min(hold8["assert"].values())
        counts = {}
        for o in OUTPUTS:
            window = range(first8, end8[o])
            counts[o] = sum(1 for t in window if self._level(t, o) != 0)
            assert counts[o] == 0, f"{o}: {counts[o]} released samples before both sources ended"
            after = hold8["release"][o] - end8[o]
            assert 0 <= after <= _BENCH_RELEASE_BOUND, (
                f"{o}: release {after} cycles after both sources ended at {end8[o]}"
            )
        self._chk(
            "CHK-COOLRST-RELEASE-REASSERT-HOLD",
            f"pin low {CONTROL_LOW}, high 10, low {CONTROL_LOW} inside the hold: released "
            f"samples smc={counts['smc']} ref={counts['ref']} from tick {first8} until the later "
            f"source ended (cool rise {hold8['rise']}, pin release {last_high}+offset), release "
            f"at smc={hold8['release']['smc']} ref={hold8['release']['ref']}, "
            f"{hold8['release']['smc'] - end8['smc']} and {hold8['release']['ref'] - end8['ref']} "
            f"cycles after both ended, inside the bench bound of {_BENCH_RELEASE_BOUND}",
        )

        drive_isolate_pin(dut, None)
        await self.csr_write("FLR_HOLD_CLR", FLR_HOLD, 0)
        await self.csr_read("FLR_HOLD_CLR_RB", FLR_HOLD, expected=0)
        cocotb.log.info(
            "measured: S6 FLR set=%d fall=%d rise=%d assert=%s release=%s; S7 pin edges %s; "
            "S8 pin edges %s",
            base["set"],
            base["fall"],
            base["rise"],
            base["assert"],
            base["release"],
            pins7["sets"],
            pins8["sets"],
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
        self.window_ok = True
