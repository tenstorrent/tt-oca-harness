# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP watchdog bite into the SMC reset unit, and its release through the cool-reset pin.

Bring-up is the SEP debug-module steps of ``smu_dtp_sep_dm_dmi_test`` and every later access is
a debug system-bus access (RISC-V Debug Specification 0.13). The SEP watchdog second stage
raises ``wdt_timer_rst_req_o`` (``hw/sys/sep/doc/watchdog.adoc``, "Bark Interrupt and Bite
Reset"), which the SMC reset unit takes as the external watchdog input: the watchdog reset is
``rst_ext_wdt_ni AND NOT smc_wdt_second_timeout_i`` and the warm reset is ``rst_primary_n AND
rst_wdt_n AND fuse_reset_ni``, the primary reset carrying no watchdog term
(``hw/sys/smc/doc/clk_rst.adoc``, reset equations). The SEP watchdog and its request are reset
by ``rst_ni`` while ``wdt_rst_ni`` resets only the core and warm scratch
(``hw/sys/sep/doc/reset_controller.adoc``), so the request holds until the cool-reset pin
asserts the primary reset and, through it, the SEP main reset.

Every clk_smu_i sample from the bite to the end of the closing window is recorded by a
free-running monitor, so the ordering and rise-count checks see every cycle.
"""

from __future__ import annotations

from collections import Counter
from typing import NamedTuple

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import smu_dtp_sep_dm_dmi_test_seq
from seq_lib.smu_dtp_sep_dm_sba_test_seq import _REPO_ROOT, _SEP_ADDR_H
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import smu_sep_sba_fabric_sweep_test_seq
from seq_lib.smu_tb_pins import cold_stable_reset, smc_primary_reset, smu_scope

_AON_H = _REPO_ROOT / "vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/gen/c/aon_timer.h"

WDOG_CTRL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR")
WDOG_BARK = c_header_u32(_SEP_ADDR_H, "SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR")
WDOG_BITE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR")
WDOG_COUNT = c_header_u32(_SEP_ADDR_H, "SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR")
# aon_timer.h WDOG_CTRL.ENABLE: the bite request needs the watchdog enabled.
WDOG_ENABLE = c_header_u32(_AON_H, "AON_TIMER__WDOG_CTRL__ENABLE_bm")
# Small bark and bite thresholds, in watchdog clock ticks, so the bite arrives early.
WDOG_THRESHOLD = 0x20
# System-bus access size 2 is a 32-bit access (RISC-V Debug Specification 0.13, sbcs.sbaccess).
SB_ACCESS_32 = 2

# watchdog.adoc "Bark Interrupt and Bite Reset": the bite request is a level that reads 1 once
# the second stage expires and 0 otherwise.
REQUEST_IDLE = 0
REQUEST_RAISED = 1
# clk_rst.adoc reset equations: every reset net is active low, so 1 is released and 0 asserted.
NET_RELEASED = 1
NET_ASSERTED = 0

WDT_REQ_PATH = "sep_wdt_timer_rst_req"
WDT_RESET_PATH = "u_smc.rst_wdt_smc_clk_no"
WARM_RESET_PATH = "u_smc.rst_warm_smc_clk_n"

# clk_rst.adoc: the cool-reset pin passes a 32-cycle de-glitcher; the pin is held for a multiple
# of it, in clk_ref_i cycles.
COOL_HOLD_REF_CYCLES = 256

# Bounds of the bounded waits and lengths of the sampled windows, in clk_smu_i cycles.
REQUEST_RISE_BOUND = 200000
ASSERT_BOUND = 4096
PRIMARY_ASSERT_BOUND = 4096
REQUEST_FALL_BOUND = 4096
RELEASE_BOUND = 20000
HOLD_WINDOW_CYCLES = 256
CLOSING_WINDOW_CYCLES = 256
STEP_CLOCK_GAP = 2
SAMPLE_GAP_CYCLES = 1

# Wait sites per kind: the request rise, the two reset-net assertions, the primary assertion,
# the request fall and the three releases.
EXPECTED_SITE_KINDS = {
    "request_rise": 1,
    "assert": 2,
    "primary_assert": 1,
    "request_fall": 1,
    "release": 3,
}
EXPECTED_SITES = 8

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12")


class Sample(NamedTuple):
    """One clk_smu_i sample of the request, the reset nets and the logged vectors."""

    t_ps: int
    req: int
    wdt: int
    warm: int
    primary: int
    cold: int
    second: int
    warm_vec: int
    sep_rst: int


class smu_sep_wdt_bite_to_smc_reset_test_seq(smu_sep_sba_fabric_sweep_test_seq):
    """SEP watchdog bite to the SMC watchdog-term and warm resets, and the release."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.smu = smu_scope(self.dut)
        self.clk = self.dut.clk_smu_i
        self.req = hier(self.smu, WDT_REQ_PATH)
        self.wdt = hier(self.smu, WDT_RESET_PATH)
        self.warm = hier(self.smu, WARM_RESET_PATH)
        self.primary = smc_primary_reset(self.dut)
        self.cold = cold_stable_reset(self.dut)
        self.period_ps = round(self.cfg.smu_clk_period_ns * 1000)
        self.trace: list[Sample] = []
        self.sites: list[dict] = []
        self.stamp_ps: dict[str, int] = {}
        self.done = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _record(self) -> Sample:
        now = int(get_sim_time(unit="ps"))
        if self.trace and self.trace[-1].t_ps == now:
            return self.trace[-1]
        dut = self.dut
        entry = Sample(
            now,
            sample(self.req, WDT_REQ_PATH),
            sample(self.wdt, WDT_RESET_PATH),
            sample(self.warm, WARM_RESET_PATH),
            sample(self.primary, "rst_primary_smc_clk_n_o"),
            sample(self.cold, "rst_cold_n_o"),
            sample(dut.tb_smc_wdt_second_timeout, "tb_smc_wdt_second_timeout"),
            sample(dut.tb_ss_warm_reset_n, "tb_ss_warm_reset_n"),
            sample(dut.obs_sep_rst_n_o, "obs_sep_rst_n_o"),
        )
        self.trace.append(entry)
        return entry

    async def _tick(self) -> Sample:
        await RisingEdge(self.clk)
        return self._record()

    async def _monitor(self) -> None:
        while True:
            await RisingEdge(self.clk)
            self._record()

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.stamp_ps[step] = int(get_sim_time(unit="ps"))
        self._log(f"STEP {step} @{self.stamp_ps[step] / 1000:.3f}ns: {text}")

    def _first(self, pred, start: int = 0) -> int:
        for idx in range(start, len(self.trace)):
            if pred(self.trace[idx]):
                return idx
        return -1

    @staticmethod
    def _state(s: Sample) -> str:
        return f"req={s.req} rst_wdt={s.wdt} rst_warm={s.warm} primary={s.primary} cold={s.cold}"

    async def _wait(self, kind: str, label: str, pred, bound: int) -> int:
        """Tick until ``pred`` holds; the site is recorded and an expiry fails the leaf."""
        used = 0
        s = await self._tick()
        while not pred(s) and used < bound:
            s = await self._tick()
            used += 1
        expired = not pred(s)
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "used": used,
                "last": self._state(s),
                "expired": int(expired),
            }
        )
        if expired:
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={bound} used={used} last_state={self._state(s)}"
            )
        return used

    async def _window(self, cycles: int) -> list[Sample]:
        return [await self._tick() for _ in range(cycles)]

    def _gap_count(self, lo: int, hi: int) -> int:
        span = self.trace[lo : hi + 1]
        return sum(
            1
            for a, b in zip(span, span[1:])
            if b.t_ps - a.t_ps != SAMPLE_GAP_CYCLES * self.period_ps
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        assert self.s1_ok and self.s2_ok and self.s3_ok, "SEP debug bring-up incomplete"
        jtag = self.jtag
        await self._mark("S1", "TEST_DEV bring-up, debug module reachable, system bus enabled")

        base = await self._tick()
        self._log(
            f"OBSERVATION baseline tb_smc_wdt_second_timeout={base.second} "
            f"obs_sep_rst_n_o={base.sep_rst} (precondition) "
            f"tb_ss_warm_reset_n=0x{base.warm_vec:08x}"
        )
        await self._mark("S2", f"baseline sample: {self._state(base)}")
        monitor = cocotb.start_soon(self._monitor())

        await self._sb_ok(jtag, WDOG_BARK, SB_ACCESS_32, WDOG_THRESHOLD)
        await self._sb_ok(jtag, WDOG_BITE, SB_ACCESS_32, WDOG_THRESHOLD)
        await self._sb_ok(jtag, WDOG_COUNT, SB_ACCESS_32, 0)
        enable_idx = len(self.trace)
        await self._sb_ok(jtag, WDOG_CTRL, SB_ACCESS_32, WDOG_ENABLE)
        await self._mark("S3", "watchdog thresholds, count and enable written")

        rise_used = await self._wait(
            "request_rise",
            "sep_wdt_timer_rst_req",
            lambda s: s.req == REQUEST_RAISED,
            REQUEST_RISE_BOUND,
        )
        await self._wait("assert", "rst_wdt", lambda s: s.wdt == NET_ASSERTED, ASSERT_BOUND)
        await self._wait("assert", "rst_warm", lambda s: s.warm == NET_ASSERTED, ASSERT_BOUND)
        i_req = self._first(lambda s: s.req == REQUEST_RAISED)
        i_wdt = self._first(lambda s: s.wdt == NET_ASSERTED)
        i_warm = self._first(lambda s: s.warm == NET_ASSERTED)
        wdt_cycles, warm_cycles = i_wdt - i_req, i_warm - i_req
        self._log(
            f"OBSERVATION request rise cycles after the WDOG_CTRL access began measured="
            f"{i_req - enable_idx}; request rise wait cycles measured={rise_used}; "
            f"rst_wdt fall cycles after request measured={wdt_cycles}; "
            f"rst_warm fall cycles after request measured={warm_cycles}"
        )
        await self._mark("S4", "request raised, rst_wdt and rst_warm asserted")

        settled = await self._tick()
        self._log(
            f"OBSERVATION settled tb_smc_wdt_second_timeout={settled.second} (SMC watchdog not "
            "armed by this leaf; logged only)"
        )
        await self._mark("S5", f"settled sample after the bite: {self._state(settled)}")

        hold = await self._window(HOLD_WINDOW_CYCLES)
        i_hold = len(self.trace) - HOLD_WINDOW_CYCLES
        hold_vectors = sorted({(s.warm_vec, s.sep_rst) for s in hold})
        self._log(
            f"OBSERVATION tb_ss_warm_reset_n and obs_sep_rst_n_o during the hold window "
            f"measured={[(f'0x{v:08x}', r) for v, r in hold_vectors]} "
            f"before=(0x{base.warm_vec:08x}, {base.sep_rst})"
        )
        await self._mark("S6", f"hold window of {HOLD_WINDOW_CYCLES} samples")

        drive_idx = len(self.trace)
        self.dut.tb_cool_reset_pin.value = 1
        await ClockCycles(self.dut.clk_ref_i, COOL_HOLD_REF_CYCLES)
        await self._wait(
            "primary_assert",
            "rst_primary",
            lambda s: s.primary == NET_ASSERTED,
            PRIMARY_ASSERT_BOUND,
        )
        at_primary = await self._tick()
        i_primary = self._first(lambda s: s.primary == NET_ASSERTED)
        self._log(
            f"OBSERVATION primary assert cycles after the cool pin drive measured="
            f"{i_primary - drive_idx}"
        )
        await self._mark("S7", f"cool pin held, primary asserted: {self._state(at_primary)}")

        await self._wait(
            "request_fall",
            "sep_wdt_timer_rst_req",
            lambda s: s.req == REQUEST_IDLE,
            REQUEST_FALL_BOUND,
        )
        at_fall = await self._tick()
        i_fall = self._first(lambda s: s.req == REQUEST_IDLE, i_req)
        self._log(
            f"OBSERVATION request fall cycles after primary assert measured={i_fall - i_primary}"
        )
        await self._mark("S8", f"request fell: {self._state(at_fall)}")

        self.dut.tb_cool_reset_pin.value = 0
        release_idx = len(self.trace)
        await self._wait(
            "release", "rst_primary", lambda s: s.primary == NET_RELEASED, RELEASE_BOUND
        )
        await self._wait("release", "rst_wdt", lambda s: s.wdt == NET_RELEASED, RELEASE_BOUND)
        await self._wait("release", "rst_warm", lambda s: s.warm == NET_RELEASED, RELEASE_BOUND)
        released = await self._tick()
        i_end9 = len(self.trace) - 1
        first_up = {
            "primary": self._first(lambda s: s.primary == NET_RELEASED, i_primary),
            "rst_wdt": self._first(lambda s: s.wdt == NET_RELEASED, i_wdt),
            "rst_warm": self._first(lambda s: s.warm == NET_RELEASED, i_warm),
        }
        order = sorted(first_up, key=first_up.get)
        self._log(
            f"OBSERVATION release order measured={order} cycles after the pin release="
            f"{ {k: v - release_idx for k, v in first_up.items()} }"
        )
        await self._mark("S9", f"cool pin released, nets back: {self._state(released)}")

        span = self.trace[i_req : i_end9 + 1]
        violations = sum(1 for s in span if s.warm == NET_RELEASED and s.wdt == NET_ASSERTED)
        wdt_low = sum(1 for s in span if s.wdt == NET_ASSERTED)
        gaps = self._gap_count(i_req, i_end9)
        await self._mark("S10", "ordering of the warm and watchdog resets evaluated")

        closing = await self._window(CLOSING_WINDOW_CYCLES)
        await self._mark("S11", f"closing window of {CLOSING_WINDOW_CYCLES} samples")
        await ClockCycles(self.clk, STEP_CLOCK_GAP)
        self.stamp_ps["S12"] = int(get_sim_time(unit="ps"))
        self._log(f"STEP S12 @{self.stamp_ps['S12'] / 1000:.3f}ns: PASS stamp")
        monitor.cancel()

        rises = sum(1 for a, b in zip(self.trace, self.trace[1:]) if b.req > a.req)
        after_vectors = sorted({(s.warm_vec, s.sep_rst) for s in closing})
        self._log(
            f"OBSERVATION tb_ss_warm_reset_n and obs_sep_rst_n_o after the closing window "
            f"measured={[(f'0x{v:08x}', r) for v, r in after_vectors]}"
        )

        self._check_request(sb, base, at_fall, i_primary, i_fall, enable_idx, i_req)
        self._check_assert(sb, i_req, i_wdt, i_warm)
        self._check_term_warm(sb, base, settled)
        self._check_primary_cold(sb, hold, i_hold, max(i_wdt, i_warm, i_req))
        self._check_hold(sb, hold)
        self._check_release(sb, at_primary, at_fall, released)
        self._check_order(sb, violations, wdt_low, gaps)
        self._check_converge(sb, closing, rises, settled, hold)
        self._check_integrity(sb)
        self.done = True

    def _check_request(self, sb, base, at_fall, i_primary, i_fall, enable_idx, i_req) -> None:
        after_primary = i_fall >= i_primary
        idle_until_enable = max(s.req for s in self.trace[:enable_idx])
        rose_after_enable = i_req >= enable_idx
        self._log(
            f"CHK-SEP-WDT-SMC-REQ: baseline request={base.req} expected={REQUEST_IDLE}; highest "
            f"request level at every sample before the enable access={idle_until_enable} "
            f"expected={REQUEST_IDLE}; first 1 sample {i_req} not before the enable access "
            f"sample {enable_idx}: {rose_after_enable}; request raised within its bound "
            f"(bounded wait); fall sample {i_fall} not before "
            f"the primary assert sample {i_primary}: {after_primary}; request after the primary "
            f"reset={at_fall.req} expected={REQUEST_IDLE}; set by WDOG_CTRL enable, observed 1, "
            "cleared by the cool pin through the primary reset, checked 0"
        )
        sb.expect_eq(
            "CHK-SEP-WDT-SMC-REQ idle, raised, falls only after the primary reset asserted",
            (
                base.req,
                idle_until_enable,
                rose_after_enable,
                after_primary,
                at_fall.req,
            ),
            (REQUEST_IDLE, REQUEST_IDLE, True, True, REQUEST_IDLE),
            evidence="CHK-SEP-WDT-SMC-REQ",
        )

    def _check_assert(self, sb, i_req, i_wdt, i_warm) -> None:
        self._log(
            f"CHK-SEP-WDT-SMC-ASSERT: rst_wdt and rst_warm read {NET_ASSERTED} within their "
            f"bounds, first {NET_ASSERTED} sample not before the request: "
            f"{(i_wdt >= i_req, i_warm >= i_req)}"
        )
        sb.expect_eq(
            "CHK-SEP-WDT-SMC-ASSERT both nets assert after the request first reads 1",
            (i_wdt >= i_req, i_warm >= i_req),
            (True, True),
            evidence="CHK-SEP-WDT-SMC-ASSERT",
        )

    def _check_term_warm(self, sb, base, settled) -> None:
        got = ((base.wdt, base.warm), (settled.req, settled.wdt, settled.warm))
        want = ((NET_RELEASED, NET_RELEASED), (REQUEST_RAISED, NET_ASSERTED, NET_ASSERTED))
        self._log(
            f"CHK-SEP-WDT-SMC-TERM-WARM: baseline (rst_wdt, rst_warm)={got[0]} expected={want[0]}; "
            f"settled (request, rst_wdt, rst_warm)={got[1]} expected={want[1]}"
        )
        sb.expect_eq(
            "CHK-SEP-WDT-SMC-TERM-WARM baseline released, settled asserted by the bite",
            got,
            want,
            evidence="CHK-SEP-WDT-SMC-TERM-WARM",
        )

    def _check_primary_cold(self, sb, hold, i_hold, i_changed) -> None:
        got = (sorted({(s.primary, s.cold) for s in hold}), i_hold > i_changed)
        want = ([(NET_RELEASED, NET_RELEASED)], True)
        self._log(
            f"CHK-SEP-WDT-SMC-PRIMARY-COLD: (primary, cold) levels over the hold window="
            f"{got[0]} expected={want[0]}; window began after the request and both nets "
            f"changed: {got[1]}"
        )
        sb.expect_eq(
            "CHK-SEP-WDT-SMC-PRIMARY-COLD primary and cold stay released across the bite",
            got,
            want,
            evidence="CHK-SEP-WDT-SMC-PRIMARY-COLD",
        )

    def _check_hold(self, sb, hold) -> None:
        got = sorted({(s.req, s.wdt, s.warm) for s in hold})
        want = [(REQUEST_RAISED, NET_ASSERTED, NET_ASSERTED)]
        self._log(
            f"CHK-SEP-WDT-SMC-HOLD: (request, rst_wdt, rst_warm) levels over the hold window="
            f"{got} expected={want}"
        )
        sb.expect_eq(
            "CHK-SEP-WDT-SMC-HOLD request held while both resets stay asserted",
            got,
            want,
            evidence="CHK-SEP-WDT-SMC-HOLD",
        )

    def _check_release(self, sb, at_primary, at_fall, released) -> None:
        got = (
            at_primary.primary,
            (at_fall.req, at_fall.primary),
            (released.primary, released.wdt, released.warm),
        )
        want = (
            NET_ASSERTED,
            (REQUEST_IDLE, NET_ASSERTED),
            (NET_RELEASED, NET_RELEASED, NET_RELEASED),
        )
        self._log(
            f"CHK-SEP-WDT-SMC-RELEASE: primary with the pin held={got[0]} expected={want[0]}; "
            f"(request, primary) after the fall={got[1]} expected={want[1]}; "
            f"(primary, rst_wdt, rst_warm) after the pin release={got[2]} expected={want[2]}"
        )
        sb.expect_eq(
            "CHK-SEP-WDT-SMC-RELEASE pin asserts primary, request falls, three nets released",
            got,
            want,
            evidence="CHK-SEP-WDT-SMC-RELEASE",
        )

    def _check_order(self, sb, violations, wdt_low, gaps) -> None:
        got = (violations, wdt_low > 0, gaps)
        want = (0, True, 0)
        self._log(
            f"CHK-SEP-WDT-SMC-ORDER: samples with rst_warm released while rst_wdt asserted="
            f"{violations} expected=0; rst_wdt asserted samples={wdt_low} (non-zero: "
            f"{wdt_low > 0}); sampling gaps={gaps} expected=0"
        )
        sb.expect_eq(
            "CHK-SEP-WDT-SMC-ORDER rst_warm never released while rst_wdt asserted, no gap",
            got,
            want,
            evidence="CHK-SEP-WDT-SMC-ORDER",
        )

    def _check_converge(self, sb, closing, rises, settled, hold) -> None:
        held = settled.req == REQUEST_RAISED and all(s.req == REQUEST_RAISED for s in hold)
        got = (
            sorted({(s.req, s.wdt, s.warm, s.primary, s.cold) for s in closing}),
            rises,
            held,
        )
        want = (
            [(REQUEST_IDLE, NET_RELEASED, NET_RELEASED, NET_RELEASED, NET_RELEASED)],
            1,
            True,
        )
        self._log(
            f"CHK-SEP-WDT-SMC-CONVERGE: (request, rst_wdt, rst_warm, primary, cold) over the "
            f"closing window={got[0]} expected={want[0]}; request rises={got[1]} expected=1; "
            f"request held 1 in the settled and hold samples: {got[2]}"
        )
        sb.expect_eq(
            "CHK-SEP-WDT-SMC-CONVERGE request stays low once, every net released",
            got,
            want,
            evidence="CHK-SEP-WDT-SMC-CONVERGE",
        )

    def _check_integrity(self, sb) -> None:
        for rec in self.sites:
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} "
                f"used={rec['used']} {'EXPIRED' if rec['expired'] else 'ok'} last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites)
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} expected={EXPECTED_SITES} kinds={kinds} "
            f"expired={expired}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK-TIMEOUT-PATHS")
        sb.expect_eq(
            "bounded wait sites per kind",
            (len(self.sites), kinds),
            (EXPECTED_SITES, EXPECTED_SITE_KINDS),
            evidence="CHK-TIMEOUT-PATHS",
        )

        stamps = [self.stamp_ps[s] for s in STEPS]
        fence = "<".join(f"{s}@{t / 1000:.1f}" for s, t in zip(STEPS, stamps))
        pass_gap = round((stamps[-1] - stamps[-2]) / self.period_ps)
        self._log(f"CHK-NONVAC: ordered sim-time fence {fence} pass_gap_cycles={pass_gap}")
        sb.expect_eq(
            "CHK-NONVAC ordered sim-time fence, PASS stamp two cycles after S11",
            (all(b > a for a, b in zip(stamps, stamps[1:])), pass_gap),
            (True, STEP_CLOCK_GAP),
            evidence="CHK-NONVAC",
        )
