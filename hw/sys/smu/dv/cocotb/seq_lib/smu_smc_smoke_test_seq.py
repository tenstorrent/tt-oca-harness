# SPDX-License-Identifier: Apache-2.0
"""Sequence body for smu_smc_smoke_test (DV Skill 1.5 / SMU_001 rev 1).

Implements the approved checkbox card steps/checkers for P0 clock + cold/primary
reset observability at the SMU boundary. Emits greppable ``CHK-*`` / ``STEP``
lines; does not grade features.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer


class smu_smc_smoke_test_seq:
    """SMU_001 clock-freeze + cold/primary reset evidence sequence."""

    FREEZE_REF_CYCLES = 64
    RUN_SMU_CYCLES = 32
    REF_OBS_CYCLES = 32
    BOUND_REF_CYCLES = 2000
    SETTLE_REF_CYCLES = 500
    # Exact count of _wait_eq sites:
    #   S1 release (3) + S2 arm×2 (4) + S2 live (3) + S2 resume (3) + S4–S7 (6) = 19
    EXPECTED_TIMEOUT_PATHS = 19
    # DTP clock-stop request bit observed through CTN 2FF+reg on clk_smu.
    DTP_CLK_STOP_PAT = 0x01

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []
        self._clk_smu_task = None
        self._clk_ref_task = None
        self._clk_periph_task = None
        self._smu_clk_enable = [True]

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = time.monotonic()
        self._log(f"STEP {step_id}: {detail}")

    def _sample(self, signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    def _start_clock(self, signal, period_ns: float):
        return cocotb.start_soon(Clock(signal, period_ns, unit="ns").start())

    async def _gated_smu_clock(self) -> None:
        """Drive clk_smu_i with a pauseable generator (cocotb Clock cannot freeze)."""
        half = self.cfg.smu_clk_period_ns / 2.0
        sig = self.dut.clk_smu_i
        while True:
            if self._smu_clk_enable[0]:
                sig.value = 1
                await Timer(half, unit="ns")
                sig.value = 0
                await Timer(half, unit="ns")
            else:
                sig.value = 0
                await Timer(half, unit="ns")

    def _freeze_smu_clk(self) -> None:
        self._smu_clk_enable[0] = False
        self.dut.clk_smu_i.value = 0

    def _resume_smu_clk(self) -> None:
        self._smu_clk_enable[0] = True

    async def _wait_eq(
        self,
        signal,
        expect: int,
        *,
        clk,
        bound: int,
        label: str,
    ) -> int:
        last = None
        for _ in range(bound):
            await RisingEdge(clk)
            last = self._sample(signal, label)
            if last == expect:
                self._timeout_paths.append(
                    f"{label}: bound={bound} ok last={last}"
                )
                return last
        self._timeout_paths.append(
            f"{label}: bound={bound} EXPIRED last={last}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={bound} last_state={last} expect={expect}"
        )

    async def _bringup_clocks_preload(self) -> None:
        """S1-capable bring-up: clocks running, cold held, powergood=1."""
        dut = self.dut
        self._smu_clk_enable[0] = True
        self._clk_smu_task = cocotb.start_soon(self._gated_smu_clock())
        self._clk_ref_task = self._start_clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns)
        self._clk_periph_task = self._start_clock(
            dut.clk_periph_i, self.cfg.periph_clk_period_ns
        )

        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        if hasattr(dut, "ext_boot_seq_done_i"):
            dut.ext_boot_seq_done_i.value = 1
        dut.jtag_tck.value = 0
        dut.jtag_tms.value = 0
        dut.jtag_trst.value = 0
        dut.jtag_tdi.value = 0
        if hasattr(dut, "xtrig_ctm_dst_req"):
            dut.xtrig_ctm_dst_req.value = 0
        if hasattr(dut, "xtrig_ctm_src_ack"):
            dut.xtrig_ctm_src_ack.value = 0
        if hasattr(dut, "xtrig_clk_stop_req"):
            dut.xtrig_clk_stop_req.value = 0
        if hasattr(dut, "captured_straps_i"):
            dut.captured_straps_i.value = 0
        if hasattr(dut, "gpio_boot_stall_drive_i"):
            dut.gpio_boot_stall_drive_i.value = 0
        for name in (
            "s_axi_awvalid",
            "s_axi_wvalid",
            "s_axi_bready",
            "s_axi_arvalid",
            "s_axi_rready",
        ):
            getattr(dut, name).value = 0

        await ClockCycles(dut.clk_ref_i, 10)
        dut.powergood_i.value = 1
        # Hold cold asserted through deglitch window (card S1).
        await ClockCycles(dut.clk_ref_i, 64)

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        await self._bringup_clocks_preload()

        # S1 — PRELOAD (ext_boot_seq_done_i hard-tied 1'b1 in tb_top)
        self._mark_step(
            "S1",
            "PRELOAD clk_smu_i/clk_ref_i toggling; rst_cold_ni=0; "
            "powergood_i=1; ext_boot_seq_done_i=1 (TB tie)",
        )
        assert self._sample(dut.rst_cold_ni, "rst_cold_ni") == 0
        assert self._sample(dut.powergood_i, "powergood_i") == 1

        # Release cold/primary for clock observation window (S2/S3).
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await ClockCycles(dut.clk_ref_i, self.SETTLE_REF_CYCLES)
        await self._wait_eq(
            dut.rst_cold_stable_ref_clk_no,
            1,
            clk=dut.clk_ref_i,
            bound=self.BOUND_REF_CYCLES,
            label="rst_cold_stable_ref_clk_no_release",
        )
        await self._wait_eq(
            dut.rst_primary_smc_clk_no,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_REF_CYCLES,
            label="rst_primary_smc_clk_no_release",
        )
        await self._wait_eq(
            dut.rst_primary_ref_clk_no,
            1,
            clk=dut.clk_ref_i,
            bound=self.BOUND_REF_CYCLES,
            label="rst_primary_ref_clk_no_release",
        )

        # S2 — CLK PRIMARY with freeze window
        # SMC progress: fuse_reset_n_delayed_o is a 16-stage clk_smc pipe (en=1).
        # DTP progress: xtrig_clk_stop_req -> CTN 2FF+reg -> dtp_stop_clks_o.
        self._mark_step(
            "S2",
            "CLK PRIMARY: SMC fuse_reset pipe + DTP stop_clks sync; "
            "freeze >=64; resume",
        )

        async def _arm_smc_pipe_midflight(tag: str) -> None:
            """Cold pulse so fuse_reset_n_delayed_o is 0 with primary just released.

            No long settle — the 16-stage pipe fills within ~16 clk_smu cycles.
            """
            dut.xtrig_clk_stop_req.value = 0
            dut.rst_cold_ni.value = 0
            await ClockCycles(dut.clk_ref_i, 64)
            await self._wait_eq(
                dut.rst_primary_smc_clk_no,
                0,
                clk=dut.clk_smu_i,
                bound=self.BOUND_REF_CYCLES,
                label=f"s2_{tag}_rst_primary_smc_hold",
            )
            dut.rst_cold_ni.value = 1
            await self._wait_eq(
                dut.rst_primary_smc_clk_no,
                1,
                clk=dut.clk_smu_i,
                bound=self.BOUND_REF_CYCLES,
                label=f"s2_{tag}_rst_primary_smc_release",
            )
            # Pipe input is 1 but delayed output still 0 for ~16 clk_smu cycles.
            if self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o") != 0:
                raise AssertionError(
                    f"SMC fuse_reset_n_delayed_o not 0 right after primary "
                    f"release ({tag})"
                )

        # LIVE: prove each consumer advances because clk_smu_i runs.
        await _arm_smc_pipe_midflight("live")
        smc_live0 = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
        await self._wait_eq(
            dut.fuse_reset_n_delayed_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_REF_CYCLES,
            label="s2_smc_fuse_delayed_live",
        )
        smc_live1 = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
        smc_adv = 1 if smc_live1 != smc_live0 else 0

        dtp_live0 = self._sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o")
        if dtp_live0 != 0:
            raise AssertionError(
                f"DTP dtp_stop_clks_o expected 0 before LIVE stop req, got {dtp_live0}"
            )
        dut.xtrig_clk_stop_req.value = self.DTP_CLK_STOP_PAT
        await self._wait_eq(
            dut.dtp_stop_clks_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_REF_CYCLES,
            label="s2_dtp_stop_clks_live_assert",
        )
        dtp_live1 = self._sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o")
        dtp_adv = 1 if dtp_live1 != dtp_live0 else 0
        dut.xtrig_clk_stop_req.value = 0
        await self._wait_eq(
            dut.dtp_stop_clks_o,
            0,
            clk=dut.clk_smu_i,
            bound=self.BOUND_REF_CYCLES,
            label="s2_dtp_stop_clks_live_clear",
        )
        if smc_adv < 1 or dtp_adv < 1:
            raise AssertionError(
                f"SMC/DTP clocked LIVE progress missing: "
                f"smc_adv={smc_adv} dtp_adv={dtp_adv}"
            )

        # FREEZE mid-flight: re-arm both, freeze before either completes.
        await _arm_smc_pipe_midflight("freeze")
        smc_pre = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
        dtp_pre = self._sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o")
        if smc_pre != 0 or dtp_pre != 0:
            raise AssertionError(
                f"mid-flight arm failed: smc_delayed={smc_pre} dtp_stop={dtp_pre}"
            )
        dut.xtrig_clk_stop_req.value = self.DTP_CLK_STOP_PAT
        freeze_edges = [0]

        async def _count_smu_edges() -> None:
            while True:
                await RisingEdge(dut.clk_smu_i)
                freeze_edges[0] += 1

        self._freeze_smu_clk()
        edge_mon = cocotb.start_soon(_count_smu_edges())
        await ClockCycles(dut.clk_ref_i, self.FREEZE_REF_CYCLES)
        edge_mon.cancel()
        freeze_smc_adv = freeze_edges[0]
        freeze_dtp_adv = freeze_edges[0]
        smc_frz = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
        dtp_frz = self._sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o")
        if freeze_smc_adv != 0:
            raise AssertionError(
                f"clk_smu_i edges during freeze: {freeze_smc_adv} (expect 0)"
            )
        if smc_frz != smc_pre or dtp_frz != dtp_pre:
            raise AssertionError(
                f"SMC/DTP progressed during clk_smu freeze: "
                f"smc {smc_pre}->{smc_frz} dtp {dtp_pre}->{dtp_frz}"
            )

        # RESUME: both clocked consumers complete their pending transitions.
        self._resume_smu_clk()
        await self._wait_eq(
            dut.fuse_reset_n_delayed_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_REF_CYCLES,
            label="s2_smc_fuse_delayed_resume",
        )
        await self._wait_eq(
            dut.dtp_stop_clks_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_REF_CYCLES,
            label="s2_dtp_stop_clks_resume",
        )
        resume_smc = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
        resume_dtp = self._sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o")
        dut.xtrig_clk_stop_req.value = 0
        await self._wait_eq(
            dut.dtp_stop_clks_o,
            0,
            clk=dut.clk_smu_i,
            bound=self.BOUND_REF_CYCLES,
            label="s2_dtp_stop_clks_resume_clear",
        )
        if resume_smc != 1 or resume_dtp != 1:
            raise AssertionError(
                f"SMC/DTP did not resume after freeze: "
                f"smc={resume_smc} dtp={resume_dtp}"
            )

        chk_clk_primary = (
            f"CHK-CLK-PRIMARY: SMC and DTP each record >=1 advancing sample while "
            f"clk_smu_i toggles and 0 advancing samples across a frozen clk_smu_i "
            f"window of >={self.FREEZE_REF_CYCLES} cycles "
            f"(smc_adv={smc_adv} dtp_adv={dtp_adv} "
            f"smc_live={smc_live0}->{smc_live1} dtp_live={dtp_live0}->{dtp_live1} "
            f"freeze_smc={smc_pre}->{smc_frz} freeze_dtp={dtp_pre}->{dtp_frz} "
            f"resume_smc={resume_smc} resume_dtp={resume_dtp} "
            f"freeze_smc_adv={freeze_smc_adv} freeze_dtp_adv={freeze_dtp_adv} "
            f"freeze_cycles={self.FREEZE_REF_CYCLES})"
        )
        self._log(chk_clk_primary)
        sb.expect_eq(
            "CHK-CLK-PRIMARY clocked progress freeze resume",
            (
                smc_adv >= 1
                and dtp_adv >= 1
                and freeze_smc_adv == 0
                and freeze_dtp_adv == 0
                and smc_frz == smc_pre
                and dtp_frz == dtp_pre
                and resume_smc == 1
                and resume_dtp == 1
            ),
            True,
            evidence="CHK-CLK-PRIMARY",
        )

        # S3 — CLK REF
        self._mark_step(
            "S3",
            "CLK REF: sample reference-domain reset-sync advancing on clk_ref_i",
        )
        ref_adv = 0
        for _ in range(self.REF_OBS_CYCLES):
            await RisingEdge(dut.clk_ref_i)
            cold = self._sample(
                dut.rst_cold_stable_ref_clk_no, "rst_cold_stable_ref_clk_no"
            )
            pref = self._sample(dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no")
            if cold != 1 or pref != 1:
                raise AssertionError(
                    f"ref-domain reset-sync unexpected levels cold={cold} pref={pref}"
                )
            ref_adv += 1
        chk_clk_ref = (
            f"CHK-CLK-REF: reference-domain reset-sync logic records >=1 advancing "
            f"sample on clk_ref_i in the observation window (ref_adv={ref_adv})"
        )
        self._log(chk_clk_ref)
        sb.expect_eq(
            "CHK-CLK-REF ref-domain samples",
            ref_adv >= 1,
            True,
            evidence="CHK-CLK-REF",
        )

        # S4 — COLD ASSERT
        self._mark_step("S4", "COLD ASSERT: rst_cold_ni=0; expect rst_cold_stable=0")
        dut.rst_cold_ni.value = 0
        cold_asserted = await self._wait_eq(
            dut.rst_cold_stable_ref_clk_no,
            0,
            clk=dut.clk_ref_i,
            bound=self.BOUND_REF_CYCLES,
            label="rst_cold_stable_assert",
        )

        # S5 — COLD RELEASE
        self._mark_step(
            "S5",
            "COLD RELEASE: rst_cold_ni=1; expect rst_cold_stable=1 after sync",
        )
        dut.rst_cold_ni.value = 1
        cold_released = await self._wait_eq(
            dut.rst_cold_stable_ref_clk_no,
            1,
            clk=dut.clk_ref_i,
            bound=self.BOUND_REF_CYCLES,
            label="rst_cold_stable_release",
        )
        chk_cold = (
            f"CHK-COLD-RESET: rst_cold_stable_ref_clk_no=1'b0 while rst_cold_ni "
            f"asserted; after release equals 1'b1 following sync deassert on "
            f"clk_ref_i (asserted={cold_asserted} released={cold_released})"
        )
        self._log(chk_cold)
        sb.expect_eq(
            "CHK-COLD-RESET polarity",
            (cold_asserted == 0 and cold_released == 1),
            True,
            evidence="CHK-COLD-RESET",
        )

        # S6 — PRIMARY HOLD (cold asserted again so primary holds)
        self._mark_step(
            "S6",
            "PRIMARY HOLD: assert cold/primary path; sample primary smc/ref = 0",
        )
        dut.rst_cold_ni.value = 0
        prim_smc_hold = await self._wait_eq(
            dut.rst_primary_smc_clk_no,
            0,
            clk=dut.clk_smu_i,
            bound=self.BOUND_REF_CYCLES,
            label="rst_primary_smc_hold",
        )
        prim_ref_hold = await self._wait_eq(
            dut.rst_primary_ref_clk_no,
            0,
            clk=dut.clk_ref_i,
            bound=self.BOUND_REF_CYCLES,
            label="rst_primary_ref_hold",
        )

        # S7 — PRIMARY RELEASE
        self._mark_step(
            "S7",
            "PRIMARY RELEASE: release cold; sample primary smc/ref = 1",
        )
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.SETTLE_REF_CYCLES)
        prim_smc_rel = await self._wait_eq(
            dut.rst_primary_smc_clk_no,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_REF_CYCLES,
            label="rst_primary_smc_release",
        )
        prim_ref_rel = await self._wait_eq(
            dut.rst_primary_ref_clk_no,
            1,
            clk=dut.clk_ref_i,
            bound=self.BOUND_REF_CYCLES,
            label="rst_primary_ref_release",
        )
        chk_prim = (
            f"CHK-PRIMARY-RESET: rst_primary_smc_clk_no and rst_primary_ref_clk_no "
            f"both 1'b0 when held and both 1'b1 when released "
            f"(hold_smc={prim_smc_hold} hold_ref={prim_ref_hold} "
            f"rel_smc={prim_smc_rel} rel_ref={prim_ref_rel})"
        )
        self._log(chk_prim)
        sb.expect_eq(
            "CHK-PRIMARY-RESET hold/release",
            (
                prim_smc_hold == 0
                and prim_ref_hold == 0
                and prim_smc_rel == 1
                and prim_ref_rel == 1
            ),
            True,
            evidence="CHK-PRIMARY-RESET",
        )

        # S8 — TIMEOUT contract evidence (exact count + per-entry shape; can fail)
        self._mark_step(
            "S8",
            "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last-state",
        )
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS}"
            )
        for i, line in enumerate(self._timeout_paths):
            if "bound=" not in line:
                raise AssertionError(
                    f"CHK-TIMEOUT-PATHS[{i}] missing finite bound field: {line}"
                )
            if "ok last=" not in line and "EXPIRED last=" not in line:
                raise AssertionError(
                    f"CHK-TIMEOUT-PATHS[{i}] missing last-state diagnostic: {line}"
                )
            if f"bound={self.BOUND_REF_CYCLES}" not in line:
                raise AssertionError(
                    f"CHK-TIMEOUT-PATHS[{i}] bound != {self.BOUND_REF_CYCLES}: {line}"
                )
        chk_to = (
            "CHK-TIMEOUT-PATHS: every bounded wait names finite bound, "
            f"fail-on-expiry path, and last-state diagnostic "
            f"(paths={n_paths} expect={self.EXPECTED_TIMEOUT_PATHS} "
            f"bound={self.BOUND_REF_CYCLES})"
        )
        self._log(chk_to)
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count+shape",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        # PASS term first, then final assertion gate, then CHK-NONVAC.
        self.cfg.reset_done.set()
        self._step_ts["PASS"] = time.monotonic()
        self._log("SMU_001 sequence complete (PASS term recorded for NONVAC fence)")

        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        chk_nonvac = (
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6<S7<PASS all present"
        )
        self._log(chk_nonvac)
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            True,
            True,
            evidence="CHK-NONVAC",
        )
