# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_secure_tm_real_sense_window_test.

Contract SMU_SEP_006, anchor smu_secure_tm_real_sense_window_test.
Spec: hw/sys/sep/doc/test_mode.adoc (TEST_EN latched when fuse sensing is done, cleared only by
chip reset), hw/sys/sep/doc/lifecycle_controller.adoc, doc/integrator/src/smu.adoc.
Port rows: hw/sys/smu/doc/port_table.adoc; response valid bit: hw/ip/efuse/doc/interface.adoc.

secure_tm_req_i is sampled into secure_tm_o when SEP fuse sensing completes and is cleared only
by a reset. Leg 1 latches a 1 from a strap held at 1. Leg 2 asserts a cold reset with the strap
still 1, requires secure_tm_o to read 0, drops the strap, and releases the reset. Over the whole
real sense that follows secure_tm_o is sampled every clk_smu_i and stays 0, including while the
strap pulses to 1 between response strobes 100 and 180. It stays 0 after sep_fuse_sense_done_o
rises with the strap at 0.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

CLEAR = "SEP_SECURE_TM_CLEAR_REAL"
NO_FOLLOW = "SEP_SECURE_TM_NO_EARLY_FOLLOW"
RESET_HOLD_REF_CYCLES = 64
RESET_LOW_BOUND = 20000
DONE_BOUND = 200000
STROBE_BOUND = 200000
STEP_CYCLES = 64
LEG1_SAMPLE_DELAY = 64
TAP_RESET_TCK = 16
MIN_WINDOW_SAMPLES = 1000
STROBE_RAISE = 100
STROBE_LOWER = 180
AFTER_EDGE_SAMPLES = 512
HOLD_SAMPLE_BOUND = 20000
RESET_DONE_BOUND = 200000


class smu_secure_tm_real_sense_window_test_seq:
    """secure_tm_o over a cold reset and the real fuse sense that follows it."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.probe = test.fuse_probe
        self.stamps: dict[str, float] = {}
        self.sites: dict[str, dict] = {}
        self._hold_over = False

    def _site(self, label: str, bound: int, unit: str) -> dict:
        rec = {"bound": bound, "unit": unit, "used": 0, "last": "none", "hit": False}
        self.sites[label] = rec
        return rec

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    def _step(self, step: str, text: str) -> None:
        self.stamps[step] = get_sim_time("ns")
        self.log.info("STEP %s @%.1f ns: %s", step, self.stamps[step], text)

    def _strobes(self) -> int:
        return self.probe.resp_words["sep_efuse_shim"]

    @staticmethod
    def _expired(rec: dict) -> bool:
        return (not rec["hit"]) or rec["used"] > rec["bound"]

    def _timeout(self, label: str) -> None:
        rec = self.sites[label]
        self.log.info("TIMEOUT-PATH %s: bound=%d EXPIRED last=%s", label, rec["bound"], rec["last"])
        raise AssertionError(f"TIMEOUT {label} bound={rec['bound']} {rec['unit']} {rec['last']}")

    async def _wait_reset_done(self) -> None:
        rec = self._site("reset_done", RESET_DONE_BOUND, "clk_smu_i")
        for cycle in range(RESET_DONE_BOUND):
            rec["used"] = cycle
            rec["last"] = f"reset_done_set={self.cfg.reset_done.is_set()}"
            if self.cfg.reset_done.is_set():
                rec["hit"] = True
                return
            await RisingEdge(self.dut.clk_smu_i)
        self._timeout("reset_done")

    async def _wait_done_rise(self, label: str, rises_before: int) -> None:
        rec = self._site(label, DONE_BOUND, "clk_smu_i")
        for polls in range(DONE_BOUND // STEP_CYCLES):
            rec["used"] = polls * STEP_CYCLES
            rec["last"] = (
                f"done_rises={len(self.probe.rises['sep_fuse_sense_done_o'])} "
                f"resp_words={self._strobes()}"
            )
            if len(self.probe.rises["sep_fuse_sense_done_o"]) > rises_before:
                rec["hit"] = True
                return
            await ClockCycles(self.dut.clk_smu_i, STEP_CYCLES)
        rec["used"] = DONE_BOUND
        self._timeout(label)

    async def _hold_sampler(self) -> tuple[int, int]:
        """Sample secure_tm_o on every clk_smu_i edge until the hold ends."""
        rec = self.sites["reset_hold_samples"]
        samples = highs = 0
        for _ in range(HOLD_SAMPLE_BOUND):
            await RisingEdge(self.dut.clk_smu_i)
            if self._hold_over:
                rec["hit"] = True
                rec["last"] = f"samples={samples} highs={highs}"
                return samples, highs
            samples += 1
            highs += self._bit("tb_secure_tm")
            rec["used"] = samples
            rec["last"] = f"samples={samples} highs={highs}"
        self._timeout("reset_hold_samples")

    async def _tck_counter(self) -> None:
        rec = self.sites["tap_reset"]
        for count in range(TAP_RESET_TCK):
            await RisingEdge(self.dut.jtag_tck)
            rec["used"] = count + 1
            rec["last"] = f"tck_pulses={count + 1}"
        rec["hit"] = True

    async def _window(self, rises_before: int, base: int) -> dict:
        """Sample secure_tm_o on every clk_smu_i edge from the release until done rises."""
        dut = self.dut
        probe = self.probe
        done_rec = self.sites["done_rise_2"]
        raise_rec = self.sites["strobe_100"]
        lower_rec = self.sites["strobe_180"]
        samples = highs = pulse_samples = pulse_highs = 0
        strap_high = False
        raised = lowered = False
        for cycle in range(DONE_BOUND):
            await RisingEdge(dut.clk_smu_i)
            strobes = self._strobes() - base
            done_rec["used"] = cycle + 1
            done_rec["last"] = f"strobes={strobes} samples={samples}"
            if (
                self._bit("sep_fuse_sense_done_o")
                and len(probe.rises["sep_fuse_sense_done_o"]) > rises_before
            ):
                done_rec["hit"] = True
                break
            sample = self._bit("tb_secure_tm")
            samples += 1
            highs += sample
            if strap_high:
                pulse_samples += 1
                pulse_highs += sample
            if not raised and strobes >= STROBE_RAISE:
                dut.tb_secure_tm_req.value = 1
                strap_high = raised = True
                raise_rec.update(used=cycle + 1, last=f"strobes={strobes}", hit=True)
                self._step("S5", f"strap raised at response strobe {strobes}")
            if raised and not lowered and strobes >= STROBE_LOWER:
                dut.tb_secure_tm_req.value = 0
                strap_high = False
                lowered = True
                lower_rec.update(used=cycle + 1, last=f"strobes={strobes}", hit=True)
        else:
            self._timeout("done_rise_2")
        for label, rec in (("strobe_100", raise_rec), ("strobe_180", lower_rec)):
            if not rec["hit"]:
                rec["used"] = DONE_BOUND
                rec["last"] = f"strobes={self._strobes() - base} at done"
                self._timeout(label)
        return {
            "samples": samples,
            "highs": highs,
            "pulse_samples": pulse_samples,
            "pulse_highs": pulse_highs,
            "strobes": self._strobes() - base,
        }

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        probe = self.probe

        self._step("S1", "setup: real sense, strap at 1 before the first cold reset")
        if "skip_fuse_sense" in cocotb.plusargs:
            raise AssertionError("+skip_fuse_sense is set; a real sense is required")
        await self._wait_reset_done()
        await RisingEdge(dut.clk_smu_i)
        strap = self._bit("tb_secure_tm_req")
        self.log.info("CELL strap_before_first_reset tb_secure_tm_req=%d", strap)
        if strap != 1:
            raise AssertionError(f"tb_secure_tm_req={strap}, want 1 held through bring-up")

        self._step("S2", "leg 1: first done rise with the strap at 1")
        await self._wait_done_rise("done_rise_1", 0)
        await ClockCycles(dut.clk_smu_i, LEG1_SAMPLE_DELAY)
        leg1 = self._bit("tb_secure_tm")
        self.log.info(
            "CELL leg1_latched secure_tm_o=%d resp_words=%d",
            leg1,
            probe.resp_words["sep_efuse_shim"],
        )
        sb.expect_eq("secure_tm_o latched 1 by leg 1", leg1, 1, evidence=CLEAR)

        self._step("S3", "leg 2: cold reset with the strap still 1")
        reset_rec = self._site("sep_reset_low", RESET_LOW_BOUND, "clk_ref_i")
        self._site("reset_hold_samples", HOLD_SAMPLE_BOUND, "clk_smu_i")
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        for cycle in range(RESET_LOW_BOUND):
            await RisingEdge(dut.clk_ref_i)
            done = self._bit("sep_fuse_sense_done_o")
            rst_n = self._bit("obs_sep_rst_n_o")
            reset_rec["used"] = cycle + 1
            reset_rec["last"] = f"sep_fuse_sense_done_o={done} obs_sep_rst_n_o={rst_n}"
            if done == 0 and rst_n == 0:
                reset_rec["hit"] = True
                break
        else:
            self._timeout("sep_reset_low")
        self._hold_over = False
        hold_task = cocotb.start_soon(self._hold_sampler())
        await ClockCycles(dut.clk_ref_i, RESET_HOLD_REF_CYCLES)
        self._hold_over = True
        hold_samples, hold_highs = await hold_task
        self.log.info(
            "CELL latched_1_cleared samples=%d highs=%d strap=%d",
            hold_samples,
            hold_highs,
            self._bit("tb_secure_tm_req"),
        )
        sb.expect_eq(
            "secure_tm_o reads 0 on every clk_smu_i sample of the cold-reset hold",
            (hold_samples > 0, hold_highs),
            (True, 0),
            evidence=CLEAR,
        )
        dut.tb_secure_tm_req.value = 0

        self._step("S4", "leg 2: release and sample secure_tm_o every clk_smu_i until done")
        rises_before = len(probe.rises["sep_fuse_sense_done_o"])
        base = self._strobes()
        self._site("tap_reset", TAP_RESET_TCK, "TCK")
        self._site("done_rise_2", DONE_BOUND, "clk_smu_i")
        self._site("strobe_100", STROBE_BOUND, "clk_smu_i")
        self._site("strobe_180", STROBE_BOUND, "clk_smu_i")
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        window_task = cocotb.start_soon(self._window(rises_before, base))
        tck_task = cocotb.start_soon(self._tck_counter())
        await self.test.jtag_tap_reset(TAP_RESET_TCK)
        await tck_task
        window = await window_task
        samples, highs = window["samples"], window["highs"]
        self.log.info("CELL strobes_at_done resp_words=%d (informational)", window["strobes"])
        self.log.info(
            "CELL stays_0_after_release_before_sample samples=%d highs=%d", samples, highs
        )
        sb.expect_eq(
            "secure_tm_o samples from release to done: enough, none high",
            (samples >= MIN_WINDOW_SAMPLES, highs),
            (True, 0),
            evidence=CLEAR,
        )
        self.log.info(
            "CELL strap_1_before_sample pulse_samples=%d highs=%d",
            window["pulse_samples"],
            window["pulse_highs"],
        )
        sb.expect_eq(
            "secure_tm_o samples while the strap pulses at 1 before done",
            (window["pulse_samples"] > 0, window["pulse_highs"]),
            (True, 0),
            evidence=NO_FOLLOW,
        )

        self._step("S6", "after the done rise with the strap at 0")
        after_high = 0
        for _ in range(AFTER_EDGE_SAMPLES):
            await RisingEdge(dut.clk_smu_i)
            after_high += self._bit("tb_secure_tm")
        self.log.info("CELL after_edge_strap_0 samples=%d highs=%d", AFTER_EDGE_SAMPLES, after_high)
        sb.expect_eq(
            "secure_tm_o samples after done with the strap at 0", after_high, 0, evidence=NO_FOLLOW
        )

        self._step("S7", "timeout paths and ordered fence")
        for label, rec in self.sites.items():
            if not (0 < rec["bound"] < float("inf")) or not rec["last"] or rec["last"] == "none":
                raise AssertionError(f"TIMEOUT-PATH {label}: no finite bound or last state: {rec}")
            state = "EXPIRED" if self._expired(rec) else "ok"
            self.log.info(
                "TIMEOUT-PATH %s: bound=%d %s used=%d %s last=%s",
                label,
                rec["bound"],
                rec["unit"],
                rec["used"],
                state,
                rec["last"],
            )
        expired = sum(self._expired(rec) for rec in self.sites.values())
        self.log.info("CHK-TIMEOUT-PATHS: sites=%d expired=%d", len(self.sites), expired)
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")

        await RisingEdge(dut.clk_smu_i)
        self.log.info(
            "CELL final_strap_and_secure_tm tb_secure_tm_req=%d secure_tm_o=%d",
            self._bit("tb_secure_tm_req"),
            self._bit("tb_secure_tm"),
        )
        self.stamps["PASS"] = get_sim_time("ns")
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "PASS"]
        ordered = [self.stamps[b] > self.stamps[a] for a, b in zip(order, order[1:])]
        fence = "<".join(f"{k}@{self.stamps[k]:.1f}" for k in order)
        self.log.info("CHK-NONVAC: %s", fence)
        sb.expect_eq(
            "CHK-NONVAC ordered fence", ordered, [True] * len(ordered), evidence="CHK-NONVAC"
        )
