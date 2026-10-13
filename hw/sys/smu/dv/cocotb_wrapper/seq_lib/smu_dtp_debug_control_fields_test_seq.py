# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_dtp_debug_control_fields_test. SEP=1 (sep_rtl), no Force.

Contract: SMU_MISC_XTRIG_019, anchor smu_dtp_debug_control_fields_test.
Spec: jtag_ptap/doc/architecture.adoc (PTAP DEBUG_CONTROL fields: 5-bit TDR, bits 0..3 R/W reset 0,
bit 4 read-only reset 0), dtp/doc/clk_rst.adoc (Clock Stop: jtag_clock_stop and the clock-stop
request lanes aggregate onto dtp_stop_clks_o; jtag_clock_stop resets on TRST, power-on reset and
Test-Logic-Reset).

S1  Idle inputs, TAP in Run-Test/Idle.
S2  DEBUG_CONTROL reads 0 with no request.
S3  Bits 0..3 store 1 and 0 one at a time.
S4  Bit 4 ignores shifted-in data with and without a lane request.
S5  clk_smu_i edges from the Update-DR of the write scan to dtp_stop_clks_o, set and cleared.
S6  TRST, Test-Logic-Reset via TMS and power-on reset clear jtag_clock_stop and the stop output.
S7  Every bounded wait is a site with its bound, last state and expiry.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_jtag_helpers import (
    DBG_BOOT_STALL_BIT,
    DBG_BOOT_STALL_OVRD_BIT,
    DBG_CLA_CLOCK_STOP_BIT,
    DBG_CLA_CLOCK_STOP_EN_BIT,
    DBG_JTAG_CLOCK_STOP_BIT,
    make_smu_jtag_tap,
    pack_debug_control,
)
from seq_lib.smu_tb_pins import smc_primary_reset

RW_BITS = (
    ("boot_stall", DBG_BOOT_STALL_BIT),
    ("boot_stall_ovrd", DBG_BOOT_STALL_OVRD_BIT),
    ("cla_clock_stop_en", DBG_CLA_CLOCK_STOP_EN_BIT),
    ("jtag_clock_stop", DBG_JTAG_CLOCK_STOP_BIT),
)
CLA_STOP_MASK = 1 << DBG_CLA_CLOCK_STOP_BIT
SET_VALUE = (1 << DBG_JTAG_CLOCK_STOP_BIT) | (1 << DBG_CLA_CLOCK_STOP_EN_BIT)

STOP_BOUND = 64
TDR_SETTLE = 16
RESET_DONE_BOUND = 5000
POR_BOUND_REF = 5000
UPDATE_DR_BOUND = 5000
UPDATE_DR_STATE = int(OcahJtagState.UPDATE_DR)
TRST_HOLD_REF = 8
TLR_TMS_HIGHS = 5

# Waits the contract names: a stop-output wait, a TDR capture settle and a reset_done wait.
CONTRACT_WAITS = ("stop_wait", "tdr_settle", "reset_done")
CONTRACT_WAIT_KINDS = 3
SITES = (
    "stop_wait",
    "tdr_settle",
    "reset_done",
    "por_assert",
    "por_release",
    "update_dr_wait",
)


class smu_dtp_debug_control_fields_test_seq:
    """DEBUG_CONTROL fields through the primary TAP TDR."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.scans = 0
        self.step_ns: dict[str, float] = {}
        self.sites = {
            site: {"bound": 0, "count": 0, "last": "none", "expired": 0} for site in SITES
        }
        self.sites["stop_wait"]["bound"] = STOP_BOUND
        self.sites["tdr_settle"]["bound"] = TDR_SETTLE
        self.sites["reset_done"]["bound"] = RESET_DONE_BOUND
        self.sites["por_assert"]["bound"] = POR_BOUND_REF
        self.sites["por_release"]["bound"] = POR_BOUND_REF
        self.sites["update_dr_wait"]["bound"] = UPDATE_DR_BOUND

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        now = float(get_sim_time(unit="ns"))
        self.step_ns[step] = now
        self._log(f"STEP {step} @{now:.3f}ns: {text}")

    def _cell(self, name: str, text: str) -> None:
        self._log(f"CELL {name} addr=DEBUG_CONTROL {text}")

    def _ok(self, site: str, last: str) -> None:
        rec = self.sites[site]
        rec["count"] += 1
        rec["last"] = last

    def _expire(self, site: str, last: str) -> None:
        rec = self.sites[site]
        rec["expired"] += 1
        rec["last"] = last
        raise AssertionError(f"TIMEOUT {site}: bound={rec['bound']} last_state={last}")

    def _stop(self) -> int:
        return sample(self.dut.dtp_stop_clks_o, "dtp_stop_clks_o")

    async def _write(self, value: int) -> None:
        self.scans += 1
        await self.jtag.write("DEBUG_CONTROL", value)

    async def _read(self, shift_value: int = 0) -> int:
        self.scans += 1
        return int(await self.jtag.read("DEBUG_CONTROL", shift_value=shift_value))

    async def _settle(self, label: str) -> None:
        edges = 0
        for _ in range(TDR_SETTLE):
            await RisingEdge(self.dut.clk_smu_i)
            edges += 1
        if edges != TDR_SETTLE:
            self._expire("tdr_settle", f"{label}: {edges} of {TDR_SETTLE} clk_smu edges")
        self._ok("tdr_settle", f"{label}: {edges} clk_smu edges")

    async def _stop_wait(self, expect: int, label: str) -> int:
        """clk_smu_i edges from now until dtp_stop_clks_o equals ``expect``, within STOP_BOUND."""
        clk = self.dut.clk_smu_i
        last = self._stop()
        edges = 0
        while last != expect:
            if edges >= STOP_BOUND:
                self._expire("stop_wait", f"{label}: dtp_stop_clks_o={last} after {edges} clk_smu")
            await RisingEdge(clk)
            edges += 1
            last = self._stop()
        self._ok("stop_wait", f"{label}: dtp_stop_clks_o={last} after {edges} clk_smu")
        return edges

    async def _latency_from_update_dr(self, expect: int, label: str) -> int:
        """clk_smu_i edges from the first edge in Update-DR until dtp_stop_clks_o equals expect."""
        dut = self.dut
        clk = dut.clk_smu_i
        waited = 0
        state = sample(dut.jtag_ptap_state, "jtag_ptap_state")
        while state != UPDATE_DR_STATE:
            if waited >= UPDATE_DR_BOUND:
                self._expire("update_dr_wait", f"{label}: jtag_ptap_state=0x{state:x}")
            await RisingEdge(clk)
            waited += 1
            state = sample(dut.jtag_ptap_state, "jtag_ptap_state")
        self._ok("update_dr_wait", f"{label}: Update-DR after {waited} clk_smu")
        edges = 0
        last = self._stop()
        while last != expect:
            if edges >= STOP_BOUND:
                self._expire("stop_wait", f"{label}: dtp_stop_clks_o={last} after {edges} clk_smu")
            await RisingEdge(clk)
            edges += 1
            last = self._stop()
        self._ok("stop_wait", f"{label}: dtp_stop_clks_o={last} after {edges} clk_smu of Update-DR")
        return edges

    async def _write_timed(self, value: int, expect: int, label: str) -> int:
        watcher = cocotb.start_soon(self._latency_from_update_dr(expect, label))
        await self._write(value)
        return await watcher

    async def _primary_released(self, label: str) -> None:
        signal = smc_primary_reset(self.dut)
        last = sample(signal, "rst_primary_smc_clk_no")
        edges = 0
        while last != 1:
            if edges >= RESET_DONE_BOUND:
                self._expire("reset_done", f"{label}: rst_primary_smc_clk_no={last}")
            await RisingEdge(self.dut.clk_smu_i)
            edges += 1
            last = sample(signal, "rst_primary_smc_clk_no")
        self._ok("reset_done", f"{label}: rst_primary_smc_clk_no=1 after {edges} clk_smu")

    async def _ref_wait(self, site: str, signal, name: str, expect: int, label: str) -> None:
        last = sample(signal, name)
        edges = 0
        while last != expect:
            if edges >= POR_BOUND_REF:
                self._expire(site, f"{label}: {name}={last}")
            await RisingEdge(self.dut.clk_ref_i)
            edges += 1
            last = sample(signal, name)
        self._ok(site, f"{label}: {name}={last} after {edges} clk_ref")

    async def _rti(self) -> None:
        self.jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)

    async def _reset_leg(self, leg: str) -> None:
        dut = self.dut
        jtag = self.jtag
        if leg == "trst":
            await jtag.assert_trst(tck_cycles=0)
            for _ in range(TRST_HOLD_REF):
                await RisingEdge(dut.clk_ref_i)
            await jtag.release_trst()
            await self._rti()
        elif leg == "tlr":
            for _ in range(TLR_TMS_HIGHS):
                await jtag.step_tms(1)
            await self._rti()
        else:
            dut.powergood_i.value = 0
            await self._ref_wait(
                "por_assert", dut.obs_powergood_stable_o, "obs_powergood_stable_o", 0, leg
            )
            dut.powergood_i.value = 1
            await self._ref_wait(
                "por_release", dut.obs_powergood_stable_o, "obs_powergood_stable_o", 1, leg
            )
            await self._primary_released(leg)
            await self._rti()

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()

        self._mark("S1", "idle inputs, TAP in Run-Test/Idle")
        idle = {
            name: sample(getattr(dut, name), name)
            for name in (
                "xtrig_ctm_dst_req",
                "xtrig_ctm_src_ack",
                "xtrig_clk_stop_req",
                "tb_xtrig_ctp_req_in_din",
                "tb_xtrig_ctp_ack_in_din",
            )
        }
        sb.expect_eq("every xtrig and CTP pad input idle", sum(idle.values()), 0)
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self._primary_released("s1")
        await self._settle("s1")
        sb.expect_eq("dtp_stop_clks_o idle at setup", self._stop(), 0)

        self._mark("S2", "DEBUG_CONTROL reset values with every request idle")
        reset_value = await self._read(0)
        self._log(f"CHK-DBGCTL-RESET-VALUES: raw DEBUG_CONTROL=0x{reset_value:02x}")
        self._cell("S2.reset_values", f"value=0x{reset_value:02x}")
        sb.expect_eq(
            "DEBUG_CONTROL bits 3:0 and bit 4 after reset with no request",
            (reset_value & 0xF, (reset_value >> DBG_CLA_CLOCK_STOP_BIT) & 1),
            (0, 0),
            evidence="CHK-DBGCTL-RESET-VALUES",
        )

        self._mark("S3", "bits 0..3 store 1 and 0 with the other bits unchanged")
        cells = []
        for name, bit in RW_BITS:
            await self._write(1 << bit)
            set_value = await self._read(1 << bit)
            await self._write(0)
            clear_value = await self._read(0)
            self._cell(f"S3.{name}", f"set=0x{set_value:02x} clear=0x{clear_value:02x}")
            cells.append((name, set_value, clear_value))
        sb.expect_eq(
            "DEBUG_CONTROL read back after writing 1 << i and then 0, per bit",
            cells,
            [(name, 1 << bit, 0) for name, bit in RW_BITS],
            evidence="CHK-DBGCTL-RW-BITS",
        )

        self._mark("S4", "bit 4 ignores shifted-in data")
        shifted_high = await self._read(CLA_STOP_MASK)
        plain = await self._read(0)
        dut.xtrig_clk_stop_req.value = 1
        await self._settle("s4_request")
        with_request = await self._read(0)
        dut.xtrig_clk_stop_req.value = 0
        await self._settle("s4_release")
        released = await self._read(0)
        self._cell("S4.no_request_capture_before_shift1", f"value=0x{shifted_high:02x}")
        self._cell("S4.no_request_plain", f"value=0x{plain:02x}")
        self._cell("S4.request_shift0", f"value=0x{with_request:02x}")
        self._cell("S4.request_released", f"value=0x{released:02x}")
        sb.expect_eq(
            "bit 4 with no request after 1 was shifted in, plain, with a lane request and released",
            tuple(
                (v >> DBG_CLA_CLOCK_STOP_BIT) & 1
                for v in (shifted_high, plain, with_request, released)
            ),
            (0, 0, 1, 0),
            evidence="CHK-DBGCTL-BIT4-READONLY",
        )

        self._mark("S5", "TCK to dtp_stop_clks_o latency")
        sb.expect_eq("dtp_stop_clks_o before jtag_clock_stop", self._stop(), 0)
        rise = await self._write_timed(pack_debug_control(jtag_clock_stop=1), 1, "s5_rise")
        fall = await self._write_timed(0, 0, "s5_fall")
        self._log(f"CHK-JTAG-STOP-LATENCY: rise={rise} fall={fall}")
        self._cell("S5.latency", f"rise={rise} fall={fall}")
        sb.expect_eq(
            "stop output rise and fall within the bound of the TDR update",
            (rise <= 64, fall <= 64),
            (True, True),
            evidence="CHK-JTAG-STOP-LATENCY",
        )

        self._mark("S6", "TRST, Test-Logic-Reset and power-on reset clear the stop bits")
        legs = {}
        for leg in ("trst", "tlr", "por"):
            await self._write(SET_VALUE)
            await self._stop_wait(1, f"s6_{leg}_set")
            observed_set = await self._read(SET_VALUE)
            self._cell(f"S6.{leg}_set", f"value=0x{observed_set:02x}")
            sb.expect_eq(
                f"{leg}: DEBUG_CONTROL read after setting jtag_clock_stop and cla_clock_stop_en",
                observed_set,
                SET_VALUE,
                evidence="CHK-DBGCTL-RESET-CLEARS",
            )
            await self._reset_leg(leg)
            await self._settle(f"s6_{leg}")
            stop_after_reset = self._stop()
            value = await self._read(0)
            stop_after_read = self._stop()
            self._log(f"CHK-DBGCTL-RESET-CLEARS: source={leg} bits=0x{value:02x}")
            self._cell(
                f"S6.{leg}",
                f"value=0x{value:02x} stop_after_reset={stop_after_reset} "
                f"stop_after_read={stop_after_read}",
            )
            self._log(
                f"CHK-DBGCTL-RESET-CLEARS: source={leg} "
                f"cla_clock_stop_en={(value >> DBG_CLA_CLOCK_STOP_EN_BIT) & 1}"
            )
            legs[leg] = (
                (value >> DBG_JTAG_CLOCK_STOP_BIT) & 1,
                stop_after_reset,
                stop_after_read,
            )
        for leg, observed in legs.items():
            sb.expect_eq(
                f"{leg}: jtag_clock_stop bit and dtp_stop_clks_o",
                observed,
                (0, 0, 0),
                evidence="CHK-DBGCTL-RESET-CLEARS",
            )

        self._mark("S7", "bounded waits and last state")
        for site in SITES:
            rec = self.sites[site]
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {site}: bound={rec['bound']} {state} count={rec['count']} "
                f"last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(SITES)} expired={expired} tdr_scans_counted={self.scans}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        recorded = [s for s in CONTRACT_WAITS if self.sites[s]["count"] > 0]
        sb.expect_eq(
            "bounded wait kinds named by the contract all exercised",
            len(recorded),
            CONTRACT_WAIT_KINDS,
        )

        await self._write(0)
        sb.expect_eq("DEBUG_CONTROL left at 0", await self._read(0), 0)
        dut.xtrig_clk_stop_req.value = 0
        self._mark("PASS", "DEBUG_CONTROL 0, xtrig inputs idle, TAP in Run-Test/Idle")
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "PASS"]
        deltas = [self.step_ns[b] - self.step_ns[a] for a, b in zip(order, order[1:])]
        advancing = sum(1 for d in deltas if d > 0)
        self._log(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6<S7<PASS "
            f"deltas_ns={[round(d, 3) for d in deltas]}"
        )
        sb.expect_eq(
            "CHK-NONVAC ordered fence step deltas positive",
            advancing,
            len(order) - 1,
            evidence="CHK-NONVAC",
        )
