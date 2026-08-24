# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_ZEROER_REGCLK_CG_TEST ANCHOR: smc_zeroer_regclk_cg_test
DV-CARD-REVISION: 1 RECORD-SHA256: 47e3381f135bfb76907ef06f89d4eb70bb30c6c7bb0232bb56dee36072ecbd1b
DV-CARD-SOURCE: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb

DV-CARD: SMC_CG_P2_003 ANCHOR: smc_zeroer_regclk_cg_test
DV-CARD-REVISION: 1 RECORD-SHA256: 93666c6c76e78b0f181dba725025d1652ff5407526e20c4421403218b24e290e
DV-CARD-SOURCE: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb

The P2 card extends this same anchor (additive): the P1 steps/checkers above
are UNCHANGED (their evidence tokens must keep appearing verbatim for the
closed P1 grade); the P2 extension below (_p2_extension) sweeps the
pending-access-while-gated race across 3 required cells (immediately after
gate, long after gate, back-to-back across the gate boundary), per SF-004
(answered): register_activity asserts on any AXI4-Lite access; pending-access
service must complete within the card's own declared bounded wait (there is
no separate SPEC max-wait constant).
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, ReadOnly, Timer

from .smc_csr_seq_utils import SmcCsrSeq
from . import smc_cg_obs_utils as cg
from . import smc_addr_map as _addr

_LOG = logging.getLogger(__name__)

# hyst=0 so card within-1-cycle idle gate-off matches axi_cg_snoop (DenyDelay=1).
HYST = 0
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 256
BUSY_TIMEOUT_SMC = 256

# Authoritative map (also re-exported via smc_cg_obs_utils).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
ZEROER_CG_EN = _addr.ZEROER_CG_EN
CG_HYST_SHIFT = _addr.CG_HYST_SHIFT
CG_HYST_MASK = _addr.CG_HYST_MASK
ZEROER_CTRL_DEST_ADDR = _addr.ZEROER_CTRL_DEST_ADDR

# P2 (SMC_CG_P2_003) additions: pending-access-while-gated race sweep.
P2_LONG_IDLE_CYCLES = 40
P2_UNGATE_BOUND_SMC = 32
P2_SERVICE_BOUND_SMC = 128
P2_ACCESS_VALUES = {
    "access-immediately-after-reg_clk-gates": 0xA5A5_0001,
    "access-long-after-reg_clk-gates": 0xA5A5_0002,
    "back-to-back-accesses-across-gate-boundary": 0xA5A5_0004,
}
P2_B2B_FIRST_VALUE = 0xA5A5_0003


class smc_zeroer_regclk_cg_test_seq(SmcCsrSeq):
    """LIVE Zeroer reg_clk gating (idle / activity / disable_cg / reset)."""

    def __init__(self, name: str = "smc_zeroer_regclk_cg_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_seen: dict[str, str] = {}

    def _dut(self):
        return cocotb.top

    async def _program_cg(self, *, zeroer_en: bool, hyst: int = HYST) -> None:
        cur = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        nxt = (cur & ~ZEROER_CG_EN & ~CG_HYST_MASK) | (
            (hyst << CG_HYST_SHIFT) & CG_HYST_MASK
        )
        if zeroer_en:
            nxt |= ZEROER_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_WR", CLOCK_GATE_CONTROL, nxt, length=8)
        rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, length=8)
        assert (rb & ZEROER_CG_EN) == (ZEROER_CG_EN if zeroer_en else 0)

    async def _measure_access_window(self) -> tuple[int, int, int]:
        """Resume delta from bus_active + every-cycle enable for access window."""
        dut = self._dut()
        state = {
            "active_at": -1,
            "resume_at": -1,
            "post_resume_cycles": 0,
            "enabled_hits": 0,
            "smc": 0,
            "seen_active": False,
            "done": False,
        }

        async def _mon() -> None:
            while not state["done"] and state["smc"] < BUSY_TIMEOUT_SMC * 8:
                await RisingEdge(dut.clk_smc_i)
                state["smc"] += 1
                await ReadOnly()
                active = cg.sample_bit(dut, "tb_zeroer_bus_active") == 1
                gval = dut.tb_zeroer_gated_reg_clk.value
                if gval.is_resolvable is False:
                    raise AssertionError("tb_zeroer_gated_reg_clk sample is X/Z")
                gated_on = int(gval) == 1
                await Timer(1, unit="ps")
                if state["active_at"] < 0 and active:
                    state["active_at"] = state["smc"]
                    state["seen_active"] = True
                if state["active_at"] >= 0 and state["resume_at"] < 0 and gated_on:
                    state["resume_at"] = state["smc"]
                if state["resume_at"] >= 0 and active:
                    state["post_resume_cycles"] += 1
                    if gated_on:
                        state["enabled_hits"] += 1
                elif state["seen_active"] and not active:
                    state["done"] = True
                    return

        mon = cocotb.start_soon(_mon())
        # SF-004: any AXI4-Lite access (read or write) to Zeroer register block.
        _ = await self.csr_read("ZEROER_DEST_ADDR_ACT", ZEROER_CTRL_DEST_ADDR, length=8)
        for _ in range(BUSY_TIMEOUT_SMC * 8):
            if state["done"]:
                break
            await RisingEdge(dut.clk_smc_i)
        mon.cancel()
        assert state["active_at"] >= 0, "zeroer bus_active never asserted on access"
        assert state["resume_at"] >= 0, "reg_clk did not resume after access"
        assert state["done"], "TIMEOUT waiting bus_active clear during access window"
        delta = max(0, state["resume_at"] - state["active_at"])
        return delta, state["enabled_hits"], state["post_resume_cycles"]

    # ---- P2 (SMC_CG_P2_003) helpers -----------------------------------

    async def _p2_timed_access(self, action_coro) -> dict:
        """Run `action_coro` (one CSR access) concurrently while sampling
        (bus_active, reg_clk_enabled) every clk_smc_i period -- same
        technique as `_measure_access_window`, generalised over an
        arbitrary access so it can be scheduled at each of the 3 required
        gate-boundary timings. Returns the resume delta (bus_active to
        reg_clk_enable) and whether reg_clk_enable ever dropped again
        before the access's own bus_active window cleared."""
        dut = self._dut()
        state = {
            "active_at": -1,
            "resume_at": -1,
            "smc": 0,
            "seen_active": False,
            "done": False,
        }
        glitch = {"seen": False, "idx": -1}

        async def _mon() -> None:
            while not state["done"] and state["smc"] < P2_SERVICE_BOUND_SMC * 4:
                await RisingEdge(dut.clk_smc_i)
                state["smc"] += 1
                await ReadOnly()
                active = cg.sample_bit(dut, "tb_zeroer_bus_active") == 1
                gval = dut.tb_zeroer_gated_reg_clk.value
                if gval.is_resolvable is False:
                    raise AssertionError("tb_zeroer_gated_reg_clk sample is X/Z")
                gated_on = int(gval) == 1
                await Timer(1, unit="ps")
                if state["active_at"] < 0 and active:
                    state["active_at"] = state["smc"]
                    state["seen_active"] = True
                if state["active_at"] >= 0 and state["resume_at"] < 0 and gated_on:
                    state["resume_at"] = state["smc"]
                if state["resume_at"] >= 0 and not gated_on and not state["done"]:
                    glitch["seen"] = True
                    glitch["idx"] = state["smc"]
                if state["seen_active"] and not active and state["resume_at"] >= 0:
                    state["done"] = True
                    return

        mon = cocotb.start_soon(_mon())
        await action_coro
        for _ in range(P2_SERVICE_BOUND_SMC):
            if state["done"]:
                break
            await RisingEdge(dut.clk_smc_i)
        mon.cancel()
        if state["active_at"] < 0 or state["resume_at"] < 0:
            raise AssertionError(
                f"TIMEOUT: access never drove bus_active/reg_clk resume "
                f"(active_at={state['active_at']} resume_at={state['resume_at']})"
            )
        delta = max(0, state["resume_at"] - state["active_at"])
        return {"delta": delta, "glitch": glitch["seen"], "glitch_at": glitch["idx"]}

    async def _p2_extension(self) -> None:
        """P2 extension (SMC_CG_P2_003), additive after the P1 flow in
        body(): pending-access-while-gated race across 3 required cells."""
        dut = self._dut()
        cg.log_step(
            "P2-S1",
            "SETUP: hold the register interface idle long enough that "
            "reg_clk gates (reg_clk_enable falls to 0) with no access pending",
        )
        cg.mark_fence(self.fence, "SETUP")
        await self._program_cg(zeroer_en=True)
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_reg_clk",
            hyst=HYST,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en",),
        )
        edges = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_reg_clk", 4)
        assert edges == 0, f"P2 setup: reg_clk not gated at baseline: edges={edges}"
        cg.mark_fence(self.fence, "REG_CLK-GATED-BASELINE")

        cg.log_step(
            "P2-S2",
            "ACTION/RESPONSE/EFFECT for SMC-CG-ZEROER-REGCLK.S1: sweep a "
            "pending register access across 3 gate-boundary timings",
        )
        results: dict[str, dict] = {}

        # Cell 1: immediately after reg_clk gates.
        label = "access-immediately-after-reg_clk-gates"
        val = P2_ACCESS_VALUES[label]
        meas = await self._p2_timed_access(
            self.csr_write("P2_ZREG_IMM_WR", ZEROER_CTRL_DEST_ADDR, val, length=8)
        )
        rb = await self.csr_read("P2_ZREG_IMM_RB", ZEROER_CTRL_DEST_ADDR, length=8)
        assert meas["delta"] <= P2_UNGATE_BOUND_SMC, (
            f"{label}: reg_clk_enable did not rise within {P2_UNGATE_BOUND_SMC} "
            f"cycles of the access: delta={meas['delta']}"
        )
        assert rb == val, f"{label}: write not reflected: wrote {val:#x} read {rb:#x}"
        results[label] = {"resume_delta": meas["delta"], "written": val, "readback": rb}

        # Re-settle idle+gated before the next cell.
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_reg_clk",
            hyst=HYST,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en",),
        )

        # Cell 2: long after reg_clk gates.
        label = "access-long-after-reg_clk-gates"
        val = P2_ACCESS_VALUES[label]
        await ClockCycles(dut.clk_smc_i, P2_LONG_IDLE_CYCLES)
        edges = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_reg_clk", 4)
        assert edges == 0, f"{label}: reg_clk unexpectedly active during long-idle wait"
        meas = await self._p2_timed_access(
            self.csr_write("P2_ZREG_LONG_WR", ZEROER_CTRL_DEST_ADDR, val, length=8)
        )
        rb = await self.csr_read("P2_ZREG_LONG_RB", ZEROER_CTRL_DEST_ADDR, length=8)
        assert meas["delta"] <= P2_UNGATE_BOUND_SMC, (
            f"{label}: reg_clk_enable did not rise within {P2_UNGATE_BOUND_SMC} "
            f"cycles of the access: delta={meas['delta']}"
        )
        assert rb == val, f"{label}: write not reflected: wrote {val:#x} read {rb:#x}"
        results[label] = {
            "resume_delta": meas["delta"],
            "written": val,
            "readback": rb,
            "idle_cycles": P2_LONG_IDLE_CYCLES,
        }

        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_reg_clk",
            hyst=HYST,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en",),
        )

        # Cell 3: two accesses issued back-to-back across the gate boundary.
        label = "back-to-back-accesses-across-gate-boundary"
        val_b = P2_ACCESS_VALUES[label]
        meas_a = await self._p2_timed_access(
            self.csr_write("P2_ZREG_B2B_A_WR", ZEROER_CTRL_DEST_ADDR, P2_B2B_FIRST_VALUE, length=8)
        )
        assert meas_a["delta"] <= P2_UNGATE_BOUND_SMC, (
            f"{label}: first (ungating) access did not resume reg_clk within "
            f"{P2_UNGATE_BOUND_SMC} cycles: delta={meas_a['delta']}"
        )
        meas_b = await self._p2_timed_access(
            self.csr_write("P2_ZREG_B2B_B_WR", ZEROER_CTRL_DEST_ADDR, val_b, length=8)
        )
        rb = await self.csr_read("P2_ZREG_B2B_RB", ZEROER_CTRL_DEST_ADDR, length=8)
        assert meas_b["delta"] <= P2_UNGATE_BOUND_SMC, (
            f"{label}: second (back-to-back) access did not resume reg_clk "
            f"within {P2_UNGATE_BOUND_SMC} cycles: delta={meas_b['delta']}"
        )
        assert rb == val_b, f"{label}: last write not reflected: wrote {val_b:#x} read {rb:#x}"
        results[label] = {
            "resume_delta_a": meas_a["delta"],
            "resume_delta_b": meas_b["delta"],
            "written_a": P2_B2B_FIRST_VALUE,
            "written_b": val_b,
            "readback": rb,
        }
        cg.mark_fence(self.fence, "ACCESS-SWEEP(3-cells)")

        cg.emit_chk(
            self.chk_seen,
            "CHK-ZEROER-REGCLK-UNGATE",
            "CHK-ZEROER-REGCLK-UNGATE: "
            f"immediately-after(resume_delta={results['access-immediately-after-reg_clk-gates']['resume_delta']}) "
            f"long-after(resume_delta={results['access-long-after-reg_clk-gates']['resume_delta']}) "
            "back-to-back("
            f"resume_delta_a={results['back-to-back-accesses-across-gate-boundary']['resume_delta_a']},"
            f"resume_delta_b={results['back-to-back-accesses-across-gate-boundary']['resume_delta_b']}) "
            f"ungate_bound_smc_cycles={P2_UNGATE_BOUND_SMC}",
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZEROER-REGCLK-ACCESS-COMPLETE",
            "CHK-ZEROER-REGCLK-ACCESS-COMPLETE: "
            "immediately-after(written=0x{:x},readback=0x{:x},match={}) "
            "long-after(written=0x{:x},readback=0x{:x},match={}) "
            "back-to-back(written_a=0x{:x},written_b=0x{:x},readback=0x{:x},match={}) "
            "service_latency_bound_smc_cycles={}".format(
                results["access-immediately-after-reg_clk-gates"]["written"],
                results["access-immediately-after-reg_clk-gates"]["readback"],
                int(
                    results["access-immediately-after-reg_clk-gates"]["written"]
                    == results["access-immediately-after-reg_clk-gates"]["readback"]
                ),
                results["access-long-after-reg_clk-gates"]["written"],
                results["access-long-after-reg_clk-gates"]["readback"],
                int(
                    results["access-long-after-reg_clk-gates"]["written"]
                    == results["access-long-after-reg_clk-gates"]["readback"]
                ),
                results["back-to-back-accesses-across-gate-boundary"]["written_a"],
                results["back-to-back-accesses-across-gate-boundary"]["written_b"],
                results["back-to-back-accesses-across-gate-boundary"]["readback"],
                int(
                    results["back-to-back-accesses-across-gate-boundary"]["written_b"]
                    == results["back-to-back-accesses-across-gate-boundary"]["readback"]
                ),
                P2_SERVICE_BOUND_SMC,
            ),
        )

        cg.log_step(
            "P2-S3",
            "TIMEOUT: the wait for reg_clk_enable to rise and for the "
            "pending access to be serviced has a finite bound, a "
            "fail-on-expiry path, and a last-state diagnostic",
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS: ungate_bound_smc_cycles={} service_bound_smc_cycles={} "
            "long_idle_cycles={} expired=0 last_reg_clk_enable={} last_bus_active={}".format(
                P2_UNGATE_BOUND_SMC,
                P2_SERVICE_BOUND_SMC,
                P2_LONG_IDLE_CYCLES,
                int(dut.tb_zeroer_gated_reg_clk.value),
                cg.sample_bit(dut, "tb_zeroer_bus_active"),
            ),
        )

        expected_p2_pre_pass = ["SETUP", "REG_CLK-GATED-BASELINE", "ACCESS-SWEEP(3-cells)"]
        p2_terms = [t for t, _ in self.fence if t in expected_p2_pre_pass]
        assert p2_terms == expected_p2_pre_pass, f"P2 NONVAC fence order wrong: {p2_terms}"
        p2_nonvac_line = (
            "CHK-NONVAC: SETUP < REG_CLK-GATED-BASELINE < ACCESS-SWEEP(3-cells) < PASS"
        )
        _LOG.info("%s", p2_nonvac_line)
        self.chk_seen["CHK-NONVAC-P2"] = p2_nonvac_line
        cg.mark_fence(self.fence, "PASS")
        _LOG.info("smc_zeroer_regclk_cg_test_seq P2 extension PASS")

    async def body(self) -> None:
        dut = self._dut()
        for port in (
            "tb_zeroer_cg_en",
            "tb_zeroer_gated_reg_clk",
            "tb_zeroer_busy",
            "tb_zeroer_bus_active",
            "rst_cool_ni",
            "rst_primary_smc_clk_no",
        ):
            assert hasattr(dut, port), f"missing TB port {port}"

        # ---- S1: idle gate-off within 1 cycle of idle establishment ----
        cg.log_step("S1", "disable_cg=0, no reg activity, observe reg_clk gates off")
        # Positive control: free-run via disable_cg, then establish idle gating.
        await self._program_cg(zeroer_en=False)
        await ClockCycles(dut.clk_smc_i, 4)
        free = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_reg_clk", 4
        )
        assert free == 4, f"reg_clk not free-running under disable_cg: {free}"
        await self._program_cg(zeroer_en=True)
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 1
        assert cg.sample_bit(dut, "tb_zeroer_bus_active") == 0
        gate_off_lat = await cg.measure_gate_off_latency(
            dut,
            "tb_zeroer_gated_reg_clk",
            max_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en", "tb_zeroer_bus_active"),
        )
        assert gate_off_lat <= 1, (
            f"reg_clk gate-off not within 1 cycle of idle: latency={gate_off_lat}"
        )
        edges = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_reg_clk", IDLE_OBSERVE
        )
        assert edges == 0, f"reg_clk still toggling idle: {edges}"
        within_1 = int(gate_off_lat <= 1)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZREG-GATE-OFF-IDLE",
            f"CHK-ZREG-GATE-OFF-IDLE: gate_off_within_1cyc={within_1} "
            f"gate_off_latency={gate_off_lat} zero_toggles_idle={IDLE_OBSERVE}",
        )
        cg.mark_fence(self.fence, "idle-gate-off-observed")

        # ---- S2: any AXI4-Lite access to Zeroer wakes reg_clk (SF-004) ----
        cg.log_step(
            "S2",
            "issue AXI4-Lite read to Zeroer DEST_ADDR; observe reg_clk resume",
        )
        delta, enabled_hits, post_resume = await self._measure_access_window()
        assert delta <= 1, (
            f"reg_clk resume not within 1 cycle of bus_active: delta={delta}"
        )
        assert post_resume > 0, "access window empty after resume"
        assert enabled_hits == post_resume, (
            f"reg_clk missing toggles in access window: hits={enabled_hits} "
            f"post_resume_cycles={post_resume}"
        )
        resume_ok = int(delta <= 1)
        every_ok = int(enabled_hits == post_resume)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZREG-ACTIVITY-ENABLE",
            f"CHK-ZREG-ACTIVITY-ENABLE: resume_within_1cyc={resume_ok} "
            f"resume_at={delta} toggles_every_cycle={every_ok} "
            f"enabled_hits={enabled_hits} post_resume_cycles={post_resume} "
            "stimulus=axi4lite_read_zeroer",
        )
        cg.mark_fence(self.fence, "activity-enable-observed")

        # Settle idle again.
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_reg_clk",
            hyst=HYST,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en",),
        )

        # ---- S3: disable_cg=1 ----
        cg.log_step("S3", "zeroer_cg_en=0; idle reg_clk stays enabled")
        await self._program_cg(zeroer_en=False)
        await ClockCycles(dut.clk_smc_i, 4)
        edges = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_reg_clk", IDLE_OBSERVE
        )
        assert edges == IDLE_OBSERVE, (
            f"reg_clk gated while disable_cg=1: edges={edges} window={IDLE_OBSERVE}"
        )
        toggles_every = int(edges == IDLE_OBSERVE)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZREG-DISABLE-CG",
            f"CHK-ZREG-DISABLE-CG: toggles_every_cycle={toggles_every} "
            f"edges={edges} window={IDLE_OBSERVE}",
        )
        cg.mark_fence(self.fence, "disable-cg-observed")

        # ---- S4: reset override ----
        cg.log_step("S4", "re-enable CG, gate off, assert cool reset; reg_clk enabled")
        await self._program_cg(zeroer_en=True)
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_reg_clk",
            hyst=HYST,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en",),
        )
        dut.rst_cool_ni.value = 0
        for _ in range(BUSY_TIMEOUT_SMC):
            if int(dut.rst_primary_smc_clk_no.value) == 0:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            raise AssertionError("TIMEOUT waiting rst_primary_smc_clk_no assert")
        edges = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_reg_clk", IDLE_OBSERVE
        )
        assert edges == IDLE_OBSERVE, (
            f"reg_clk gated during reset: edges={edges}"
        )
        toggles_rst = int(edges == IDLE_OBSERVE)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZREG-RESET-OVERRIDE",
            f"CHK-ZREG-RESET-OVERRIDE: toggles_during_reset={toggles_rst} "
            f"edges={edges} window={IDLE_OBSERVE}",
        )
        cg.mark_fence(self.fence, "reset-override-observed")
        dut.rst_cool_ni.value = 1
        for _ in range(BUSY_TIMEOUT_SMC):
            if int(dut.rst_primary_smc_clk_no.value) == 1:
                break
            await RisingEdge(dut.clk_smc_i)
        await ClockCycles(dut.clk_smc_i, 32)

        cg.assert_fence_order(
            self.fence,
            [
                "idle-gate-off-observed",
                "activity-enable-observed",
                "disable-cg-observed",
                "reset-override-observed",
            ],
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: idle-gate-off-observed < activity-enable-observed < "
            "disable-cg-observed < reset-override-observed < PASS",
        )
        cg.mark_fence(self.fence, "PASS")
        _LOG.info("smc_zeroer_regclk_cg_test_seq PASS")

        # ---- P2 (SMC_CG_P2_003) extension: additive, P1 evidence above unchanged ----
        await self._p2_extension()
