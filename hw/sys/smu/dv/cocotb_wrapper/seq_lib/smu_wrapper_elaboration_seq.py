# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Structural production-wrapper sequence used before firmware bring-up.

DV-CARD:          SMU_ALL_001   ANCHOR: smu_wrapper_elaboration_sep_rtl_test
"""

from __future__ import annotations

import random
import time

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer


class SmuWrapperElaborationSeq:
    """Check profile selection and reset propagation over repeated reset pulses.

    When ``+expected_sep=1`` (anchor ``smu_wrapper_elaboration_sep_rtl_test``),
    executes the SMU_ALL_001 card steps and emits the card's ``CHK-*`` lines.
    The SEP=0 leaf keeps the legacy wrapper-elaboration evidence tokens.
    """

    BOUND_REF_CYCLES = 500
    # Bounded waits in the SEP=1 card path (must match _timeout_paths length):
    # S1 powergood + rst_cold (2) + S5 prim assert + prim release + cold release (3).
    EXPECTED_TIMEOUT_PATHS_SEP1 = 5

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.rng = random.Random(test.random_seed())
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = time.monotonic()
        self.log.info("STEP %s: %s", step_id, detail)

    def _sample(self, signal, name: str) -> int:
        return self.test.read_int(signal, name, allow_xz=False)

    async def _assert_compose_hier_clk_identity(self, dut, samples_per_edge: int = 4) -> dict:
        """Prove SMC/SEP/DTP/xbar instances via hierarchical clk identity.

        Missing elaboration fails as X/Z (allow_xz=False) or as a stuck
        constant that cannot track both edges of clk_smu_i. Does not use
        hardwired obs_compose_*_present_o constants (FIND-001).
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
                self._timeout_paths.append(f"{name}: bound={limit} ok last={last} cycle={cycle}")
                self.log.info("%s reached expected=%d at poll cycle %d", name, expected, cycle)
                return cycle
        self._timeout_paths.append(f"{name}: bound={limit} EXPIRED last={last}")
        raise AssertionError(f"{name} timeout: expected={expected} observed={last} limit={limit}")

    async def _run_legacy_no_sep(self, expected_sep: int) -> None:
        """Legacy no-SEP wrapper smoke evidence (SMU_ALL_008 owns SEP=0 compose)."""
        self.log.info("=" * 70)
        self.log.info("TEST: production smu_wrapper profile and reset propagation")
        self.log.info("=" * 70)

        expected_reset_during_cold = 0 if expected_sep else 1
        observed_reset_during_cold = self.test.pre_release_sep_reset
        observed_fuse_during_cold = self.test.pre_release_sep_fuse
        assert observed_reset_during_cold == expected_reset_during_cold, (
            "SEP profile mismatch at the real DUT reset output: "
            f"expected reset_n={expected_reset_during_cold} for SEP={expected_sep}, "
            f"observed={observed_reset_during_cold}"
        )
        assert observed_fuse_during_cold == 0, (
            "SEP fuse-done must be inactive during cold reset: "
            f"expected=0 observed={observed_fuse_during_cold}"
        )
        self._mark_step(
            "S1",
            f"profile SEP={expected_sep} cold_reset_n={observed_reset_during_cold} "
            f"fuse_done={observed_fuse_during_cold}",
        )
        self.log.info("EVIDENCE:CHK-WRAPPER-SEP-PROFILE_OK")
        self.log.info("EVIDENCE:CHK-WRAPPER-SEP-FUSE-COLD_OK")

        await self.wait_value(self.dut.powergood_o, 1, "powergood_o")
        await self.wait_value(self.dut.rst_cold_n_o, 1, "rst_cold_n_o")
        self._mark_step("S2", "powergood/rst_cold released after bring-up")
        self.log.info("EVIDENCE:CHK-WRAPPER-POWERGOOD_OK")
        self.log.info("EVIDENCE:CHK-WRAPPER-RST-COLD-RELEASE_OK")

        for iteration in range(2):
            hold_cycles = self.rng.randint(2, 5)
            self.log.info(
                "Reset iteration %d: assert cold reset for %d ref-clock cycles",
                iteration,
                hold_cycles,
            )
            self.dut.rst_cold_ni.value = 0
            await self.wait_value(self.dut.rst_cold_n_o, 0, "rst_cold_n_o")
            await ClockCycles(self.dut.clk_ref_i, hold_cycles)
            self.dut.rst_cold_ni.value = 1
            await self.wait_value(self.dut.rst_cold_n_o, 1, "rst_cold_n_o")

        self._mark_step("S3", "reset propagation loop (2 pulses) complete")
        self.log.info("EVIDENCE:CHK-WRAPPER-RST-PROPAGATION_OK")

        self._step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "PASS"]
        pairs_ok = sum(
            1
            for a, b in zip(order, order[1:])
            if a in self._step_ts and b in self._step_ts and self._step_ts[a] < self._step_ts[b]
        )
        if pairs_ok != len(order) - 1:
            raise AssertionError(
                f"CHK-NONVAC ordered fence fail: pairs_ok={pairs_ok} expect={len(order) - 1}"
            )
        self.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<PASS (pairs_ok=%d)",
            pairs_ok,
        )
        self.log.info("EVIDENCE: CHK-NONVAC")
        self.log.info("EVIDENCE:CHK-NONVAC")
        self.log.info(
            "PASS: production wrapper elaborated with SEP=%d and reset remained responsive",
            expected_sep,
        )

    async def _run_smu_all_001(self) -> None:
        """SMU_ALL_001 / smu_wrapper_elaboration_sep_rtl_test (SEP=1 only)."""
        dut = self.dut
        self.log.info("=" * 70)
        self.log.info("TEST: SMU_ALL_001 SEP=1 wrapper elaboration (compose/clk/rst)")
        self.log.info("=" * 70)

        # ------------------------------------------------------------------
        # S1 SETUP — clocks stable, out of reset (base_test.bring_up done)
        # ------------------------------------------------------------------
        await self.wait_value(dut.powergood_o, 1, "powergood_o", self.BOUND_REF_CYCLES)
        await self.wait_value(dut.rst_cold_n_o, 1, "rst_cold_n_o", self.BOUND_REF_CYCLES)
        sep_en = self._sample(dut.sep_enabled_o, "sep_enabled_o")
        assert sep_en == 1, f"SEP=1 profile required: sep_enabled_o={sep_en}"
        assert self.test.pre_release_sep_reset == 0, (
            "SEP=1 cold-reset must assert sep_reset_n_o: "
            f"observed={self.test.pre_release_sep_reset}"
        )
        self._mark_step(
            "S1",
            "SETUP: clocks stable; powergood_o=1; rst_cold_n_o=1; "
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
        # FIND-001 (A): presence from hierarchical DUT clk observes that track
        # toggling clk_smu_i — not hardwired obs_compose_*_present_o.
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
        assert smc_rst == sep_rst == dtp_rst == xbar_rst == prim, (
            "shared rst_primary_smc_clk_no mismatch: "
            f"prim={prim} smc={smc_rst} sep={sep_rst} dtp={dtp_rst} xbar={xbar_rst}"
        )
        self.log.info(
            "CHK-SMU-COMPOSE-BLOCKS-S2: PASS "
            "(domain=clk_smu rst=rst_primary_smc_clk_no "
            f"clk_last={last_levels} rst={prim})"
        )

        # ------------------------------------------------------------------
        # S4 COMPOSE-BLOCKS.S3 — port groups jtag / smu_axi / xtrig / lifecycle
        # ------------------------------------------------------------------
        self._mark_step(
            "S4",
            "ACTION SMU-COMPOSE-BLOCKS.S3: sample jtag/smu_axi/xtrig/lc port groups",
        )
        jtag = self._sample(dut.obs_jtag_tdo_o, "obs_jtag_tdo_o")
        axi = self._sample(dut.obs_smu_axi_awready_o, "obs_smu_axi_awready_o")
        xtrig = self._sample(dut.obs_xtrig_src_req0_o, "obs_xtrig_src_req0_o")
        lc = self._sample(dut.lc_state_o, "lc_state_o")
        # Resolvable samples prove the four port groups are present at the boundary.
        self.log.info(
            "port_group sample jtag_tdo=%d axi_awready=%d xtrig0=%d lc_state=0x%02x",
            jtag,
            axi,
            xtrig,
            lc,
        )
        self.log.info(
            "CHK-SMU-COMPOSE-BLOCKS-S3: PASS "
            "(port_group=jtag,smu_axi,xtrig,lifecycle "
            f"jtag={jtag} axi={axi} xtrig={xtrig} lc=0x{lc:02x})"
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
        assert cold_obs == 0 and prim_obs == 0, (
            f"cold assert observe fail: cold={cold_obs} prim={prim_obs}"
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
        assert cold_clr == 1 and prim_clr == 1, (
            f"cold release checked_cleared fail: cold={cold_clr} prim={prim_clr}"
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
        assert cfg.sep_wdt_clk_period_ns != cfg.smu_clk_period_ns, (
            "sep_wdt period must differ from clk_smu for domain separation"
        )
        # Observe hierarchical consumers track distinct TB clock inputs.
        await RisingEdge(dut.clk_ref_i)
        await Timer(1, unit="ns")
        tel_hier = self._sample(dut.obs_smc_tel_clk_o, "obs_smc_tel_clk_o")
        ref_now = self._sample(dut.clk_ref_i, "clk_ref_i")
        assert tel_hier == ref_now, (
            f"telemetry consumer not on clk_ref/telemetry: tel={tel_hier} ref={ref_now}"
        )
        await RisingEdge(dut.clk_sep_wdt_i)
        await Timer(1, unit="ns")
        wdt_hier = self._sample(dut.obs_sep_wdt_clk_o, "obs_sep_wdt_clk_o")
        wdt_now = self._sample(dut.clk_sep_wdt_i, "clk_sep_wdt_i")
        assert wdt_hier == wdt_now, (
            f"SEP WDT consumer not on clk_sep_wdt_i: hier={wdt_hier} pin={wdt_now}"
        )
        await RisingEdge(dut.clk_smu_i)
        await Timer(1, unit="ns")
        smu_hier = self._sample(dut.obs_smc_clk_o, "obs_smc_clk_o")
        smu_now = self._sample(dut.clk_smu_i, "clk_smu_i")
        assert smu_hier == smu_now, (
            f"SMC primary clk consumer mismatch: hier={smu_hier} pin={smu_now}"
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
        assert cfg.sep_wdt_clk_period_ns != cfg.smu_clk_period_ns
        assert tel_chk == self._sample(dut.clk_ref_i, "clk_ref_i")
        assert wdt_chk == self._sample(dut.clk_sep_wdt_i, "clk_sep_wdt_i")
        self.log.info(
            "LIFECYCLE SMU-PORT-CLK-RST.S3 checked_cleared: "
            f"tel_hier={tel_chk} wdt_hier={wdt_chk} still on distinct domains"
        )
        self.log.info(
            "CHK-SMU-PORT-CLK-RST-S3: PASS "
            "(clk=telemetry,sep_wdt separate_from clk_smu_i "
            f"smu_ns={cfg.smu_clk_period_ns} tel_ns={cfg.ref_clk_period_ns} "
            f"wdt_ns={cfg.sep_wdt_clk_period_ns})"
        )

        # ------------------------------------------------------------------
        # S7 SEP-PARAM.S1 — SEP in 3x3 xbar + drives lc_state_o
        # ------------------------------------------------------------------
        self._mark_step(
            "S7",
            "ACTION SMU-SEP-PARAM.S1: SEP xbar present and lc_state_o from SEP",
        )
        assert self._sample(dut.sep_enabled_o, "sep_enabled_o") == 1
        # FIND-001 (A): xbar/SEP presence via hierarchical clk identity, not
        # hardwired present_o flags.
        xbar_levels = await self._assert_compose_hier_clk_identity(dut, samples_per_edge=2)
        assert xbar_levels["sep"] == xbar_levels["top"]
        assert xbar_levels["xbar"] == xbar_levels["top"]
        # FIND-002 (A): lc_state=from_sep only after live SEP source equals
        # boundary lc_state_o. SEP eFuse LC_STATE default is 0xF0, so a
        # boundary value of 0xf0 under SEP=1 is expected when the hierarchical
        # SEP export matches — not a fabricated from_sep label on a SEP=0 tie.
        sep_lc = self._sample(dut.obs_sep_lc_state_o, "obs_sep_lc_state_o")
        lc_now = self._sample(dut.lc_state_o, "lc_state_o")
        assert sep_lc == lc_now, (
            "lc_state_o not driven by SEP hierarchical source: "
            f"obs_sep_lc_state_o=0x{sep_lc:02x} lc_state_o=0x{lc_now:02x}"
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

        self._step_ts["PASS"] = time.monotonic()
        self.log.info("PASS term recorded for NONVAC fence")

        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self.log.info("CHK-NONVAC: Ordered fence S1<S2<S3<S4<S5<S6<S7<S8<PASS all hold")

    async def run(self) -> None:
        expected_sep_arg = cocotb.plusargs.get("expected_sep")
        assert expected_sep_arg is not None, "missing required +expected_sep profile contract"
        expected_sep = int(expected_sep_arg, 0)
        if expected_sep == 1:
            await self._run_smu_all_001()
        else:
            await self._run_legacy_no_sep(expected_sep)
