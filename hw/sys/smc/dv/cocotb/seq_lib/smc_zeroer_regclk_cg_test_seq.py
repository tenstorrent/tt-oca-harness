# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_ZEROER_REGCLK_CG_TEST ANCHOR: smc_zeroer_regclk_cg_test

DV-CARD: SMC_CG_P2_003 ANCHOR: smc_zeroer_regclk_cg_test

The P2 card shares this anchor: the P1 steps and checkers run first and emit
their evidence tokens verbatim; `_p2_extension` sweeps the
pending-access-while-gated race across 3 required cells (at the gate-off
boundary with the gap to the access measured and bounded, long after gate,
back-to-back across the gate boundary), per SF-004:
register_activity asserts on any AXI4-Lite access; pending-access service must
complete within the card's own declared bounded wait (there is no separate SPEC
max-wait constant).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

from . import smc_addr_map as _addr
from . import smc_cg_obs_utils as cg
from .smc_csr_seq_utils import SmcCsrSeq

# hyst=0 so card within-1-cycle idle gate-off matches axi_cg_snoop (DENY_DELAY=1).
HYST = 0
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 256
BUSY_TIMEOUT_SMC = 256
# Bound on the frontdoor accesses that program the gate enable, from the start
# of the latency sampling task to the enable's rising edge.
ENABLE_EDGE_TIMEOUT_SMC = 256

# Authoritative map (also re-exported via smc_cg_obs_utils).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
ZEROER_CG_EN = _addr.ZEROER_CG_EN
CG_HYST_SHIFT = _addr.CG_HYST_SHIFT
CG_HYST_MASK = _addr.CG_HYST_MASK
ZEROER_CTRL_DEST_ADDR = _addr.ZEROER_CTRL_DEST_ADDR

# P2 (SMC_CG_P2_003) cells: pending-access-while-gated race sweep.
P2_LONG_IDLE_CYCLES = 40
P2_UNGATE_BOUND_SMC = 32
P2_SERVICE_BOUND_SMC = 128
# Cell 1 issues its write on the sample that shows reg_clk gated; bus_active
# then follows after the SYS AXI driver's and the fabric's issue latency, which
# no specification states. This bound is a bench fact: a gap at or beyond it
# means the access was not issued at the boundary. It stays below
# P2_LONG_IDLE_CYCLES so the cell is distinct from the long-after cell.
P2_IMMEDIATE_GAP_BOUND_SMC = 16
assert P2_IMMEDIATE_GAP_BOUND_SMC < P2_LONG_IDLE_CYCLES
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
        nxt = (cur & ~ZEROER_CG_EN & ~CG_HYST_MASK) | ((hyst << CG_HYST_SHIFT) & CG_HYST_MASK)
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
        reg_clk_enable), the per-SMC-rise enable count over the access's own
        post-resume window, and whether reg_clk_enable ever dropped again
        before the access's own bus_active window cleared. The verdict on
        those last two is applied once, at the `CHK-NONVAC-P2` site, over all
        the swept cells together."""
        dut = self._dut()
        state = {
            "active_at": -1,
            "active_ns": -1.0,
            "resume_at": -1,
            "post_resume_cycles": 0,
            "enabled_hits": 0,
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
                    state["active_ns"] = get_sim_time(unit="ns")
                    state["seen_active"] = True
                if state["active_at"] >= 0 and state["resume_at"] < 0 and gated_on:
                    state["resume_at"] = state["smc"]
                elif state["resume_at"] >= 0 and not state["done"]:
                    # Post-resume continuity window: one sample per clk_smc_i
                    # rise from the cycle after reg_clk resumed until this
                    # access's own bus_active clears. `enabled_hits` counts the
                    # samples on which reg_clk was still enabled, so the pair is
                    # the in-access half of the gated-versus-running contrast.
                    state["post_resume_cycles"] += 1
                    if gated_on:
                        state["enabled_hits"] += 1
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
        # ENFORCE the service bound that CHK-TIMEOUT-PATHS advertises
        # ([TIMEOUT-MUST-FAIL]). The wait loop above only *caps* `smc` at
        # P2_SERVICE_BOUND_SMC, so expiry alone is indistinguishable from a
        # completed access unless `done` is checked: an access whose bus_active
        # never cleared inside the bound would otherwise report `service_cycles`
        # pinned at the bound and make `service_cycles <= P2_SERVICE_BOUND_SMC`
        # unfalsifiable. The P1 twin `_measure_access_window` asserts the same
        # property (see its `assert state["done"]`).
        if not state["done"]:
            raise AssertionError(
                f"TIMEOUT: pending access was not serviced within the declared "
                f"P2_SERVICE_BOUND_SMC={P2_SERVICE_BOUND_SMC} clk_smc_i cycles "
                f"(bus_active never cleared after reg_clk resumed; "
                f"active_at={state['active_at']} resume_at={state['resume_at']} "
                f"sampled_cycles={state['smc']} "
                f"last_reg_clk_enable={int(dut.tb_zeroer_gated_reg_clk.value)} "
                f"last_bus_active={cg.sample_bit(dut, 'tb_zeroer_bus_active')})"
            )
        delta = max(0, state["resume_at"] - state["active_at"])
        # `smc` is the number of clk_smc_i cycles this access actually consumed
        # before bus_active cleared -- the MEASURED margin against
        # P2_SERVICE_BOUND_SMC, enforced by the `done` check above and
        # reported in CHK-TIMEOUT-PATHS.
        return {
            "delta": delta,
            "active_ns": state["active_ns"],
            "service_cycles": state["smc"],
            "post_resume_cycles": state["post_resume_cycles"],
            "enabled_hits": state["enabled_hits"],
            "glitch": glitch["seen"],
            "glitch_at": glitch["idx"],
        }

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
        baseline_window = 4
        p2_baseline_enabled = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_reg_clk", baseline_window
        )
        assert p2_baseline_enabled == 0, (
            f"P2 setup: reg_clk not gated at baseline: edges={p2_baseline_enabled}"
        )
        cg.mark_fence(self.fence, "REG_CLK-GATED-BASELINE")

        cg.log_step(
            "P2-S2",
            "ACTION/RESPONSE/EFFECT for SMC-CG-ZEROER-REGCLK.S1: sweep a "
            "pending register access across 3 gate-boundary timings",
        )
        results: dict[str, dict] = {}

        # Cell 1: the access issued at the gate-off boundary. A read wakes
        # reg_clk; the boundary task returns on the sample that shows the
        # clock gated again, and the write is issued from that instant. The
        # gap from that sample to the write's bus_active is measured in smc
        # cycles and bounded.
        label = "access-immediately-after-reg_clk-gates"
        val = P2_ACCESS_VALUES[label]
        boundary = cocotb.start_soon(
            cg.wait_gate_off_edge(
                dut,
                "tb_zeroer_gated_reg_clk",
                max_smc=GATE_OFF_TIMEOUT_SMC,
                diag_names=("tb_zeroer_cg_en", "tb_zeroer_bus_active"),
            )
        )
        await self.csr_read("P2_ZREG_WAKE_RD", ZEROER_CTRL_DEST_ADDR, length=8)
        gate_off_ns, _ = await boundary
        meas = await self._p2_timed_access(
            self.csr_write("P2_ZREG_IMM_WR", ZEROER_CTRL_DEST_ADDR, val, length=8)
        )
        gap = round((meas["active_ns"] - gate_off_ns) / self.cfg.smc_clk_period_ns)
        rb = await self.csr_read(
            "P2_ZREG_IMM_RB", ZEROER_CTRL_DEST_ADDR, expected=val, length=8
        )  # The `expected=` is what enforces the compare that
        # CHK-ZEROER-REGCLK-ACCESS-COMPLETE reports as `match=`: the scoreboard
        # applies an exact 64-bit comparison and raises on mismatch, so the
        # printed field describes a verdict that was actually applied
        # ([NO-ALWAYS-PASS-CHECKER]).
        assert 0 <= gap <= P2_IMMEDIATE_GAP_BOUND_SMC, (
            f"{label}: bus_active followed the gate-off sample by {gap} smc cycles, "
            f"outside [0, {P2_IMMEDIATE_GAP_BOUND_SMC}]; the access was not issued at "
            f"the gate boundary"
        )
        assert meas["delta"] <= P2_UNGATE_BOUND_SMC, (
            f"{label}: reg_clk_enable did not rise within {P2_UNGATE_BOUND_SMC} "
            f"cycles of the access: delta={meas['delta']}"
        )
        assert rb == val, f"{label}: write not reflected: wrote {val:#x} read {rb:#x}"
        results[label] = {
            "resume_delta": meas["delta"],
            "gap_after_gate_off": gap,
            "service_cycles": meas["service_cycles"],
            "post_resume_cycles": meas["post_resume_cycles"],
            "enabled_hits": meas["enabled_hits"],
            "glitch": int(meas["glitch"]),
            "glitch_at": meas["glitch_at"],
            "written": val,
            "readback": rb,
        }

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
        edges = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_reg_clk", baseline_window)
        assert edges == 0, f"{label}: reg_clk unexpectedly active during long-idle wait"
        meas = await self._p2_timed_access(
            self.csr_write("P2_ZREG_LONG_WR", ZEROER_CTRL_DEST_ADDR, val, length=8)
        )
        rb = await self.csr_read("P2_ZREG_LONG_RB", ZEROER_CTRL_DEST_ADDR, expected=val, length=8)
        assert meas["delta"] <= P2_UNGATE_BOUND_SMC, (
            f"{label}: reg_clk_enable did not rise within {P2_UNGATE_BOUND_SMC} "
            f"cycles of the access: delta={meas['delta']}"
        )
        assert rb == val, f"{label}: write not reflected: wrote {val:#x} read {rb:#x}"
        results[label] = {
            "resume_delta": meas["delta"],
            "service_cycles": meas["service_cycles"],
            "post_resume_cycles": meas["post_resume_cycles"],
            "enabled_hits": meas["enabled_hits"],
            "glitch": int(meas["glitch"]),
            "glitch_at": meas["glitch_at"],
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
        # Back-to-back: the LAST write wins, so the readback must equal val_b.
        rb = await self.csr_read("P2_ZREG_B2B_RB", ZEROER_CTRL_DEST_ADDR, expected=val_b, length=8)
        assert meas_b["delta"] <= P2_UNGATE_BOUND_SMC, (
            f"{label}: second (back-to-back) access did not resume reg_clk "
            f"within {P2_UNGATE_BOUND_SMC} cycles: delta={meas_b['delta']}"
        )
        assert rb == val_b, f"{label}: last write not reflected: wrote {val_b:#x} read {rb:#x}"
        results[label] = {
            "resume_delta_a": meas_a["delta"],
            "resume_delta_b": meas_b["delta"],
            "service_cycles_a": meas_a["service_cycles"],
            "service_cycles_b": meas_b["service_cycles"],
            "post_resume_cycles_a": meas_a["post_resume_cycles"],
            "post_resume_cycles_b": meas_b["post_resume_cycles"],
            "enabled_hits_a": meas_a["enabled_hits"],
            "enabled_hits_b": meas_b["enabled_hits"],
            "glitch": int(meas_a["glitch"] or meas_b["glitch"]),
            "glitch_at": max(meas_a["glitch_at"], meas_b["glitch_at"]),
            "written_a": P2_B2B_FIRST_VALUE,
            "written_b": val_b,
            "readback": rb,
        }
        cg.mark_fence(self.fence, "ACCESS-SWEEP(3-cells)")

        cg.emit_chk(
            self.chk_seen,
            "CHK-ZEROER-REGCLK-UNGATE",
            "CHK-ZEROER-REGCLK-UNGATE: "
            f"immediately-after(resume_delta={results['access-immediately-after-reg_clk-gates']['resume_delta']},"
            f"gap_after_gate_off_smc={results['access-immediately-after-reg_clk-gates']['gap_after_gate_off']},"
            f"gap_bound_smc={P2_IMMEDIATE_GAP_BOUND_SMC}) "
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
        # Measured margins, not a restatement of the configuration: each cell's
        # observed ungate delta against the bound that governed it, plus the
        # observed service cycles against the service bound.
        ungate_used = [
            v for r in results.values() for k, v in r.items() if k.startswith("resume_delta")
        ]
        service_used = [
            v for r in results.values() for k, v in r.items() if k.startswith("service_cycles")
        ]
        # The service bound the token reports is enforced here, over the same
        # numbers the token prints. `_p2_timed_access` raises when an access is
        # never serviced at all, but its monitor is allowed to run to
        # `P2_SERVICE_BOUND_SMC * 4` so a late completion is still diagnosed
        # rather than silently truncated -- which means the reported
        # `service_cycles` can exceed `P2_SERVICE_BOUND_SMC` and only this
        # assert makes the denominator a real bound ([TIMEOUT-MUST-FAIL]).
        assert service_used and max(service_used) <= P2_SERVICE_BOUND_SMC, (
            f"P2 pending-access service exceeded the declared bound: "
            f"service_cycles={service_used} bound={P2_SERVICE_BOUND_SMC} "
            f"smc cycles"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS: ungate_cycles_used={} max={}/{} bound "
            "(enforced per cell); service_cycles_used={} max={}/{} bound "
            "(enforced over all cells here); long_idle_cycles={} "
            "last_reg_clk_enable={} last_bus_active={}".format(
                ",".join(str(v) for v in ungate_used),
                max(ungate_used) if ungate_used else -1,
                P2_UNGATE_BOUND_SMC,
                ",".join(str(v) for v in service_used),
                max(service_used) if service_used else -1,
                P2_SERVICE_BOUND_SMC,
                P2_LONG_IDLE_CYCLES,
                int(dut.tb_zeroer_gated_reg_clk.value),
                cg.sample_bit(dut, "tb_zeroer_bus_active"),
            ),
        )

        expected_p2_pre_pass = ["SETUP", "REG_CLK-GATED-BASELINE", "ACCESS-SWEEP(3-cells)"]
        p2_fence = [(t, ts) for t, ts in self.fence if t in expected_p2_pre_pass]
        # `assert_fence_progress` requires strictly increasing simulation
        # timestamps, so a P2 phase that consumed no DUT time fails here.
        p2_times = cg.assert_fence_progress(p2_fence, expected_p2_pre_pass)
        # Loop-integrity guards: `len(results) == 3` and a non-empty
        # `resume_deltas` hold by construction over three straight-line cells
        # and catch an edit that drops a cell ([NO-ALWAYS-PASS-CHECKER]). The
        # DUT-sensitive content is the per-cell `delta <= P2_UNGATE_BOUND_SMC`
        # asserts, the three `expected=` readbacks (cell-unique values, last
        # write wins for back-to-back), the service-bound assert above, and the
        # gated-baseline versus in-access contrast below.
        assert len(results) == 3, f"P2 sweep observed {len(results)}/3 cells"
        resume_deltas = [
            v for r in results.values() for k, v in r.items() if k.startswith("resume_delta")
        ]
        assert resume_deltas, "P2 sweep recorded no reg_clk resume measurement"

        # Contrast measured on one probe (`tb_zeroer_gated_reg_clk`) across two
        # windows of the same sweep:
        #   * gated baseline -- `p2_baseline_enabled` enabled samples over a
        #     `baseline_window`-cycle window with the bus idle;
        #   * in-access -- `enabled_hits` over `post_resume_cycles` samples,
        #     from the cycle after reg_clk resumed until each access's own
        #     bus_active cleared.
        # A gater that never gates makes the baseline non-zero; a clock that
        # resumes and then re-gates mid-access makes `enabled_hits` fall short
        # of `post_resume_cycles` (and sets the `glitch` flag with the cycle
        # index).
        post_resume = [
            v for r in results.values() for k, v in r.items() if k.startswith("post_resume_cycles")
        ]
        enabled_hits = [
            v for r in results.values() for k, v in r.items() if k.startswith("enabled_hits")
        ]
        glitching = {label: r["glitch_at"] for label, r in results.items() if r["glitch"]}
        assert (
            p2_baseline_enabled == 0
            and not glitching
            and all(h == c and c > 0 for h, c in zip(enabled_hits, post_resume))
        ), (
            f"NONVAC-P2 contrast absent on tb_zeroer_gated_reg_clk: gated "
            f"baseline {p2_baseline_enabled}/{baseline_window} enabled, "
            f"in-access enabled_hits={enabled_hits} over "
            f"post_resume_cycles={post_resume}; mid-access re-gate at "
            f"{glitching or 'none'}"
        )
        p2_nonvac_line = (
            "CHK-NONVAC-P2: SETUP@{}ns < REG_CLK-GATED-BASELINE@{}ns < "
            "ACCESS-SWEEP(3-cells)@{}ns < PASS cells={} "
            "gated_baseline_enabled={}/{} in_access_enabled_hits={} over "
            "post_resume_cycles={} mid_access_regate={} "
            "resume_deltas={} max_resume_delta={}/{} bound".format(
                p2_times[0],
                p2_times[1],
                p2_times[2],
                len(results),
                p2_baseline_enabled,
                baseline_window,
                ",".join(str(v) for v in enabled_hits),
                ",".join(str(v) for v in post_resume),
                glitching or "none",
                ",".join(str(d) for d in resume_deltas),
                max(resume_deltas),
                P2_UNGATE_BOUND_SMC,
            )
        )
        cg.emit_chk(self.chk_seen, "CHK-NONVAC-P2", p2_nonvac_line)
        cg.mark_fence(self.fence, "PASS")
        cocotb.log.info("smc_zeroer_regclk_cg_test_seq P2 extension PASS")

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
        free = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_reg_clk", 4)
        assert free == 4, f"reg_clk not free-running under disable_cg: {free}"
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 0
        assert cg.sample_bit(dut, "tb_zeroer_bus_active") == 0
        # The latency origin is the enable's own rising edge on
        # tb_zeroer_cg_en: the sampling task starts before the enable write,
        # so the frontdoor accesses that program the enable cannot move it.
        gate_off = cocotb.start_soon(
            cg.measure_gate_off_from_enable(
                dut,
                "tb_zeroer_cg_en",
                "tb_zeroer_gated_reg_clk",
                enable_wait_smc=ENABLE_EDGE_TIMEOUT_SMC,
                max_smc=GATE_OFF_TIMEOUT_SMC,
                diag_names=("tb_zeroer_cg_en", "tb_zeroer_bus_active"),
            )
        )
        await self._program_cg(zeroer_en=True)
        enable_at, gate_off_lat = await gate_off
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 1
        assert gate_off_lat <= 1, (
            f"reg_clk gate-off not within 1 cycle of tb_zeroer_cg_en rising: latency={gate_off_lat}"
        )
        idle_enabled = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_reg_clk", IDLE_OBSERVE
        )
        edges = idle_enabled
        assert edges == 0, f"reg_clk still toggling idle: {edges}"
        within_1 = int(gate_off_lat <= 1)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZREG-GATE-OFF-IDLE",
            f"CHK-ZREG-GATE-OFF-IDLE: gate_off_within_1cyc={within_1} "
            f"gate_off_latency={gate_off_lat} origin=tb_zeroer_cg_en_rise "
            f"enable_edge_sample={enable_at} zero_toggles_idle={IDLE_OBSERVE}",
        )
        cg.mark_fence(self.fence, "idle-gate-off-observed")

        # ---- S2: any AXI4-Lite access to Zeroer wakes reg_clk (SF-004) ----
        cg.log_step(
            "S2",
            "issue AXI4-Lite read to Zeroer DEST_ADDR; observe reg_clk resume",
        )
        delta, enabled_hits, post_resume = await self._measure_access_window()
        assert delta <= 1, f"reg_clk resume not within 1 cycle of bus_active: delta={delta}"
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
        disable_cg_enabled = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_reg_clk", IDLE_OBSERVE
        )
        edges = disable_cg_enabled
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
        await cg.wait_reset_asserted(
            dut,
            "rst_primary_smc_clk_no",
            ref_cycles=cg.COOL_RESET_ASSERT_BOUND_REF_CYCLES,
            ref_period_ns=self.cfg.ref_clk_period_ns,
        )
        edges = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_reg_clk", IDLE_OBSERVE)
        assert edges == IDLE_OBSERVE, f"reg_clk gated during reset: edges={edges}"
        # The token carries the two measured edge counts: S4 with reset
        # asserted against S1's gated idle window, under the same cg_en=1 /
        # bus-idle programming. The fail-capable compare is the exact
        # `edges == IDLE_OBSERVE` above: a DUT that kept reg_clk gated through
        # reset returns 0 there ([NO-ALWAYS-PASS-CHECKER]).
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZREG-RESET-OVERRIDE",
            f"CHK-ZREG-RESET-OVERRIDE: reg_clk enabled edges during reset "
            f"={edges}/{IDLE_OBSERVE} (free-running), vs {idle_enabled}"
            f"/{IDLE_OBSERVE} measured in S1's gated idle window under the same "
            f"cg_en=1 / bus-idle programming -- reset assertion is the only "
            f"difference between the two windows",
        )
        cg.mark_fence(self.fence, "reset-override-observed")
        dut.rst_cool_ni.value = 1
        # Bounded AND fail-on-expiry, matching the assert twin above: a reset
        # that never deasserts must fail at the wait that expired, not later in
        # some other phase running against a DUT still held in reset
        # ([TIMEOUT-MUST-FAIL]).
        last_primary = None
        for _ in range(BUSY_TIMEOUT_SMC):
            last_primary = int(dut.rst_primary_smc_clk_no.value)
            if last_primary == 1:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            raise AssertionError(
                f"TIMEOUT waiting rst_primary_smc_clk_no to deassert after "
                f"rst_cool_ni was released: last={last_primary} bound="
                f"{BUSY_TIMEOUT_SMC} smc cycles"
            )
        await ClockCycles(dut.clk_smc_i, 32)

        # `assert_fence_progress` requires strictly increasing simulation
        # timestamps across the listed phases (order alone holds by
        # construction) and returns them for the token below.
        fence_times = cg.assert_fence_progress(
            self.fence,
            [
                "idle-gate-off-observed",
                "activity-enable-observed",
                "disable-cg-observed",
                "reset-override-observed",
            ],
        )
        # Refactor guards: `idle_enabled == 0` restates S1's assert,
        # `disable_cg_enabled == IDLE_OBSERVE` restates S3's, and
        # `post_resume > 0` / `enabled_hits == post_resume` restate S2's. They
        # fail if a refactor drops an upstream assert; the non-vacuity claim
        # rests on the measured contrast those values carry into the token:
        # idle 0/IDLE_OBSERVE against disable_cg IDLE_OBSERVE/IDLE_OBSERVE on
        # one probe.
        assert idle_enabled == 0 and disable_cg_enabled == IDLE_OBSERVE, (
            f"NONVAC contrast absent on tb_zeroer_gated_reg_clk: "
            f"idle_enabled={idle_enabled}/{IDLE_OBSERVE} "
            f"disable_cg_enabled={disable_cg_enabled}/{IDLE_OBSERVE}"
        )
        assert post_resume > 0 and enabled_hits == post_resume, (
            f"NONVAC activity-window measurement vacuous: enabled_hits="
            f"{enabled_hits} post_resume_cycles={post_resume}"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: idle-gate-off-observed@{}ns < "
            "activity-enable-observed@{}ns < disable-cg-observed@{}ns < "
            "reset-override-observed@{}ns < PASS "
            "idle_enabled={}/{} activity_enabled={}/{} disable_cg_enabled={}/{} "
            "reset_override_enabled={}/{}".format(
                fence_times[0],
                fence_times[1],
                fence_times[2],
                fence_times[3],
                idle_enabled,
                IDLE_OBSERVE,
                enabled_hits,
                post_resume,
                disable_cg_enabled,
                IDLE_OBSERVE,
                edges,
                IDLE_OBSERVE,
            ),
        )
        cg.mark_fence(self.fence, "PASS")
        cocotb.log.info("smc_zeroer_regclk_cg_test_seq PASS")

        # ---- P2 (SMC_CG_P2_003) extension ----
        await self._p2_extension()
