# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_clock_stop_coordination_test (SMU_ALL_006).

DV-CARD:          SMU_ALL_006   ANCHOR: smu_clock_stop_coordination_test

Allocated (wrapper):
  DTP-BOOT-STALL.S1 / S2
  DTP-IC-RESET.S1 / S3
  DTP-CLKSTOP-AGG.S1 / S2 / S3
No Force/deposit. DTP-FEAT-GATE.* and INT-FEAT-CTRL-DTP-GATE are out of scope for this card.

The SMC eFuse sense runs for real on the wrapper. BOOT-STALL.S1 samples the
held fuse_reset only after smc_fuse_sense_done_o has risen for the cold reset,
and BOOT-STALL.S2 bounds the release by the gate path, not the sense latency.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_fuse_gate_helpers import (
    FUSE_GATE_HOLD_CYCLES,
    FUSE_GATE_RELEASE_BOUND_CYCLES,
    FUSE_SENSE_BOUND_CYCLES,
    assert_hold_window_covers,
)
from seq_lib.smu_jtag_helpers import (
    DBG_CLA_CLOCK_STOP_BIT,
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_SMC_COLD_PORT,
    make_smu_jtag_tap,
    pack_debug_control,
    pack_ic_reset_ports,
)
from seq_lib.smu_tb_pins import smc_primary_reset, smu_scope


class smu_clock_stop_coordination_test_seq:
    """SMU_ALL_006: boot-stall / IC-RESET / clkstop aggregation."""

    BOUND_CYCLES = 2000
    BOUND_REF = 2000
    SETTLE = 8
    TRST_CYCLES = 8

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []
        self._lifecycle: dict[str, dict[str, float]] = {}
        # Fence granularity: one SMU clock period of simulated time. Every step
        # and every set->observed pair below spans at least one clk_smu_i edge,
        # so a run whose simulation time did not advance fails the fence.
        self.min_sim_advance_ns = float(self.cfg.smu_clk_period_ns)

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sim_ns(self) -> float:
        return float(get_sim_time(unit="ns"))

    def _mark_step(self, step_id: str, detail: str) -> None:
        now = self._sim_ns()
        self._step_ts[step_id] = now
        self._log(f"STEP {step_id} @{now:.3f}ns: {detail}")

    def _mark_lifecycle(self, chk: str, phase: str, detail: str) -> None:
        now = self._sim_ns()
        bucket = self._lifecycle.setdefault(chk, {})
        bucket[phase] = now
        self._log(f"LIFECYCLE {chk} {phase} @{now:.3f}ns: {detail}")

    def _check_lifecycle(self, chk: str) -> None:
        """Fail unless the DUT had simulated time to react between set and observed."""
        order = ["set", "observed", "cleared", "checked_cleared"]
        ts = self._lifecycle.get(chk, {})
        for phase in order:
            if phase not in ts:
                raise AssertionError(f"{chk} lifecycle missing: {phase}")
        for a, b in zip(order, order[1:]):
            if ts[b] < ts[a]:
                raise AssertionError(
                    f"{chk} lifecycle sim-time order fail: {a}={ts[a]:.3f}ns is after "
                    f"{b}={ts[b]:.3f}ns"
                )
        stimulus_to_observe = ts["observed"] - ts["set"]
        if stimulus_to_observe < self.min_sim_advance_ns:
            raise AssertionError(
                f"{chk} lifecycle sim-time advance fail: set->observed "
                f"{stimulus_to_observe:.3f}ns < {self.min_sim_advance_ns:.3f}ns "
                f"(DUT sampled without simulated time to respond)"
            )

    def _sample(self, signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    async def _wait_eq(
        self,
        signal,
        expect: int,
        *,
        clk,
        bound: int,
        label: str,
        name: str,
    ) -> int:
        last = None
        for _ in range(bound):
            await RisingEdge(clk)
            last = self._sample(signal, name)
            if last == expect:
                self._timeout_paths.append(f"{label}: bound={bound} ok last=0x{last:x}")
                return last
        self._timeout_paths.append(
            f"{label}: bound={bound} EXPIRED last={'None' if last is None else f'0x{last:x}'}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={bound} last_state={last} expect={expect} name={name}"
        )

    async def _watch_gate_release(self, dut, *, bound: int, label: str) -> int:
        """clk_smu cycles from the DTP dropping the stall to the fuse gate opening.

        Started before the JTAG write that clears DEBUG_CONTROL: the gate opens
        as soon as the stall drops, while that write is still shifting, so a
        wait begun after the write could find it already open.
        """
        name = "smc_fuse_reset_n_delayed_o"
        while self._sample(dut.jtag_boot_stall_ovrd, "jtag_boot_stall_ovrd") and self._sample(
            dut.jtag_boot_stall, "jtag_boot_stall"
        ):
            if self._sample(dut.smc_fuse_reset_n_delayed_o, name) != 0:
                raise AssertionError(f"{label}: {name} rose while the stall was still asserted")
            await RisingEdge(dut.clk_smu_i)
        if self._sample(dut.smc_fuse_reset_n_delayed_o, name) == 1:
            self._timeout_paths.append(f"{label}: bound={bound} ok cycles=0")
            return 0
        return await self._wait_rise(
            dut.smc_fuse_reset_n_delayed_o, clk=dut.clk_smu_i, bound=bound, label=label, name=name
        )

    async def _wait_rise(
        self,
        signal,
        *,
        clk,
        bound: int,
        label: str,
        name: str,
    ) -> int:
        """0 -> 1 within ``bound``; a signal already 1 is a failure (no transition seen)."""
        first = self._sample(signal, name)
        if first != 0:
            self._timeout_paths.append(f"{label}: bound={bound} NOT-OBSERVED first=0x{first:x}")
            raise AssertionError(
                f"{label}: {name} already {first} before the wait: no 0->1 observed"
            )
        for cycle in range(1, bound + 1):
            await RisingEdge(clk)
            if self._sample(signal, name) == 1:
                self._timeout_paths.append(f"{label}: bound={bound} ok cycles={cycle}")
                return cycle
        self._timeout_paths.append(f"{label}: bound={bound} EXPIRED last=0x0")
        raise AssertionError(f"TIMEOUT {label}: bound={bound} last_state=0 expect=1 name={name}")

    async def _wait_eq_hold(
        self,
        signal,
        expect: int,
        *,
        clk,
        bound: int,
        label: str,
        name: str,
        hold: int = 8,
    ) -> int:
        """Require expect for ``hold`` consecutive cycles (fail if drops)."""
        last = None
        consecutive = 0
        for _ in range(bound):
            await RisingEdge(clk)
            last = self._sample(signal, name)
            if last == expect:
                consecutive += 1
                if consecutive >= hold:
                    self._timeout_paths.append(f"{label}: bound={bound} ok last=0x{last:x}")
                    return last
            else:
                consecutive = 0
        self._timeout_paths.append(
            f"{label}: bound={bound} EXPIRED last={'None' if last is None else f'0x{last:x}'}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={bound} last_state={last} "
            f"expect={expect} hold={hold} name={name}"
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        jtag.init_signals()
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, self.SETTLE)

        # ------------------------------------------------------------------
        # S1 SETUP
        # ------------------------------------------------------------------
        self._mark_step(
            "S1",
            "SETUP: bring SMU out of reset with clocks stable; ready the "
            "JTAG/xtrig pins for boot-stall/IC-reset/clkstop; record baseline",
        )
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        await self._wait_eq(
            smc_primary_reset(dut),
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s1_primary",
            name="rst_primary_smc_clk_no",
        )
        dut.xtrig_clk_stop_req.value = 0
        # No stall at bring-up: the sense completes, then the release follows
        # it within the gate path.
        sense_cycles = await self._wait_rise(
            dut.smc_fuse_sense_done_o,
            clk=dut.clk_smu_i,
            bound=FUSE_SENSE_BOUND_CYCLES,
            label="s1_fuse_sense_done",
            name="smc_fuse_sense_done_o",
        )
        release_cycles = await self._wait_rise(
            dut.smc_fuse_reset_n_delayed_o,
            clk=dut.clk_smu_i,
            bound=FUSE_GATE_RELEASE_BOUND_CYCLES,
            label="s1_fuse_release_after_sense",
            name="smc_fuse_reset_n_delayed_o",
        )
        assert_hold_window_covers(release_cycles, label="s1 release-after-sense", log=cocotb.log)
        self._log(
            f"FUSE-SENSE bring-up: smc_fuse_sense_done_o rose after {sense_cycles} clk_smu, "
            f"smc_fuse_reset_n_delayed_o {release_cycles} clk_smu later @{self._sim_ns():.3f}ns"
        )
        baseline_stop = self._sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o")
        baseline_stall_ovrd = self._sample(dut.jtag_boot_stall_ovrd, "jtag_boot_stall_ovrd")
        baseline_stall = self._sample(dut.jtag_boot_stall, "jtag_boot_stall")
        baseline_fuse = self._sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o")
        if baseline_stop != 0:
            raise AssertionError(f"baseline dtp_stop_clks_o={baseline_stop} expect 0")
        if baseline_fuse != 1:
            raise AssertionError(f"baseline fuse_reset={baseline_fuse} expect 1 after sense-done")
        self._log(
            f"BASELINE: stop_clks={baseline_stop} stall_ovrd={baseline_stall_ovrd} "
            f"stall={baseline_stall} fuse_reset={baseline_fuse} "
            f"cells=SEP=1,tb=wrapper"
        )

        # ------------------------------------------------------------------
        # S2 DTP-BOOT-STALL.S1 — hold SMC boot
        # ------------------------------------------------------------------
        self._mark_step(
            "S2",
            "ACTION/RESPONSE/EFFECT DTP-BOOT-STALL.S1: DEBUG_CONTROL "
            "ovrd=1 stall=1 across cold reset holds SMC fuse_reset",
        )
        self._log("COVERAGE DTP-BOOT-STALL.S1 cells: ovrd=1,stall=1,boot=held")
        stall_val = pack_debug_control(boot_stall_ovrd=1, boot_stall=1)
        self._mark_lifecycle(
            "CHK-DTP-BOOT-STALL-S1",
            "set",
            f"assert observation DEBUG_CONTROL=0x{stall_val:x} ovrd=1 stall=1",
        )
        await jtag.write("DEBUG_CONTROL", stall_val)
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        ovrd = self._sample(dut.jtag_boot_stall_ovrd, "jtag_boot_stall_ovrd")
        stall = self._sample(dut.jtag_boot_stall, "jtag_boot_stall")
        if ovrd != 1 or stall != 1:
            raise AssertionError(f"BOOT-STALL.S1 set fail: ovrd={ovrd} stall={stall}")

        # Cold reset; keep TRST high so DEBUG_CONTROL persists.
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, 64)
        dut.rst_cold_ni.value = 1
        # Arm the sense-done observation at the release itself: the flag reads 0
        # in reset, and the settle below can outlast the whole sense.
        sense_done = cocotb.start_soon(
            self._wait_rise(
                dut.smc_fuse_sense_done_o,
                clk=dut.clk_smu_i,
                bound=FUSE_SENSE_BOUND_CYCLES,
                label="s2_fuse_sense_done_after_cold",
                name="smc_fuse_sense_done_o",
            )
        )
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await self._wait_eq(
            smc_primary_reset(dut),
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s2_primary_after_cold",
            name="rst_primary_smc_clk_no",
        )
        # The cold reset restarted the sense. Only once it has completed is a
        # low fuse_reset the stall gate: hold it at 0 for the whole window
        # (bound == hold, so a single 1 expires the wait).
        sense_cycles = await sense_done
        self._log(
            f"FUSE-SENSE cold+stall: smc_fuse_sense_done_o rose after {sense_cycles} clk_smu "
            f"@{self._sim_ns():.3f}ns fuse_reset="
            f"{self._sample(dut.smc_fuse_reset_n_delayed_o, 'smc_fuse_reset_n_delayed_o')}"
        )
        await self._wait_eq_hold(
            dut.smc_fuse_reset_n_delayed_o,
            0,
            clk=dut.clk_smu_i,
            bound=FUSE_GATE_HOLD_CYCLES,
            label="s2_fuse_held_after_sense",
            name="smc_fuse_reset_n_delayed_o",
            hold=FUSE_GATE_HOLD_CYCLES,
        )
        fuse_held = self._sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o")
        self._mark_lifecycle(
            "CHK-DTP-BOOT-STALL-S1",
            "observed",
            f"consumer samples boot=held fuse_reset={fuse_held} sense_done=1 "
            f"ovrd={self._sample(dut.jtag_boot_stall_ovrd, 'jtag_boot_stall_ovrd')} "
            f"stall={self._sample(dut.jtag_boot_stall, 'jtag_boot_stall')}",
        )
        # cleared = cold-reset pulse cleared (rst_cold_ni back high) while stall holds
        cold_n = self._sample(dut.rst_cold_ni, "rst_cold_ni")
        if cold_n != 1:
            raise AssertionError(f"BOOT-STALL.S1 clear/ack fail: rst_cold_ni={cold_n}")
        self._mark_lifecycle(
            "CHK-DTP-BOOT-STALL-S1",
            "cleared",
            f"clear/ack cold-reset exit rst_cold_ni={cold_n} while stall holds",
        )
        fuse_still = self._sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o")
        if fuse_still != 0:
            raise AssertionError(f"BOOT-STALL.S1 checked_cleared fail: fuse_reset={fuse_still}")
        self._mark_lifecycle(
            "CHK-DTP-BOOT-STALL-S1",
            "checked_cleared",
            f"readback held fuse_reset={fuse_still} after cold-reset clear",
        )
        self._check_lifecycle("CHK-DTP-BOOT-STALL-S1")
        detail_s1 = (
            f"ovrd=1 stall=1 boot=held fuse_reset={fuse_still} cells=ovrd=1,stall=1,boot=held"
        )
        self._log(f"CHK-DTP-BOOT-STALL-S1: PASS ({detail_s1})")
        sb.expect_eq(
            "CHK-DTP-BOOT-STALL-S1 fuse held",
            fuse_still,
            0,
            evidence="CHK-DTP-BOOT-STALL-S1",
        )

        # ------------------------------------------------------------------
        # S3 DTP-BOOT-STALL.S2 — release
        # ------------------------------------------------------------------
        self._mark_step(
            "S3",
            "ACTION/RESPONSE/EFFECT DTP-BOOT-STALL.S2: clear stall/override "
            "allows SMC fuse_reset progression",
        )
        self._log("COVERAGE DTP-BOOT-STALL.S2 cells: stall=0,boot=progresses")
        self._mark_lifecycle(
            "CHK-DTP-BOOT-STALL-S2",
            "set",
            "assert observation DEBUG_CONTROL=0 (clear stall/ovrd)",
        )
        sense_before_clear = self._sample(dut.smc_fuse_sense_done_o, "smc_fuse_sense_done_o")
        fuse_before_clear = self._sample(
            dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o"
        )
        if sense_before_clear != 1 or fuse_before_clear != 0:
            raise AssertionError(
                f"BOOT-STALL.S2 precondition: sense_done={sense_before_clear} "
                f"fuse_reset={fuse_before_clear} before the clear (expect 1 / 0)"
            )
        # The sense is already done, so the rise is the gate opening: bound it
        # by the gate path from the stall clearing, then require it to stay open.
        release_watch = cocotb.start_soon(
            self._watch_gate_release(
                dut,
                bound=FUSE_GATE_RELEASE_BOUND_CYCLES,
                label="s3_fuse_release_after_clear",
            )
        )
        await jtag.write("DEBUG_CONTROL", 0)
        release_cycles = await release_watch
        # The S1 hold above asserted fuse_reset stayed 0 for FUSE_GATE_HOLD_CYCLES
        # while the stall was on. That is evidence only if a gate ignoring the
        # stall would have released inside the window -- which is exactly the
        # latency just measured, so check the two against each other.
        assert_hold_window_covers(
            release_cycles, label="s3 release-after-stall-clear", log=cocotb.log
        )
        await self._wait_eq_hold(
            dut.smc_fuse_reset_n_delayed_o,
            1,
            clk=dut.clk_smu_i,
            bound=FUSE_GATE_HOLD_CYCLES,
            label="s3_fuse_release_stable",
            name="smc_fuse_reset_n_delayed_o",
            hold=FUSE_GATE_HOLD_CYCLES,
        )
        self._log(
            f"FUSE-GATE stall clear: smc_fuse_reset_n_delayed_o released {release_cycles} clk_smu "
            f"after the clear (bound {FUSE_GATE_RELEASE_BOUND_CYCLES}) and held 1 for "
            f"{FUSE_GATE_HOLD_CYCLES} clk_smu @{self._sim_ns():.3f}ns"
        )
        fuse_rel = self._sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o")
        self._mark_lifecycle(
            "CHK-DTP-BOOT-STALL-S2",
            "observed",
            f"consumer samples boot=progresses fuse_reset={fuse_rel}",
        )
        ovrd_c = self._sample(dut.jtag_boot_stall_ovrd, "jtag_boot_stall_ovrd")
        stall_c = self._sample(dut.jtag_boot_stall, "jtag_boot_stall")
        if ovrd_c != 0 or stall_c != 0:
            raise AssertionError(f"BOOT-STALL.S2 clear fail: ovrd={ovrd_c} stall={stall_c}")
        self._mark_lifecycle(
            "CHK-DTP-BOOT-STALL-S2",
            "cleared",
            f"clear/ack stall outputs ovrd={ovrd_c} stall={stall_c}",
        )
        fuse_chk = self._sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o")
        if fuse_chk != 1:
            raise AssertionError(f"BOOT-STALL.S2 checked_cleared fuse_reset={fuse_chk}")
        self._mark_lifecycle(
            "CHK-DTP-BOOT-STALL-S2",
            "checked_cleared",
            f"readback cleared stall; fuse_reset={fuse_chk}",
        )
        self._check_lifecycle("CHK-DTP-BOOT-STALL-S2")
        detail_s2 = f"stall=0 boot=progresses fuse_reset={fuse_chk} cells=stall=0,boot=progresses"
        self._log(f"CHK-DTP-BOOT-STALL-S2: PASS ({detail_s2})")
        sb.expect_eq(
            "CHK-DTP-BOOT-STALL-S2 fuse released",
            fuse_chk,
            1,
            evidence="CHK-DTP-BOOT-STALL-S2",
        )

        # ------------------------------------------------------------------
        # S4 DTP-IC-RESET.S1 — SMC cold override
        # ------------------------------------------------------------------
        self._mark_step(
            "S4",
            "ACTION/RESPONSE/EFFECT DTP-IC-RESET.S1: SMC IC_RESET override "
            "forces selected SMC cold-reset slice to programmed value",
        )
        self._log("COVERAGE DTP-IC-RESET.S1 cells: target=smc,ovrd=1")
        smc_assert = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_SMC_COLD_PORT: 0},
            port_control={SMU_IC_RESET_SMC_COLD_PORT: 0},
        )
        await jtag.write("IC_RESET", smc_assert)
        await ClockCycles(dut.clk_smu_i, 16)
        smc_ovrd = self._sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd")
        smc_ctrl = self._sample(dut.jtag_ic_reset_smc_ctrl_n, "jtag_ic_reset_smc_ctrl_n")
        if smc_ovrd != 1 or smc_ctrl != 0:
            raise AssertionError(f"IC-RESET.S1 fail: smc_ovrd={smc_ovrd} smc_ctrl_n={smc_ctrl}")
        detail_ic1 = f"target=smc ovrd=1 ctrl_n={smc_ctrl} cells=target=smc,ovrd=1"
        self._log(f"CHK-DTP-IC-RESET-S1: PASS ({detail_ic1})")
        sb.expect_eq(
            "CHK-DTP-IC-RESET-S1 SMC ovrd",
            (smc_ovrd, smc_ctrl),
            (1, 0),
            evidence="CHK-DTP-IC-RESET-S1",
        )

        # ------------------------------------------------------------------
        # S5 DTP-IC-RESET.S3 — clear_ovrd + TRST/POR exit
        # ------------------------------------------------------------------
        self._mark_step(
            "S5",
            "ACTION/RESPONSE/EFFECT DTP-IC-RESET.S3: clear override then "
            "TRST/POR each remove the override effect",
        )
        self._log("COVERAGE DTP-IC-RESET.S3 cells: exit=clear_ovrd,exit=trst_por")
        # Path A: clear_ovrd via TDR default
        await jtag.write("IC_RESET", SMU_IC_RESET_DEFAULT)
        await ClockCycles(dut.clk_smu_i, 16)
        clr_ovrd = self._sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd")
        if clr_ovrd != 0:
            raise AssertionError(f"IC-RESET.S3 clear_ovrd fail: smc_ovrd={clr_ovrd}")
        self._log(f"IC-RESET.S3 exit=clear_ovrd smc_ovrd={clr_ovrd}")

        # Re-assert then TRST exit
        await jtag.write("IC_RESET", smc_assert)
        await ClockCycles(dut.clk_smu_i, 16)
        re_ovrd = self._sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd")
        if re_ovrd != 1:
            raise AssertionError(f"IC-RESET.S3 re-assert fail: smc_ovrd={re_ovrd}")
        await jtag.assert_trst(tck_cycles=0)
        for _ in range(self.TRST_CYCLES):
            await RisingEdge(dut.clk_ref_i)
        await jtag.release_trst()
        await ClockCycles(dut.clk_ref_i, 8)
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 16)
        trst_ovrd = self._sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd")
        if trst_ovrd != 0:
            raise AssertionError(f"IC-RESET.S3 TRST exit fail: smc_ovrd={trst_ovrd}")
        self._log(f"IC-RESET.S3 exit=trst_por smc_ovrd={trst_ovrd}")
        detail_ic3 = (
            f"exit=clear_ovrd clr={clr_ovrd} exit=trst_por trst={trst_ovrd} "
            f"cells=exit=clear_ovrd,exit=trst_por"
        )
        self._log(f"CHK-DTP-IC-RESET-S3: PASS ({detail_ic3})")
        sb.expect_eq(
            "CHK-DTP-IC-RESET-S3 both exits clear",
            (clr_ovrd, trst_ovrd),
            (0, 0),
            evidence="CHK-DTP-IC-RESET-S3",
        )

        # ------------------------------------------------------------------
        # S6 DTP-CLKSTOP-AGG.S1 — JTAG-only stop
        # ------------------------------------------------------------------
        self._mark_step(
            "S6",
            "ACTION/RESPONSE/EFFECT DTP-CLKSTOP-AGG.S1: only jtag_clock_stop asserts stop_clks_o",
        )
        self._log("COVERAGE DTP-CLKSTOP-AGG.S1 cells: src=jtag,stop_clks=1")
        dut.xtrig_clk_stop_req.value = 0
        val_jtag = pack_debug_control(jtag_clock_stop=1)
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S1",
            "set",
            f"assert observation DEBUG_CONTROL jtag_clock_stop val=0x{val_jtag:x} xtrig=0",
        )
        await jtag.write("DEBUG_CONTROL", val_jtag)
        stop1 = await self._wait_eq(
            dut.dtp_stop_clks_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s6_stop_assert",
            name="dtp_stop_clks_o",
        )
        xtrig_idle = self._sample(dut.xtrig_clk_stop_req, "xtrig_clk_stop_req")
        if xtrig_idle != 0:
            raise AssertionError(f"CLKSTOP-AGG.S1 not JTAG-only: xtrig={xtrig_idle}")
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S1",
            "observed",
            f"consumer samples stop_clks={stop1} src=jtag xtrig={xtrig_idle}",
        )
        await jtag.write("DEBUG_CONTROL", 0)
        stop_clr = await self._wait_eq(
            dut.dtp_stop_clks_o,
            0,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s6_stop_clear",
            name="dtp_stop_clks_o",
        )
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S1",
            "cleared",
            f"clear/ack jtag_clock_stop; stop_clks={stop_clr}",
        )
        stop_chk = self._sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o")
        if stop_chk != 0:
            raise AssertionError(f"CLKSTOP-AGG.S1 checked_cleared stop_clks={stop_chk}")
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S1",
            "checked_cleared",
            f"readback cleared stop_clks={stop_chk}",
        )
        self._check_lifecycle("CHK-DTP-CLKSTOP-AGG-S1")
        detail_c1 = "src=jtag stop_clks=1 then cleared cells=src=jtag,stop_clks=1"
        self._log(f"CHK-DTP-CLKSTOP-AGG-S1: PASS ({detail_c1})")
        sb.expect_eq(
            "CHK-DTP-CLKSTOP-AGG-S1 jtag-only",
            stop1,
            1,
            evidence="CHK-DTP-CLKSTOP-AGG-S1",
        )

        # ------------------------------------------------------------------
        # S7 DTP-CLKSTOP-AGG.S2 — CLA-only stop + status
        # ------------------------------------------------------------------
        self._mark_step(
            "S7",
            "ACTION/RESPONSE/EFFECT DTP-CLKSTOP-AGG.S2: only CLA "
            "clk_stop_req asserts stop_clks_o and CLA-only status",
        )
        self._log("COVERAGE DTP-CLKSTOP-AGG.S2 cells: src=cla,stop_clks=1,cla_status=1")
        # jtag_clock_stop=0; TB xtrig[0] -> DTP[1] (CLA request path)
        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S2",
            "set",
            "assert observation TB xtrig_clk_stop_req[0]=1 jtag_clock_stop=0",
        )
        dut.xtrig_clk_stop_req.value = 0x1
        stop_cla = await self._wait_eq(
            dut.dtp_stop_clks_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s7_cla_stop_assert",
            name="dtp_stop_clks_o",
        )
        # CLA-only status via DEBUG_CONTROL bit 4
        rb = await jtag.read("DEBUG_CONTROL", shift_value=0)
        cla_status = (int(rb) >> DBG_CLA_CLOCK_STOP_BIT) & 0x1
        jtag_stop_bit = (int(rb) >> 3) & 0x1
        if cla_status != 1:
            raise AssertionError(
                f"CLKSTOP-AGG.S2 CLA status fail: DEBUG_CONTROL=0x{int(rb):x} "
                f"cla_status={cla_status}"
            )
        if jtag_stop_bit != 0:
            raise AssertionError(f"CLKSTOP-AGG.S2 not CLA-only: jtag_clock_stop={jtag_stop_bit}")
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S2",
            "observed",
            f"consumer samples stop_clks={stop_cla} cla_status={cla_status} "
            f"jtag_stop={jtag_stop_bit}",
        )
        dut.xtrig_clk_stop_req.value = 0
        stop_cla_clr = await self._wait_eq(
            dut.dtp_stop_clks_o,
            0,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s7_cla_stop_clear",
            name="dtp_stop_clks_o",
        )
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S2",
            "cleared",
            f"clear/ack xtrig; stop_clks={stop_cla_clr}",
        )
        rb2 = await jtag.read("DEBUG_CONTROL", shift_value=0)
        cla_status2 = (int(rb2) >> DBG_CLA_CLOCK_STOP_BIT) & 0x1
        if cla_status2 != 0 or stop_cla_clr != 0:
            raise AssertionError(
                f"CLKSTOP-AGG.S2 checked_cleared fail: stop={stop_cla_clr} cla_status={cla_status2}"
            )
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S2",
            "checked_cleared",
            f"readback cleared stop={stop_cla_clr} cla_status={cla_status2}",
        )
        self._check_lifecycle("CHK-DTP-CLKSTOP-AGG-S2")
        detail_c2 = "src=cla stop_clks=1 cla_status=1 cells=src=cla,stop_clks=1,cla_status=1"
        self._log(f"CHK-DTP-CLKSTOP-AGG-S2: PASS ({detail_c2})")
        sb.expect_eq(
            "CHK-DTP-CLKSTOP-AGG-S2 CLA-only",
            (stop_cla, cla_status),
            (1, 1),
            evidence="CHK-DTP-CLKSTOP-AGG-S2",
        )

        # ------------------------------------------------------------------
        # S8 DTP-CLKSTOP-AGG.S3 — port[0] reserved for the SMC
        # ------------------------------------------------------------------
        # Only the reserved-port property is attested here: the TB clock-stop
        # request pins land on DTP[8:1] and leave DTP[0] untouched. DTP[0] is
        # the SMC's clocks_stopped_by_cla, which this bench has no way to
        # provoke (the SMC runs the default ROM and the CLA event has no CSR
        # path), so its level is logged, not compared.
        self._mark_step(
            "S8",
            "ACTION/RESPONSE/EFFECT DTP-CLKSTOP-AGG.S3: port[0] is reserved for "
            "the SMC; TB clock-stop requests land on DTP[8:1] and do not reach DTP[0]",
        )
        self._log("COVERAGE DTP-CLKSTOP-AGG.S3 cells: port0=smc_reserved")
        cla_en = pack_debug_control(cla_clock_stop_en=1)
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S3",
            "set",
            f"assert observation cla_clock_stop_en=1 val=0x{cla_en:x}",
        )
        await jtag.write("DEBUG_CONTROL", cla_en)
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        en_o = self._sample(dut.dtp_cla_clock_stop_en, "dtp_cla_clock_stop_en")
        if en_o != 1:
            raise AssertionError(f"CLKSTOP-AGG.S3 handshake en fail: dtp_cla_clock_stop_en={en_o}")
        dtp0_before = (
            self._sample(smu_scope(dut).dtp_xtrig_clk_stop_req, "dtp_xtrig_clk_stop_req") & 0x1
        )
        # Drive TB xtrig[0]=1; must appear at DTP[1], NOT DTP[0]
        dut.xtrig_clk_stop_req.value = 0x1
        await RisingEdge(dut.clk_smu_i)
        await RisingEdge(dut.clk_smu_i)
        dtp_req = self._sample(smu_scope(dut).dtp_xtrig_clk_stop_req, "dtp_xtrig_clk_stop_req")
        smc_fb = self._sample(
            smu_scope(dut).tdr_dbg_ctrl_clocks_stopped_by_cla,
            "tdr_dbg_ctrl_clocks_stopped_by_cla",
        )
        dtp0 = dtp_req & 0x1
        dtp_hi = (dtp_req >> 1) & 0xFF
        if dtp0 != dtp0_before:
            raise AssertionError(
                f"CLKSTOP-AGG.S3 port0 not SMC-reserved: TB xtrig[0] moved DTP[0] "
                f"{dtp0_before}->{dtp0} dtp_req=0x{dtp_req:x}"
            )
        if dtp_hi != 0x1:
            raise AssertionError(
                f"CLKSTOP-AGG.S3 TB xtrig remap fail: DTP[8:1]=0x{dtp_hi:x} expect 0x1"
            )
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S3",
            "observed",
            f"consumer samples port0=smc_reserved dtp0={dtp0} (before={dtp0_before}) "
            f"DTP[8:1]=0x{dtp_hi:x} en={en_o}; SMC clocks_stopped_by_cla={smc_fb} (logged only)",
        )
        dut.xtrig_clk_stop_req.value = 0
        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        en_clr = self._sample(dut.dtp_cla_clock_stop_en, "dtp_cla_clock_stop_en")
        if en_clr != 0:
            raise AssertionError(f"CLKSTOP-AGG.S3 clear fail: dtp_cla_clock_stop_en={en_clr}")
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S3",
            "cleared",
            f"clear/ack cla_en and xtrig; en={en_clr}",
        )
        dtp_idle = await self._wait_eq(
            smu_scope(dut).dtp_xtrig_clk_stop_req,
            dtp0_before,  # DTP[8:1] back to 0; DTP[0] as it was before the drive
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s8_port0_idle",
            name="dtp_xtrig_clk_stop_req",
        )
        if ((dtp_idle >> 1) & 0xFF) != 0:
            raise AssertionError(
                f"CLKSTOP-AGG.S3 checked_cleared upper bits live: dtp=0x{dtp_idle:x}"
            )
        if (dtp_idle & 0x1) != dtp0_before:
            raise AssertionError("CLKSTOP-AGG.S3 checked_cleared DTP[0] moved with the TB pins")
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S3",
            "checked_cleared",
            f"readback idle dtp=0x{dtp_idle:x} en={en_clr}",
        )
        self._check_lifecycle("CHK-DTP-CLKSTOP-AGG-S3")
        detail_c3 = (
            f"port0=smc_reserved dtp0={dtp0} unchanged from {dtp0_before} "
            f"DTP[8:1]=0x{dtp_hi:x} cells=port0=smc_reserved"
        )
        self._log(f"CHK-DTP-CLKSTOP-AGG-S3: PASS ({detail_c3})")
        sb.expect_eq(
            "CHK-DTP-CLKSTOP-AGG-S3 port0 SMC reserved",
            (dtp0 == dtp0_before, dtp_hi, en_o),
            (True, 0x1, 1),
            evidence="CHK-DTP-CLKSTOP-AGG-S3",
        )

        # ------------------------------------------------------------------
        # S9 bounded-wait inventory (diagnostic log)
        # ------------------------------------------------------------------
        self._mark_step(
            "S9",
            "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last observed state",
        )
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        self._log(
            f"TIMEOUT-PATH inventory: {len(self._timeout_paths)} bounded wait(s) "
            f"bound_cycles={self.BOUND_CYCLES}"
        )

        # ------------------------------------------------------------------
        # CHK-NONVAC simulation-time fence
        # ------------------------------------------------------------------
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        self._step_ts["PASS"] = self._sim_ns()
        self._log("SMU_ALL_006 sequence complete (PASS term recorded for NONVAC fence)")
        order = [
            "S1",
            "S2",
            "S3",
            "S4",
            "S5",
            "S6",
            "S7",
            "S8",
            "S9",
            "PASS",
        ]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        deltas_ns = [self._step_ts[b] - self._step_ts[a] for a, b in zip(order, order[1:])]
        min_ns = self.min_sim_advance_ns
        advancing = sum(1 for d in deltas_ns if d >= min_ns)
        expect_deltas = len(order) - 1
        if advancing != expect_deltas:
            raise AssertionError(
                f"CHK-NONVAC sim-time fence fail: {advancing} of {expect_deltas} steps "
                f"advanced >= {min_ns:.3f}ns of simulation time; "
                f"deltas_ns={[round(d, 3) for d in deltas_ns]}"
            )
        self._log(
            "CHK-NONVAC: Ordered simulation-time fence S1<S2<S3<S4<S5<S6<S7<S8<S9<PASS all hold "
            f"(min_step={min_ns:.3f}ns "
            f"total={self._step_ts['PASS'] - self._step_ts['S1']:.3f}ns "
            f"deltas_ns={[round(d, 3) for d in deltas_ns]})"
        )
        sb.expect_eq(
            "CHK-NONVAC sim-time advancing step count",
            advancing,
            expect_deltas,
            evidence="CHK-NONVAC",
        )
