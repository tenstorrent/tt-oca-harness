# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Structural production-wrapper sequence used before firmware bring-up.

DV-CARD:          SMU_ALL_001   ANCHOR: smu_wrapper_elaboration_test
"""

from __future__ import annotations

import itertools
import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer
from cocotb.utils import get_sim_time


class SmuWrapperElaborationSeq:
    """Check profile selection and reset propagation over repeated reset pulses.

    Executes the SMU_ALL_001 card steps and emits the card's ``CHK-*`` lines.
    ``+expected_sep`` is required and must be 1: the wrapper's one compile
    profile elaborates SEP, and the SEP=0 composition is proved on
    ``--dut smu_block``.
    """

    BOUND_REF_CYCLES = 500
    # Bounded waits in the SEP=1 card path (must match _timeout_paths length):
    # S1 powergood_stable baseline high + driven low + driven release + rst_cold
    # (4), S4 smu_axi awready (1), S5 prim assert + prim release + cold release
    # (3).
    EXPECTED_TIMEOUT_PATHS_SEP1 = 8
    # Non-vacuity floors. MIN_DUT_CHECKS is the number of fail-capable
    # comparisons against DUT-sourced samples the leg's own stimulus issues:
    # 8 bounded waits, 12 hierarchical clk-identity comparisons in the two
    # compose loops, 8 in the shared-domain loop, and the discrete
    # reset/domain/lifecycle compares.
    # MIN_ADVANCING_STEPS and MIN_SPAN_NS are the simulation time that stimulus
    # cannot complete in less than.
    MIN_DUT_CHECKS_SEP1 = 31
    MIN_ADVANCING_STEPS_SEP1 = 5
    MIN_SPAN_NS_SEP1 = 500
    # Domain-separation observation window. 240 ns is a whole multiple of every
    # clk_smu_i and clk_ref_i period smu_env_cfg draws, so the transition counts
    # of two distinct periods cannot coincide; the 1 ns sample step is below the
    # shortest half period (4 ns).
    DOMAIN_WINDOW_NS = 240
    DOMAIN_SAMPLE_NS = 1

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.rng = random.Random(test.random_seed())
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []
        self._dut_checks = 0

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = get_sim_time("ns")
        self.log.info("STEP %s: %s", step_id, detail)

    def _sample(self, signal, name: str) -> int:
        return self.test.read_int(signal, name, allow_xz=False)

    def _check(self, ok: bool, message: str) -> None:
        """Enforce and count one comparison over DUT-sourced samples."""
        self._dut_checks += 1
        assert ok, message

    def _assert_nonvac_fence(
        self,
        order: list[str],
        min_checks: int,
        min_advancing: int,
        min_span_ns: float,
    ) -> None:
        """Require step order, simulation-time advance, and DUT comparisons."""
        missing = [step_id for step_id in order if step_id not in self._step_ts]
        if missing:
            raise AssertionError(f"CHK-NONVAC missing step terms: {missing}")
        for first, second in zip(order, order[1:]):
            if self._step_ts[second] < self._step_ts[first]:
                raise AssertionError(
                    f"CHK-NONVAC order fail: {second} stamped at "
                    f"{self._step_ts[second]} ns, before {first} at {self._step_ts[first]} ns"
                )
        advancing = sum(
            1
            for first, second in zip(order, order[1:])
            if self._step_ts[second] > self._step_ts[first]
        )
        span_ns = self._step_ts[order[-1]] - self._step_ts[order[0]]
        if advancing < min_advancing:
            raise AssertionError(
                f"CHK-NONVAC fail: {advancing} of {len(order) - 1} step transitions advanced "
                f"simulation time; minimum is {min_advancing}"
            )
        if span_ns < min_span_ns:
            raise AssertionError(
                f"CHK-NONVAC fail: steps span {span_ns} ns of simulation; "
                f"minimum is {min_span_ns} ns"
            )
        if self._dut_checks < min_checks:
            raise AssertionError(
                f"CHK-NONVAC fail: {self._dut_checks} fail-capable comparisons against "
                f"DUT-sourced samples; minimum is {min_checks}"
            )
        self.log.info(
            "CHK-NONVAC: %d DUT comparisons, %d of %d step transitions advanced simulation "
            "time, span=%d ns over %s",
            self._dut_checks,
            advancing,
            len(order) - 1,
            span_ns,
            "<".join(order),
        )

    async def _count_transitions(self, signals: dict) -> dict:
        """Count level changes on DUT nodes over DOMAIN_WINDOW_NS."""
        last = {name: self._sample(signal, name) for name, signal in signals.items()}
        counts = {name: 0 for name in signals}
        for _ in range(self.DOMAIN_WINDOW_NS // self.DOMAIN_SAMPLE_NS):
            await Timer(self.DOMAIN_SAMPLE_NS, unit="ns")
            for name, signal in signals.items():
                now = self._sample(signal, name)
                if now != last[name]:
                    counts[name] += 1
                    last[name] = now
        return counts

    async def _check_powergood_reached_dut(self) -> None:
        """Drive a power-good deassertion and require the DUT to follow it.

        The three bounded waits are one 1 -> 0 -> 1 transition of the DUT
        synchronizer output around a powergood_i deassertion this sequence
        drives. The leading wait for 1 is what makes the low attributable: the
        bench initializes every node to 0, so a low sampled without a proven
        high ahead of it is the power-up value rather than a response, and the
        sticky obs_powergood_stable_low_seen_o record carries that power-up
        value from time zero. A run in which powergood_i is never deasserted
        expires the middle wait and fails.
        """
        await self.wait_value(
            self.dut.obs_powergood_stable_o,
            1,
            "obs_powergood_stable_o baseline_high",
            self.BOUND_REF_CYCLES,
        )
        self.dut.powergood_i.value = 0
        await self.wait_value(
            self.dut.obs_powergood_stable_o,
            0,
            "obs_powergood_stable_o driven_low",
            self.BOUND_REF_CYCLES,
        )
        self.dut.powergood_i.value = 1
        await self.wait_value(
            self.dut.obs_powergood_stable_o,
            1,
            "obs_powergood_stable_o driven_release",
            self.BOUND_REF_CYCLES,
        )
        low_seen = self._sample(
            self.dut.obs_powergood_stable_low_seen_o, "obs_powergood_stable_low_seen_o"
        )
        self.log.info(
            "CHK-WRAPPER-POWERGOOD: obs_powergood_stable_o 1 -> 0 -> 1 across the "
            "powergood_i deassertion this sequence drove (sticky low_seen=%d, which "
            "also holds the power-up value and is a diagnostic, not a term)",
            low_seen,
        )

    async def _assert_compose_hier_clk_identity(self, dut, samples_per_edge: int = 4) -> dict:
        """Prove SMC/SEP/DTP/xbar instances via hierarchical clk identity.

        Missing elaboration fails as X/Z (allow_xz=False) or as a stuck
        constant that cannot track both edges of clk_smu_i. The hardwired
        obs_compose_*_present_o constants cannot report a missing instance.
        """
        seen_top: set[int] = set()
        mismatches = 0
        last_levels: dict = {}
        for _ in range(samples_per_edge):
            await RisingEdge(dut.clk_smu_i)
            await Timer(1, unit="ns")
            top = self._sample(dut.clk_smu_i, "clk_smu_i")
            seen_top.add(top)
            levels = {
                "top": top,
                "smc": self._sample(dut.obs_smc_clk_o, "obs_smc_clk_o"),
                "sep": self._sample(dut.obs_sep_clk_o, "obs_sep_clk_o"),
                "dtp": self._sample(dut.obs_dtp_clk_o, "obs_dtp_clk_o"),
                "xbar": self._sample(dut.obs_xbar_clk_o, "obs_xbar_clk_o"),
            }
            last_levels = levels
            self._dut_checks += 1
            if not (levels["smc"] == levels["sep"] == levels["dtp"] == levels["xbar"] == top):
                mismatches += 1
            await FallingEdge(dut.clk_smu_i)
            await Timer(1, unit="ns")
            top = self._sample(dut.clk_smu_i, "clk_smu_i")
            seen_top.add(top)
            levels = {
                "top": top,
                "smc": self._sample(dut.obs_smc_clk_o, "obs_smc_clk_o"),
                "sep": self._sample(dut.obs_sep_clk_o, "obs_sep_clk_o"),
                "dtp": self._sample(dut.obs_dtp_clk_o, "obs_dtp_clk_o"),
                "xbar": self._sample(dut.obs_xbar_clk_o, "obs_xbar_clk_o"),
            }
            last_levels = levels
            self._dut_checks += 1
            if not (levels["smc"] == levels["sep"] == levels["dtp"] == levels["xbar"] == top):
                mismatches += 1
        assert mismatches == 0, (
            f"compose hierarchical clk identity fail: mismatches={mismatches} last={last_levels}"
        )
        assert seen_top == {0, 1}, (
            "compose presence needs toggling clk_smu_i (non-constant identity): "
            f"seen_top={sorted(seen_top)}"
        )
        return last_levels

    async def wait_value(self, signal, expected: int, name: str, limit: int = 500) -> int:
        last = None
        for cycle in range(limit):
            await RisingEdge(self.dut.clk_ref_i)
            last = self._sample(signal, name)
            if last == expected:
                self._dut_checks += 1
                self._timeout_paths.append(f"{name}: bound={limit} ok last={last} cycle={cycle}")
                self.log.info("%s reached expected=%d at poll cycle %d", name, expected, cycle)
                return cycle
        self._timeout_paths.append(f"{name}: bound={limit} EXPIRED last={last}")
        raise AssertionError(f"{name} timeout: expected={expected} observed={last} limit={limit}")

    async def _run_smu_all_001(self) -> None:
        """SMU_ALL_001 / smu_wrapper_elaboration_test (SEP=1 only)."""
        dut = self.dut
        self.log.info("=" * 70)
        self.log.info("TEST: SMU_ALL_001 SEP=1 wrapper elaboration (compose/clk/rst)")
        self.log.info("=" * 70)

        # ------------------------------------------------------------------
        # S1 SETUP — clocks stable, out of reset (base_test.bring_up done)
        # ------------------------------------------------------------------
        await self._check_powergood_reached_dut()
        await self.wait_value(dut.rst_cold_n_o, 1, "rst_cold_n_o", self.BOUND_REF_CYCLES)
        sep_en = self._sample(dut.sep_enabled_o, "sep_enabled_o")
        assert sep_en == 1, f"SEP=1 profile required: sep_enabled_o={sep_en}"
        # sep_reset_n_o is the live SEP reset output in this build, so the
        # cold-reset baseline is a DUT-sourced sample here.
        self._check(
            self.test.pre_release_sep_reset == 0,
            "SEP=1 cold-reset must assert sep_reset_n_o: "
            f"observed={self.test.pre_release_sep_reset}",
        )
        self._mark_step(
            "S1",
            "SETUP: clocks stable; obs_powergood_stable_o driven 1->0->1; rst_cold_n_o=1; "
            f"sep_enabled_o=1 baseline cold_sep_reset_n="
            f"{self.test.pre_release_sep_reset}",
        )

        # ------------------------------------------------------------------
        # S2 COMPOSE-BLOCKS.S1 — SMC/SEP/DTP/xbar present under SEP=1
        # ------------------------------------------------------------------
        self._mark_step(
            "S2",
            "ACTION SMU-COMPOSE-BLOCKS.S1: hierarchical compose clk identity",
        )
        # Presence from hierarchical DUT clk observes that track toggling
        # clk_smu_i.
        compose_levels = await self._assert_compose_hier_clk_identity(dut)
        self.log.info(
            "CHK-SMU-COMPOSE-BLOCKS-S1: PASS "
            "(sep=1 blocks=smc+sep+dtp+xbar "
            f"hier_clk_identity={compose_levels})"
        )

        # ------------------------------------------------------------------
        # S3 COMPOSE-BLOCKS.S2 — shared clk_smu_i / rst_primary_smc_clk_no
        # ------------------------------------------------------------------
        self._mark_step(
            "S3",
            "ACTION SMU-COMPOSE-BLOCKS.S2: shared clk_smu / rst_primary domain",
        )
        # Compare after a settle delay: RisingEdge callbacks can sample before
        # continuous XMR assigns to obs_*_clk_o update in the same delta.
        clk_mismatch = 0
        last_levels = {}
        for _ in range(8):
            await RisingEdge(dut.clk_smu_i)
            await Timer(1, unit="ns")
            top_clk = self._sample(dut.clk_smu_i, "clk_smu_i")
            smc_clk = self._sample(dut.obs_smc_clk_o, "obs_smc_clk_o")
            sep_clk = self._sample(dut.obs_sep_clk_o, "obs_sep_clk_o")
            dtp_clk = self._sample(dut.obs_dtp_clk_o, "obs_dtp_clk_o")
            xbar_clk = self._sample(dut.obs_xbar_clk_o, "obs_xbar_clk_o")
            last_levels = {
                "top": top_clk,
                "smc": smc_clk,
                "sep": sep_clk,
                "dtp": dtp_clk,
                "xbar": xbar_clk,
            }
            self._dut_checks += 1
            if not (smc_clk == sep_clk == dtp_clk == xbar_clk == top_clk):
                clk_mismatch += 1
        assert clk_mismatch == 0, (
            "shared clk_smu domain mismatch across settled samples: "
            f"mismatches={clk_mismatch} last={last_levels}"
        )
        await Timer(1, unit="ns")
        prim = self._sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o")
        smc_rst = self._sample(dut.obs_smc_rst_n_o, "obs_smc_rst_n_o")
        sep_rst = self._sample(dut.obs_sep_rst_n_o, "obs_sep_rst_n_o")
        dtp_rst = self._sample(dut.obs_dtp_rst_n_o, "obs_dtp_rst_n_o")
        xbar_rst = self._sample(dut.obs_xbar_rst_n_o, "obs_xbar_rst_n_o")
        self._check(
            smc_rst == sep_rst == dtp_rst == xbar_rst == prim,
            "shared rst_primary_smc_clk_no mismatch: "
            f"prim={prim} smc={smc_rst} sep={sep_rst} dtp={dtp_rst} xbar={xbar_rst}",
        )
        self.log.info(
            "CHK-SMU-COMPOSE-BLOCKS-S2: PASS "
            "(domain=clk_smu rst=rst_primary_smc_clk_no "
            f"clk_last={last_levels} rst={prim})"
        )

        # ------------------------------------------------------------------
        # S4 COMPOSE-BLOCKS.S3 — smu_axi and lifecycle port groups answer;
        # jtag and xtrig are sampled without stimulus and prove nothing here
        # ------------------------------------------------------------------
        self._mark_step(
            "S4",
            "ACTION SMU-COMPOSE-BLOCKS.S3: smu_axi accepts addresses, lifecycle port "
            "carries the SEP export; jtag/xtrig sampled",
        )
        jtag = self._sample(dut.obs_jtag_tdo_o, "obs_jtag_tdo_o")
        xtrig = self._sample(dut.obs_xtrig_src_req0_o, "obs_xtrig_src_req0_o")
        # An inbound AXI subordinate that is composed, clocked and out of reset
        # raises awready; one held in reset or unclocked never does.
        await self.wait_value(
            dut.obs_smu_axi_awready_o,
            1,
            "obs_smu_axi_awready_o",
            self.BOUND_REF_CYCLES,
        )
        axi = self._sample(dut.obs_smu_axi_awready_o, "obs_smu_axi_awready_o")
        sep_lc = self._sample(dut.obs_sep_lc_state_o, "obs_sep_lc_state_o")
        lc = self._sample(dut.lc_state_o, "lc_state_o")
        self._check(
            sep_lc == lc,
            "lifecycle port group: lc_state_o does not carry the SEP LCC export: "
            f"obs_sep_lc_state_o=0x{sep_lc:02x} lc_state_o=0x{lc:02x}",
        )
        self.log.info(
            "port_group sample jtag_tdo=%d axi_awready=%d xtrig0=%d lc_state=0x%02x",
            jtag,
            axi,
            xtrig,
            lc,
        )
        self.log.info(
            "CHK-SMU-COMPOSE-BLOCKS-S3: PASS "
            "(port_group=smu_axi,lifecycle "
            f"axi_awready={axi} sep_lc=0x{sep_lc:02x} lc=0x{lc:02x})"
        )
        self.log.info(
            "CHK-SMU-COMPOSE-BLOCKS-S3: NOT-PROVEN "
            "(port_group=jtag,xtrig sampled_only: this step drives no JTAG or "
            f"cross-trigger stimulus, so jtag_tdo={jtag} xtrig={xtrig} are levels, "
            "not responses)"
        )

        # ------------------------------------------------------------------
        # S5 PORT-CLK-RST.S1 — LIVE cold assert/deassert lifecycle on primary
        # ------------------------------------------------------------------
        self._mark_step(
            "S5",
            "ACTION SMU-PORT-CLK-RST.S1: cold assert/deassert primary-reset lifecycle",
        )
        self.log.info("LIFECYCLE SMU-PORT-CLK-RST.S1 set: assert rst_cold_ni=0")
        dut.rst_cold_ni.value = 0
        await self.wait_value(
            dut.rst_primary_smc_clk_n_o,
            0,
            "rst_primary_smc_clk_n_o",
            self.BOUND_REF_CYCLES,
        )
        cold_obs = self._sample(dut.rst_cold_n_o, "rst_cold_n_o")
        prim_obs = self._sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o")
        self._check(
            cold_obs == 0 and prim_obs == 0,
            f"cold assert observe fail: cold={cold_obs} prim={prim_obs}",
        )
        self.log.info(
            "LIFECYCLE SMU-PORT-CLK-RST.S1 observed: "
            f"rst_cold_n_o={cold_obs} rst_primary_smc_clk_n_o={prim_obs}"
        )

        self.log.info("LIFECYCLE SMU-PORT-CLK-RST.S1 cleared: release rst_cold_ni=1")
        dut.rst_cold_ni.value = 1
        await self.wait_value(
            dut.rst_primary_smc_clk_n_o,
            1,
            "rst_primary_smc_clk_n_o",
            self.BOUND_REF_CYCLES,
        )
        # rst_cold_stable (rst_cold_n_o) can lag primary through the ref-clock sync.
        await self.wait_value(
            dut.rst_cold_n_o,
            1,
            "rst_cold_n_o",
            self.BOUND_REF_CYCLES,
        )
        cold_clr = self._sample(dut.rst_cold_n_o, "rst_cold_n_o")
        prim_clr = self._sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o")
        self._check(
            cold_clr == 1 and prim_clr == 1,
            f"cold release checked_cleared fail: cold={cold_clr} prim={prim_clr}",
        )
        self.log.info(
            "LIFECYCLE SMU-PORT-CLK-RST.S1 checked_cleared: "
            f"rst_cold_n_o={cold_clr} rst_primary_smc_clk_n_o={prim_clr}"
        )
        self.log.info(
            "CHK-SMU-PORT-CLK-RST-S1: PASS "
            "(rst=cold_assert,cold_deassert obs=rst_primary_smc "
            f"assert_prim={prim_obs} release_prim={prim_clr})"
        )

        # ------------------------------------------------------------------
        # S6 PORT-CLK-RST.S3 — telemetry / SEP-WDT domains ≠ clk_smu_i
        # ------------------------------------------------------------------
        self._mark_step(
            "S6",
            "ACTION SMU-PORT-CLK-RST.S3: telemetry and sep_wdt domains vs clk_smu",
        )
        cfg = self.test.cfg
        self.log.info(
            "LIFECYCLE SMU-PORT-CLK-RST.S3 set: observe domain periods "
            f"smu={cfg.smu_clk_period_ns} ref/tel={cfg.ref_clk_period_ns} "
            f"wdt={cfg.sep_wdt_clk_period_ns}"
        )
        # Every domain pair has to differ: an equality observation against one
        # clock cannot tell that clock from another running at the same period
        # and phase.
        domains = (
            ("clk_smu_i", cfg.smu_clk_period_ns),
            ("clk_ref_i/telemetry", cfg.ref_clk_period_ns),
            ("clk_sep_wdt_i", cfg.sep_wdt_clk_period_ns),
        )
        for (left, left_ns), (right, right_ns) in itertools.combinations(domains, 2):
            assert left_ns != right_ns, (
                f"{left} and {right} must run at different periods for domain separation to "
                f"be observable: both {left_ns} ns (seed {self.test.random_seed()})"
            )
        # Observe hierarchical consumers track distinct TB clock inputs.
        await RisingEdge(dut.clk_ref_i)
        await Timer(1, unit="ns")
        tel_hier = self._sample(dut.obs_smc_tel_clk_o, "obs_smc_tel_clk_o")
        ref_now = self._sample(dut.clk_ref_i, "clk_ref_i")
        self._check(
            tel_hier == ref_now,
            f"telemetry consumer not on clk_ref/telemetry: tel={tel_hier} ref={ref_now}",
        )
        await RisingEdge(dut.clk_sep_wdt_i)
        await Timer(1, unit="ns")
        wdt_hier = self._sample(dut.obs_sep_wdt_clk_o, "obs_sep_wdt_clk_o")
        wdt_now = self._sample(dut.clk_sep_wdt_i, "clk_sep_wdt_i")
        self._check(
            wdt_hier == wdt_now,
            f"SEP WDT consumer not on clk_sep_wdt_i: hier={wdt_hier} pin={wdt_now}",
        )
        await RisingEdge(dut.clk_smu_i)
        await Timer(1, unit="ns")
        smu_hier = self._sample(dut.obs_smc_clk_o, "obs_smc_clk_o")
        smu_now = self._sample(dut.clk_smu_i, "clk_smu_i")
        self._check(
            smu_hier == smu_now,
            f"SMC primary clk consumer mismatch: hier={smu_hier} pin={smu_now}",
        )
        # Rate separation at the DUT nodes themselves: a telemetry or WDT
        # consumer wired to the primary domain toggles at the primary rate.
        transitions = await self._count_transitions(
            {
                "obs_smc_tel_clk_o": dut.obs_smc_tel_clk_o,
                "obs_sep_wdt_clk_o": dut.obs_sep_wdt_clk_o,
                "obs_smc_clk_o": dut.obs_smc_clk_o,
            }
        )
        self.log.info(
            "LIFECYCLE SMU-PORT-CLK-RST.S3 transitions over %d ns: %s",
            self.DOMAIN_WINDOW_NS,
            transitions,
        )
        self._check(
            all(count > 0 for count in transitions.values()),
            f"a clock consumer stopped over {self.DOMAIN_WINDOW_NS} ns: {transitions}",
        )
        self._check(
            transitions["obs_smc_tel_clk_o"] != transitions["obs_smc_clk_o"],
            "telemetry consumer toggles at the clk_smu_i rate, so it is not on a separate "
            f"domain: {transitions}",
        )
        self._check(
            transitions["obs_sep_wdt_clk_o"] != transitions["obs_smc_clk_o"],
            "SEP WDT consumer toggles at the clk_smu_i rate, so it is not on a separate "
            f"domain: {transitions}",
        )
        self.log.info(
            "LIFECYCLE SMU-PORT-CLK-RST.S3 observed: "
            f"tel_hier==clk_ref ({tel_hier}) wdt_hier==clk_sep_wdt ({wdt_hier}) "
            f"smc_clk==clk_smu ({smu_hier}); periods distinct "
            f"smu/ref/wdt="
            f"{cfg.smu_clk_period_ns}/{cfg.ref_clk_period_ns}/"
            f"{cfg.sep_wdt_clk_period_ns}"
        )
        # Clear observation window (no stimulus left asserted on clocks).
        await ClockCycles(dut.clk_ref_i, 2)
        await Timer(1, unit="ns")
        self.log.info("LIFECYCLE SMU-PORT-CLK-RST.S3 cleared: observation window closed")
        tel_chk = self._sample(dut.obs_smc_tel_clk_o, "obs_smc_tel_clk_o")
        wdt_chk = self._sample(dut.obs_sep_wdt_clk_o, "obs_sep_wdt_clk_o")
        # checked_cleared: domains remain separately wired after the window.
        self._check(
            tel_chk == self._sample(dut.clk_ref_i, "clk_ref_i"),
            f"telemetry consumer left clk_ref/telemetry after the window: tel={tel_chk}",
        )
        self._check(
            wdt_chk == self._sample(dut.clk_sep_wdt_i, "clk_sep_wdt_i"),
            f"SEP WDT consumer left clk_sep_wdt_i after the window: wdt={wdt_chk}",
        )
        self.log.info(
            "LIFECYCLE SMU-PORT-CLK-RST.S3 checked_cleared: "
            f"tel_hier={tel_chk} wdt_hier={wdt_chk} still on distinct domains"
        )
        self.log.info(
            "CHK-SMU-PORT-CLK-RST-S3: PASS "
            "(clk=telemetry,sep_wdt separate_from clk_smu_i "
            f"smu_ns={cfg.smu_clk_period_ns} tel_ns={cfg.ref_clk_period_ns} "
            f"wdt_ns={cfg.sep_wdt_clk_period_ns} "
            f"transitions_per_{self.DOMAIN_WINDOW_NS}ns={transitions})"
        )

        # ------------------------------------------------------------------
        # S7 SEP-PARAM.S1 — SEP in 3x3 xbar + drives lc_state_o
        # ------------------------------------------------------------------
        self._mark_step(
            "S7",
            "ACTION SMU-SEP-PARAM.S1: SEP xbar present and lc_state_o from SEP",
        )
        assert self._sample(dut.sep_enabled_o, "sep_enabled_o") == 1
        # xbar/SEP presence via hierarchical clk identity.
        xbar_levels = await self._assert_compose_hier_clk_identity(dut, samples_per_edge=2)
        self._check(
            xbar_levels["sep"] == xbar_levels["top"],
            f"SEP clock does not track clk_smu_i: {xbar_levels}",
        )
        self._check(
            xbar_levels["xbar"] == xbar_levels["top"],
            f"xbar clock does not track clk_smu_i: {xbar_levels}",
        )
        # lc_state=from_sep only after the live SEP source equals boundary
        # lc_state_o. SEP eFuse LC_STATE default is 0xF0, so a boundary value of
        # 0xf0 under SEP=1 is expected when the hierarchical SEP export matches.
        sep_lc = self._sample(dut.obs_sep_lc_state_o, "obs_sep_lc_state_o")
        lc_now = self._sample(dut.lc_state_o, "lc_state_o")
        self._check(
            sep_lc == lc_now,
            "lc_state_o not driven by SEP hierarchical source: "
            f"obs_sep_lc_state_o=0x{sep_lc:02x} lc_state_o=0x{lc_now:02x}",
        )
        self.log.info(
            "CHK-SMU-SEP-PARAM-S1: PASS "
            f"(sep=1 xbar=present lc_state=from_sep "
            f"sep_lc=0x{sep_lc:02x} lc_state_o=0x{lc_now:02x} match=1 "
            f"hier_clk={xbar_levels})"
        )

        # ------------------------------------------------------------------
        # S8 TIMEOUT contract
        # ------------------------------------------------------------------
        self._mark_step(
            "S8",
            "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last-state",
        )
        for line in self._timeout_paths:
            self.log.info("TIMEOUT-PATH %s", line)
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS_SEP1:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS_SEP1}"
            )
        for i, line in enumerate(self._timeout_paths):
            if "bound=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing finite bound field: {line}")
            if "ok last=" not in line and "EXPIRED last=" not in line:
                raise AssertionError(
                    f"CHK-TIMEOUT-PATHS[{i}] missing last-state diagnostic: {line}"
                )
        self.log.info(
            "CHK-TIMEOUT-PATHS: Finite bound on S8; expiry fails with last-state "
            f"diagnostics (paths={n_paths} bound={self.BOUND_REF_CYCLES})"
        )

        self._step_ts["PASS"] = get_sim_time("ns")
        self.log.info("PASS term recorded for NONVAC fence")

        self._assert_nonvac_fence(
            ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "PASS"],
            self.MIN_DUT_CHECKS_SEP1,
            self.MIN_ADVANCING_STEPS_SEP1,
            self.MIN_SPAN_NS_SEP1,
        )

    async def run(self) -> None:
        expected_sep_arg = cocotb.plusargs.get("expected_sep")
        assert expected_sep_arg is not None, "missing required +expected_sep profile contract"
        expected_sep = int(expected_sep_arg, 0)
        # The wrapper has a single compile profile and it elaborates SEP, so
        # this is a contract check rather than a branch: a SEP=0 build of this
        # bench no longer exists, and the SEP=0 composition is proved on
        # --dut smu_block (the `nosep` group of testlists/block.toml).
        assert expected_sep == 1, (
            f"+expected_sep={expected_sep} on the wrapper: the only profile is "
            "compile_smu_chiplet, which elaborates SEP=1"
        )
        await self._run_smu_all_001()
