# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_clock_stop_coordination_test (SMU_ALL_006).

DV-CARD:          SMU_ALL_006   ANCHOR: smu_clock_stop_coordination_test

Allocated (narrowed Option B; SEP=0 bare tb_top):
  DTP-BOOT-STALL.S1 / S2
  DTP-IC-RESET.S1 / S3
  DTP-CLKSTOP-AGG.S1 / S2 / S3
No Force/deposit. No DTP-FEAT-GATE.* / INT-FEAT-CTRL-DTP-GATE (re-homed to 008).
"""

from __future__ import annotations

from seq_lib.smu_tb_pins import smc_primary_reset

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DBG_CLA_CLOCK_STOP_BIT,
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_SMC_COLD_PORT,
    make_smu_jtag_tap,
    pack_debug_control,
    pack_ic_reset_ports,
)


class smu_clock_stop_coordination_test_seq:
    """SMU_ALL_006: boot-stall / IC-RESET / clkstop aggregation."""

    BOUND_CYCLES = 2000
    BOUND_REF = 2000
    SETTLE = 8
    TRST_CYCLES = 8
    # Real poll-with-expiry sites (each can hit EXPIRED):
    #   s1_primary, s2_primary_after_cold, s2_fuse_held_stable,
    #   s3_fuse_release, s6_stop_assert, s6_stop_clear,
    #   s7_cla_stop_assert, s7_cla_stop_clear, s8_port0_idle
    EXPECTED_TIMEOUT_PATHS = 9

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []
        self._lifecycle: dict[str, dict[str, float]] = {}

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = time.monotonic()
        self._log(f"STEP {step_id}: {detail}")

    def _mark_lifecycle(self, chk: str, phase: str, detail: str) -> None:
        bucket = self._lifecycle.setdefault(chk, {})
        bucket[phase] = time.monotonic()
        self._log(f"LIFECYCLE {chk} {phase}: {detail}")

    def _check_lifecycle(self, chk: str) -> None:
        order = ["set", "observed", "cleared", "checked_cleared"]
        ts = self._lifecycle.get(chk, {})
        for phase in order:
            if phase not in ts:
                raise AssertionError(f"{chk} lifecycle missing: {phase}")
        for a, b in zip(order, order[1:]):
            if ts[a] >= ts[b]:
                raise AssertionError(f"{chk} lifecycle order fail: {a} not before {b}")

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
            "SETUP: bring SMU out of reset with clocks stable; ready bare "
            "tb_top JTAG/xtrig for boot-stall/IC-reset/clkstop; record baseline",
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
        baseline_stop = self._sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o")
        baseline_stall_ovrd = self._sample(dut.jtag_boot_stall_ovrd, "jtag_boot_stall_ovrd")
        baseline_stall = self._sample(dut.jtag_boot_stall, "jtag_boot_stall")
        baseline_fuse = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
        if baseline_stop != 0:
            raise AssertionError(f"baseline dtp_stop_clks_o={baseline_stop} expect 0")
        self._log(
            f"BASELINE: stop_clks={baseline_stop} stall_ovrd={baseline_stall_ovrd} "
            f"stall={baseline_stall} fuse_reset={baseline_fuse} "
            f"cells=SEP=0,tb=bare"
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
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await self._wait_eq(
            smc_primary_reset(dut),
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s2_primary_after_cold",
            name="rst_primary_smc_clk_no",
        )
        # Held fuse_reset across sticky stall (must stay 0).
        await self._wait_eq_hold(
            dut.fuse_reset_n_delayed_o,
            0,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s2_fuse_held_stable",
            name="fuse_reset_n_delayed_o",
            hold=16,
        )
        fuse_held = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
        self._mark_lifecycle(
            "CHK-DTP-BOOT-STALL-S1",
            "observed",
            f"consumer samples boot=held fuse_reset={fuse_held} "
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
        fuse_still = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
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
        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        await self._wait_eq(
            dut.fuse_reset_n_delayed_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s3_fuse_release",
            name="fuse_reset_n_delayed_o",
        )
        fuse_rel = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
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
        fuse_chk = self._sample(dut.fuse_reset_n_delayed_o, "fuse_reset_n_delayed_o")
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
        dut.jtag_trst.value = 0
        for _ in range(self.TRST_CYCLES):
            await RisingEdge(dut.clk_ref_i)
        dut.jtag_trst.value = 1
        await ClockCycles(dut.clk_ref_i, 8)
        jtag._state = OcahJtagState.TEST_LOGIC_RESET
        jtag._current_instruction = None
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
        # S8 DTP-CLKSTOP-AGG.S3 — port[0] SMC reserved handshake
        # ------------------------------------------------------------------
        self._mark_step(
            "S8",
            "ACTION/RESPONSE/EFFECT DTP-CLKSTOP-AGG.S3: port[0] reserved for "
            "SMC participates in SMC CLA handshake (CONNECTIVITY)",
        )
        self._log("COVERAGE DTP-CLKSTOP-AGG.S3 cells: port0=smc_reserved,smc_cla=handshake")
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
        # Drive TB xtrig[0]=1; must appear at DTP[1], NOT DTP[0]
        dut.xtrig_clk_stop_req.value = 0x1
        await RisingEdge(dut.clk_smu_i)
        await RisingEdge(dut.clk_smu_i)
        dtp_req = self._sample(dut.u_dut.dtp_xtrig_clk_stop_req, "dtp_xtrig_clk_stop_req")
        smc_fb = self._sample(
            dut.u_dut.tdr_dbg_ctrl_clocks_stopped_by_cla,
            "tdr_dbg_ctrl_clocks_stopped_by_cla",
        )
        dtp0 = dtp_req & 0x1
        dtp_hi = (dtp_req >> 1) & 0xFF
        if dtp0 != smc_fb:
            raise AssertionError(
                f"CLKSTOP-AGG.S3 port0 not SMC-reserved: dtp0={dtp0} "
                f"smc_fb={smc_fb} dtp_req=0x{dtp_req:x}"
            )
        if dtp_hi != 0x1:
            raise AssertionError(
                f"CLKSTOP-AGG.S3 TB xtrig remap fail: DTP[8:1]=0x{dtp_hi:x} expect 0x1"
            )
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S3",
            "observed",
            f"consumer samples port0=smc_reserved dtp0={dtp0} smc_fb={smc_fb} "
            f"DTP[8:1]=0x{dtp_hi:x} en={en_o} smc_cla=handshake",
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
            dut.u_dut.dtp_xtrig_clk_stop_req,
            smc_fb & 0x1,  # only SMC fb bit may remain; upper bits 0
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s8_port0_idle",
            name="dtp_xtrig_clk_stop_req",
        )
        # Upper bits must be 0; port0 still equals SMC fb
        if ((dtp_idle >> 1) & 0xFF) != 0:
            raise AssertionError(
                f"CLKSTOP-AGG.S3 checked_cleared upper bits live: dtp=0x{dtp_idle:x}"
            )
        if (dtp_idle & 0x1) != (
            self._sample(
                dut.u_dut.tdr_dbg_ctrl_clocks_stopped_by_cla,
                "tdr_dbg_ctrl_clocks_stopped_by_cla",
            )
        ):
            raise AssertionError("CLKSTOP-AGG.S3 checked_cleared port0/SMC fb mismatch")
        self._mark_lifecycle(
            "CHK-DTP-CLKSTOP-AGG-S3",
            "checked_cleared",
            f"readback idle dtp=0x{dtp_idle:x} en={en_clr}",
        )
        self._check_lifecycle("CHK-DTP-CLKSTOP-AGG-S3")
        detail_c3 = (
            f"port0=smc_reserved smc_cla=handshake dtp0={dtp0} "
            f"smc_fb={smc_fb} DTP[8:1]=0x{dtp_hi:x} "
            f"cells=port0=smc_reserved,smc_cla=handshake"
        )
        self._log(f"CHK-DTP-CLKSTOP-AGG-S3: PASS ({detail_c3})")
        sb.expect_eq(
            "CHK-DTP-CLKSTOP-AGG-S3 port0 SMC reserved",
            (dtp0, dtp_hi, en_o),
            (smc_fb, 0x1, 1),
            evidence="CHK-DTP-CLKSTOP-AGG-S3",
        )

        # ------------------------------------------------------------------
        # S9 TIMEOUT inventory
        # ------------------------------------------------------------------
        self._mark_step(
            "S9",
            "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last observed state",
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
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing finite bound: {line}")
            if "ok last=" not in line and "EXPIRED last=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing last-state: {line}")
        self._log(
            "CHK-TIMEOUT-PATHS: Finite bound on S9; expiry fails with "
            f"last-state diagnostics (paths={n_paths} "
            f"expect={self.EXPECTED_TIMEOUT_PATHS} "
            f"bound_cycles={self.BOUND_CYCLES})"
        )
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count+shape",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step_ts["PASS"] = time.monotonic()
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
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        deltas_ns = [
            int((self._step_ts[b] - self._step_ts[a]) * 1e9) for a, b in zip(order, order[1:])
        ]
        positive_deltas = sum(1 for d in deltas_ns if d > 0)
        expect_deltas = len(order) - 1
        if positive_deltas != expect_deltas:
            raise AssertionError(
                f"CHK-NONVAC positive-delta count fail: {positive_deltas} "
                f"expect={expect_deltas} deltas_ns={deltas_ns}"
            )
        self._log("CHK-NONVAC: Ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<PASS all hold")
        sb.expect_eq(
            "CHK-NONVAC positive step-delta count",
            positive_deltas,
            expect_deltas,
            evidence="CHK-NONVAC",
        )
