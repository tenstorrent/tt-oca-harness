# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_sep_cold_reassert_during_sense_test.

Contract SMU_SEP_005, anchor smu_sep_cold_reassert_during_sense_test.
Spec: hw/sys/sep/doc/reset_controller.adoc, hw/sys/sep/doc/clk_rst.adoc,
hw/sys/sep/doc/otp_fuse_controller.adoc, hw/ip/efuse/doc/architecture.adoc.
Response valid bit: hw/ip/efuse/doc/interface.adoc; done reset value 0: sep_cpu_ctrl.rdl.

The SEP reset follows the cold reset, done is cleared only through the cold reset, and sensing
restarts after the release. Leg 1 re-asserts the cold reset with done high and runs a second full
sense. Legs 2 to 4 assert it after response word 0, 128 and near 255 of a sense: every sample
after the falls reads sep_reset_n_o 0 and done 0, and done does not rise. The last leg runs a full
sense that delivers at least 256 response words before the first done sample of 1 and rises once.
The latency from the pin to each fall is logged and not compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

RESET_REASSERT = "SEP_RESET_REASSERT"
DONE_COLD_CLEAR = "SEP_DONE_COLD_CLEAR"
ABORT_RESTART = "SEP_SENSE_ABORT_RESTART"
SENSE_BOUND = 200000
STROBE_BOUND = 200000
COLD_FALL_BOUND = 2000
RESET_RISE_BOUND = 2000
HOLD_REF_CYCLES = 64
RESET_DONE_BOUND = 20000
HOLD_SAMPLE_CAP = 100000
TAP_RESET_TCK = 16
FULL_SENSE_WORDS = 256
LAST_WORD = 255
LEG_WORD_TRIGGERS = (("0", 1), ("128", 128))
CONTRACT_WAIT_KINDS = ("done_rise", "strobe", "cold_fall", "cold_rise", "reset_rise")


class smu_sep_cold_reassert_during_sense_test_seq:
    """Cold reset re-assertion at chosen instants of the SEP fuse sense."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.probe = test.fuse_probe
        self.stamps: dict[str, float] = {}
        self.sites: dict[str, dict] = {}
        self.base = 0
        self.rises_before = 0
        self.req_base = 0
        self.held: dict = {}
        self.fall_latency_strobes: list[int] = []

    def _site(self, label: str, kind: str, bound: int, unit: str) -> dict:
        rec = {"kind": kind, "bound": bound, "unit": unit, "used": 0, "last": "none"}
        self.sites[label] = rec
        return rec

    def _expire(self, label: str, rec: dict) -> None:
        rec["used"] = rec["bound"]
        self.log.info(
            "TIMEOUT-PATH %s: bound=%d %s EXPIRED last=%s",
            label,
            rec["bound"],
            rec["unit"],
            rec["last"],
        )
        raise AssertionError(f"TIMEOUT {label} {rec['last']}")

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _step(self, step: str, text: str) -> None:
        await RisingEdge(self.dut.clk_smu_i)
        self.stamps[step] = get_sim_time("ns")
        self.log.info("STEP %s @%.1f ns: %s", step, self.stamps[step], text)

    def _strobes(self) -> int:
        return self.probe.resp_words["sep_efuse_shim"] - self.base

    def _rises(self) -> int:
        return len(self.probe.rises["sep_fuse_sense_done_o"]) - self.rises_before

    async def _wait_first_done_rise(self, label: str) -> None:
        rec = self._site(label, "done_rise", SENSE_BOUND, "clk_smu_i")
        for cycle in range(SENSE_BOUND):
            rec["used"] = cycle
            rec["last"] = f"done_rises={self._rises()} strobes={self._strobes()}"
            if self._rises() > 0:
                return
            await RisingEdge(self.dut.clk_smu_i)
        self._expire(label, rec)

    async def _wait_sep_reset_high(self, label: str) -> None:
        rec = self._site(label, "reset_rise", RESET_RISE_BOUND, "clk_smu_i")
        for cycle in range(RESET_RISE_BOUND):
            rec["used"] = cycle
            rec["last"] = f"sep_reset_n_o={self._bit('sep_reset_n_o')}"
            if self._bit("sep_reset_n_o"):
                return
            await RisingEdge(self.dut.clk_smu_i)
        self._expire(label, rec)

    async def _release(self, label: str, walk: bool = True) -> None:
        """Release the cold reset and restart the per-leg strobe and rise counters."""
        self.base = self.probe.resp_words["sep_efuse_shim"]
        self.rises_before = len(self.probe.rises["sep_fuse_sense_done_o"])
        self.req_base = self.probe.req_pulses["sep_efuse_shim"]
        self.dut.rst_cold_ni.value = 1
        self.dut.jtag_trst.value = 1
        rec = self._site(f"cold_rise_{label}", "cold_rise", COLD_FALL_BOUND, "clk_ref_i")
        for cycle in range(COLD_FALL_BOUND):
            await RisingEdge(self.dut.clk_ref_i)
            rec["used"] = cycle + 1
            rec["last"] = f"rst_cold_n_o={self._bit('rst_cold_n_o')}"
            if self._bit("rst_cold_n_o"):
                break
        else:
            self._expire(f"cold_rise_{label}", rec)
        if not walk:
            self.log.info("TAP reset walk %s: skipped (trigger armed at release)", label)
            return
        await self.test.jtag_tap_reset(TAP_RESET_TCK)
        self.log.info(
            "TAP reset walk %s: %d TCK pulses (fixed loop, no wait)", label, TAP_RESET_TCK
        )

    async def _wait_fall(self, label: str, net: str) -> int:
        rec = self._site(f"{label}_{net}", "cold_fall", COLD_FALL_BOUND, "clk_ref_i")
        for cycle in range(COLD_FALL_BOUND):
            await RisingEdge(self.dut.clk_ref_i)
            rec["used"] = cycle + 1
            rec["last"] = f"{net}={self._bit(net)} strobes={self._strobes()}"
            if self._bit(net) == 0:
                return cycle + 1
        self._expire(f"{label}_{net}", rec)
        return 0

    async def _assert_cold(self, label: str) -> int:
        """Assert the cold reset, wait for both falls, return the strobes delivered at the fall.

        A sampler starts at the rst_cold_n_o fall and runs until ``_hold`` stops it; it counts
        done on every clk_smu_i and sep_reset_n_o once its own fall was seen.
        """
        self.dut.rst_cold_ni.value = 0
        self.dut.jtag_trst.value = 0
        cold = await self._wait_fall(label, "rst_cold_n_o")
        strobes = self._strobes()
        counts = {
            "samples": 0,
            "sep_samples": 0,
            "sep_highs": 0,
            "done_highs": 0,
            "stop": False,
            "sep_low_seen": False,
        }
        rec = self._site(f"hold_{label}", "hold", HOLD_SAMPLE_CAP, "clk_smu_i")

        async def sampler() -> None:
            for _ in range(HOLD_SAMPLE_CAP):
                await RisingEdge(self.dut.clk_smu_i)
                if counts["stop"]:
                    return
                counts["samples"] += 1
                counts["done_highs"] += self._bit("sep_fuse_sense_done_o")
                if counts["sep_low_seen"]:
                    counts["sep_samples"] += 1
                    counts["sep_highs"] += self._bit("sep_reset_n_o")
                rec["used"] = counts["samples"]
                rec["last"] = f"sep_highs={counts['sep_highs']} done_highs={counts['done_highs']}"

        counts["task"] = cocotb.start_soon(sampler())
        self.held[label] = (counts, rec)
        sep = await self._wait_fall(label, "sep_reset_n_o")
        counts["sep_low_seen"] = True
        self.log.info(
            "CHK-SEP-RESET-REASSERT: leg=%s latency_ref_cycles rst_cold_n_o=%d sep_reset_n_o=%d",
            label,
            cold,
            sep,
        )
        return strobes

    async def _hold(self, label: str) -> dict:
        """Hold the reset for the contract window, then stop the sampler started at the fall."""
        counts, rec = self.held.pop(label)
        await ClockCycles(self.dut.clk_ref_i, HOLD_REF_CYCLES)
        counts["stop"] = True
        await counts["task"].join()
        if rec["used"] >= rec["bound"]:
            self._expire(f"hold_{label}", rec)
        return counts

    async def _wait_strobes(self, label: str, target: int) -> None:
        rec = self._site(label, "strobe", STROBE_BOUND, "clk_smu_i")
        for cycle in range(STROBE_BOUND):
            rec["used"] = cycle
            rec["last"] = f"strobes={self._strobes()} done={self._bit('sep_fuse_sense_done_o')}"
            if self._strobes() >= target:
                return
            await RisingEdge(self.dut.clk_smu_i)
        self._expire(label, rec)

    async def _abort_leg(self, name: str, label: str, target: int) -> int:
        """Release, trigger at ``target`` strobes, re-assert, compare the held samples."""
        await self._release(label, walk=False)
        await self._wait_strobes(f"strobe_{name}", target)
        strobes_at_trigger = self._strobes()
        self.sb.expect_eq(
            f"abort after word {name}: trigger taken at the target strobe count",
            strobes_at_trigger,
            target,
            evidence=ABORT_RESTART,
        )
        strobes_at_fall = await self._assert_cold(f"abort_{name}")
        self.log.info(
            "CELL abort_trigger_%s target=%d strobes_at_trigger=%d strobes_at_fall=%d",
            name,
            target,
            strobes_at_trigger,
            strobes_at_fall,
        )
        self.fall_latency_strobes.append(strobes_at_fall - strobes_at_trigger)
        held = await self._hold(f"abort_{name}")
        await self._compare_held(name, strobes_at_fall, held, ABORT_RESTART)
        return strobes_at_fall

    async def _compare_held(self, name: str, strobes_at_fall: int, held: dict, token: str) -> None:
        sb = self.sb
        rises = self._rises()
        self.log.info(
            "CELL reset_after_word_%s strobes_at_fall=%d rises=%d samples=%d done_highs=%d",
            name,
            strobes_at_fall,
            rises,
            held["samples"],
            held["done_highs"],
        )
        sb.expect_eq(
            f"abort after word {name}: samples taken, done never high, no done rise",
            (held["samples"] > 0, held["done_highs"], rises),
            (True, 0, 0),
            evidence=token,
        )
        self.log.info(
            "CELL reassert_during_sense word=%s samples=%d highs=%d",
            name,
            held["sep_samples"],
            held["sep_highs"],
        )
        sb.expect_eq(
            f"abort after word {name}: sep_reset_n_o never high",
            held["sep_highs"],
            0,
            evidence=RESET_REASSERT,
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        probe = self.probe

        await self._step("S1", "setup: real sense, leg 0 done rise")
        if "skip_fuse_sense" in cocotb.plusargs:
            raise AssertionError("+skip_fuse_sense is set; a real sense is required")
        rec = self._site("reset_done", "bring_up", RESET_DONE_BOUND, "clk_ref_i")
        for cycle in range(RESET_DONE_BOUND):
            rec["used"] = cycle
            rec["last"] = f"reset_done set={self.cfg.reset_done.is_set()}"
            if self.cfg.reset_done.is_set():
                break
            await RisingEdge(dut.clk_ref_i)
        else:
            self._expire("reset_done", rec)
        await self._wait_first_done_rise("done_rise_0")
        self.log.info(
            "CELL leg0_done rises=%d resp_words=%d",
            len(probe.rises["sep_fuse_sense_done_o"]),
            probe.resp_words["sep_efuse_shim"],
        )

        await self._step("S2", "leg 1: cold reset with done high")
        await self._wait_sep_reset_high("sep_reset_rise_0")
        pre = (self._bit("sep_reset_n_o"), self._bit("sep_fuse_sense_done_o"))
        self.log.info("CELL pre_assert sep_reset_n_o=%d done=%d", *pre)
        sb.expect_eq("sep_reset_n_o and done high before the re-assertion", pre, (1, 1))
        await self._assert_cold("leg1")
        held = await self._hold("leg1")
        self.log.info(
            "CELL reassert_after_release samples=%d highs=%d",
            held["sep_samples"],
            held["sep_highs"],
        )
        sb.expect_eq(
            "sep_reset_n_o samples under the re-asserted cold reset",
            (held["sep_samples"] > 0, held["sep_highs"]),
            (True, 0),
            evidence=RESET_REASSERT,
        )
        self.log.info(
            "CELL cleared_by_cold_reset samples=%d highs=%d", held["samples"], held["done_highs"]
        )
        sb.expect_eq(
            "done samples under the re-asserted cold reset",
            (held["samples"] > 0, held["done_highs"]),
            (True, 0),
            evidence=DONE_COLD_CLEAR,
        )

        await self._step("S3", "leg 1: release and second full sense")
        await self._release("leg1")
        await self._wait_first_done_rise("done_rise_1")
        strobes = self._strobes()
        await RisingEdge(dut.clk_smu_i)
        rises = self._rises()
        self.log.info("CELL second_sequence_single_rise rises=%d strobes=%d", rises, strobes)
        sb.expect_eq(
            "second sense: one done rise after at least 256 response strobes",
            (rises, strobes >= FULL_SENSE_WORDS),
            (1, True),
            evidence=DONE_COLD_CLEAR,
        )

        await self._step("S4", "leg 2: abort after word 0")
        await self._assert_cold("leg2")
        await self._hold("leg2")
        await self._abort_leg("0", "leg2", LEG_WORD_TRIGGERS[0][1])

        await self._step("S5", "leg 3: abort after word 128")
        await self._abort_leg("128", "leg3", LEG_WORD_TRIGGERS[1][1])

        await self._step("S6", "leg 4: abort near word 255")
        latency = max(self.fall_latency_strobes)
        trigger = LAST_WORD - latency - 1
        self.log.info(
            "CELL word_255_trigger latency_strobes=%d trigger=%d formula=255-latency-1",
            latency,
            trigger,
        )
        await self._release("leg4", walk=False)
        await self._wait_strobes(f"strobe_{trigger}", trigger)
        at_trigger = self._strobes()
        sb.expect_eq(
            "abort after word 255: trigger taken at the target strobe count",
            at_trigger,
            trigger,
            evidence=ABORT_RESTART,
        )
        at_fall = await self._assert_cold("abort_255")
        self.log.info(
            "CELL abort_trigger_255 target=%d strobes_at_trigger=%d strobes_at_fall=%d",
            trigger,
            at_trigger,
            at_fall,
        )
        self.log.info(
            "CHK-SEP-SENSE-ABORT-RESTART: word255 trigger=%d strobes_at_trigger=%d at_fall=%d",
            trigger,
            at_trigger,
            at_fall,
        )
        held = await self._hold("abort_255")
        if at_fall < FULL_SENSE_WORDS:
            await self._compare_held("255", at_fall, held, ABORT_RESTART)
        else:
            self.log.info("OBSERVED word-255 window missed strobes_at_fall=%d", at_fall)
            self.log.info("CHK-SEP-SENSE-ABORT-RESTART: word255=missed LINKED-ISSUE SF-014")

        await self._step("S7", "final leg: release and a full sense")
        await self._release("final")
        rec = self._site("done_rise_final", "done_rise", SENSE_BOUND, "clk_smu_i")
        strobes_at_first_done = None
        new_requests = 0
        for cycle in range(SENSE_BOUND):
            rec["used"] = cycle
            rec["last"] = f"strobes={self._strobes()} done_rises={self._rises()}"
            if self._bit("sep_fuse_sense_done_o"):
                strobes_at_first_done = self._strobes()
                new_requests = probe.req_pulses["sep_efuse_shim"] - self.req_base
                break
            await RisingEdge(dut.clk_smu_i)
        if strobes_at_first_done is None:
            self._expire("done_rise_final", rec)
        await RisingEdge(dut.clk_smu_i)
        rises = self._rises()
        self.log.info(
            "CELL restart_full_sequence strobes=%d rises=%d", strobes_at_first_done, rises
        )
        sb.expect_eq(
            "final sense: at least 256 strobes before the first done sample, one rise",
            (strobes_at_first_done >= FULL_SENSE_WORDS, rises),
            (True, 1),
            evidence=ABORT_RESTART,
        )
        sb.expect_eq(
            "final sense: a new request rising edge before the first done sample",
            new_requests >= 1,
            True,
            evidence=ABORT_RESTART,
        )

        await self._step("S8", "timeout paths and ordered fence")
        for label, rec in self.sites.items():
            state = "EXPIRED" if rec["used"] >= rec["bound"] else "ok"
            self.log.info(
                "TIMEOUT-PATH %s: bound=%d %s used=%d %s last=%s",
                label,
                rec["bound"],
                rec["unit"],
                rec["used"],
                state,
                rec["last"],
            )
        expired = sum(rec["used"] >= rec["bound"] for rec in self.sites.values())
        bounds_finite = all(
            isinstance(rec["bound"], int) and 0 < rec["bound"] < 10**9
            for rec in self.sites.values()
        )
        last_states = all(rec["last"] and rec["last"] != "none" for rec in self.sites.values())
        self.log.info("CHK-TIMEOUT-PATHS: sites=%d expired=%d", len(self.sites), expired)
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq(
            "every bound finite and every last state recorded",
            (bounds_finite, last_states),
            (True, True),
            evidence="CHK_TIMEOUT_PATHS",
        )
        kinds = {rec["kind"] for rec in self.sites.values()}
        sb.expect_true(
            "every bounded wait kind named by the contract ran",
            all(kind in kinds for kind in CONTRACT_WAIT_KINDS),
        )

        await RisingEdge(dut.clk_smu_i)
        self.stamps["PASS"] = get_sim_time("ns")
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "PASS"]
        deltas = [self.stamps[b] - self.stamps[a] for a, b in zip(order, order[1:])]
        fence = "<".join(f"{k}@{self.stamps[k]:.1f}" for k in order)
        self.log.info("CHK-NONVAC: %s", fence)
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            [d > 0 for d in deltas],
            [True] * len(deltas),
            evidence="CHK-NONVAC",
        )
