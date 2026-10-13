# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SS_CONFIG write-through to the ss_config_o lanes, lane by lane.

Contract SMU_MISC_COMPOSITION_006, anchor smu_ss_config_lane_drive_test.
Spec: reset_unit.rdl (SS_CONFIG 32-bit R/W reset 0, SS_CONFIG_LOCK); smc.rdl (smc_reset_unit at
SMC base + 0x2000); smu and smc port_table.adoc (ss_config_o [31:0] carries SS_CONFIG).

SS_CONFIG is written over the JTAG2AXI bridge and ss_config_o is sampled on clk_smu_i.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

SS_CONFIG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")
SS_CONFIG_LOCK = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR")

LANES = 32
ALL_ONES = 0xFFFF_FFFF
J2A_POLL_LIMIT = 128
PIN_POLL_LIMIT = 64
PIN_POLL_CYCLES = 4
# S1 reads SS_CONFIG_LOCK once, S2 writes 32 lanes, S3 writes twice and reads SS_CONFIG back.
CONTRACT_J2A_ACCESSES = 36
# One propagation wait after each of the 32 lane writes and the two S3 writes.
CONTRACT_PIN_WAITS = 34


class smu_ss_config_lane_drive_test_seq:
    """SS_CONFIG patterns written over JTAG2AXI and observed on ss_config_o."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.step_ts: dict[str, float] = {}
        self.sites = {
            "j2a": {
                "bound": f"{J2A_POLL_LIMIT} polls",
                "count": 0,
                "last": "none",
                "expired": 0,
            },
            "pin": {
                "bound": f"{PIN_POLL_LIMIT} polls of {PIN_POLL_CYCLES} clk_smu_i",
                "count": 0,
                "last": "none",
                "expired": 0,
            },
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = float(get_sim_time(unit="ns"))
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, addr: int, text: str) -> None:
        self._log(f"CELL {name} addr=0x{addr:08x} {text}")

    def _pin(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    def _j2a_done(self, label: str, addr: int, status: int) -> None:
        rec = self.sites["j2a"]
        rec["count"] += 1
        rec["last"] = f"{label} status={status}"
        require_jtag_tdo_resolved(f"J2A {label} @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {label} @0x{addr:08x} status={status}")

    def _j2a_expired(self, label: str, exc: Exception) -> None:
        rec = self.sites["j2a"]
        rec["expired"] += 1
        rec["last"] = f"EXPIRED {label} {exc}"
        self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")

    async def _rd32(self, addr: int, label: str) -> int:
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag,
                addr,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            self._j2a_expired(f"RD {label}", exc)
            raise
        self._j2a_done(f"RD {label}", addr, status)
        return axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, label: str) -> None:
        wstrb, beat = axi64_pack32(addr, data)
        try:
            status, _ = await jtag2axi_single_write(
                self.jtag,
                addr,
                beat,
                wstrb=wstrb,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            self._j2a_expired(f"WR {label}", exc)
            raise
        self._j2a_done(f"WR {label}", addr, status)

    async def _wait_pin(self, want: int, label: str) -> int:
        """Poll ss_config_o until it equals want; expiry raises with the last sample."""
        rec = self.sites["pin"]
        rec["count"] += 1
        last = None
        for polls in range(1, PIN_POLL_LIMIT + 1):
            await ClockCycles(self.dut.clk_smu_i, PIN_POLL_CYCLES)
            last = self._pin("tb_ss_config")
            if last == want:
                rec["last"] = f"{label} ss_config_o=0x{last:08x} after {polls} polls"
                return last
        rec["expired"] += 1
        rec["last"] = f"EXPIRED {label} ss_config_o=0x{last:08x} want=0x{want:08x}"
        self._log(f"TIMEOUT-PATH pin: bound={rec['bound']} {rec['last']}")
        raise AssertionError(f"ss_config_o never reached 0x{want:08x}: last=0x{last:08x}")

    async def run(self) -> None:
        sb = self.sb
        dut = self.dut
        await self.cfg.reset_done.wait()

        self._mark("S1", "SETUP: bring-up, IDCODE, J2A gate open, SS_CONFIG_LOCK open")
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._pin("tb_smc_jtag2axi_security_disable") & 1
        if gate:
            raise AssertionError("SMC JTAG2AXI gated; no CSR access can run")
        self._log(f"CELL setup idcode=0x{idcode:08x} security_disable={gate}")
        lock = await self._rd32(SS_CONFIG_LOCK, "SS_CONFIG_LOCK")
        self._cell("ss_config_lock", SS_CONFIG_LOCK, f"value=0x{lock:08x}")
        if lock != 0:
            raise AssertionError(f"SS_CONFIG_LOCK reads 0x{lock:08x}, whole word not writable")

        self._mark("S2", "write SS_CONFIG = 1 << i for i in 0..31 and sample ss_config_o")
        width = len(dut.tb_ss_config)
        if width != LANES:
            raise AssertionError(f"ss_config_o width {width}, want {LANES}")
        for i in range(LANES):
            want = 1 << i
            await self._wr32(SS_CONFIG, want, f"SS_CONFIG lane {i}")
            got = await self._wait_pin(want, f"lane {i}")
            self._cell(f"ss_config_lane_{i}", SS_CONFIG, f"ss_config_o=0x{got:08x}")
            sb.expect_eq(
                f"CHK-COMP-SS-CONFIG-SINGLE-LANE ss_config_o lane {i}",
                got,
                want,
                evidence="COMP_SS_CONFIG_SINGLE_LANE",
            )

        self._mark("S3", "write all ones then all zeros, then read SS_CONFIG back")
        await self._wr32(SS_CONFIG, ALL_ONES, "SS_CONFIG all ones")
        got = await self._wait_pin(ALL_ONES, "all ones")
        self._cell("ss_config_all_ones", SS_CONFIG, f"ss_config_o=0x{got:08x}")
        sb.expect_eq(
            "CHK-COMP-SS-CONFIG-ALL-ONES-ZERO ss_config_o all ones",
            got,
            ALL_ONES,
            evidence="COMP_SS_CONFIG_ALL_ONES_ZERO",
        )
        await self._wr32(SS_CONFIG, 0, "SS_CONFIG all zeros")
        got = await self._wait_pin(0, "all zeros")
        self._cell("ss_config_all_zeros", SS_CONFIG, f"ss_config_o=0x{got:08x}")
        sb.expect_eq(
            "CHK-COMP-SS-CONFIG-ALL-ONES-ZERO ss_config_o all zeros",
            got,
            0,
            evidence="COMP_SS_CONFIG_ALL_ONES_ZERO",
        )
        readback = await self._rd32(SS_CONFIG, "SS_CONFIG")
        self._cell("ss_config_readback", SS_CONFIG, f"value=0x{readback:08x}")
        sb.expect_eq(
            "CHK-COMP-SS-CONFIG-ALL-ONES-ZERO SS_CONFIG read back after zero write",
            readback,
            0,
            evidence="COMP_SS_CONFIG_ALL_ONES_ZERO",
        )

        self._mark("S4", "TIMEOUT: bounded waits and last state")
        for site, rec in self.sites.items():
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {site}: bound={rec['bound']} {state} count={rec['count']} "
                f"last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites.values())
        j2a = self.sites["j2a"]["count"]
        pin = self.sites["pin"]["count"]
        self._log(
            f"CHK-TIMEOUT-PATHS: expired={expired} j2a_waits={j2a} pin_waits={pin} "
            f"(contract names {CONTRACT_J2A_ACCESSES} J2A accesses + {CONTRACT_PIN_WAITS} pin waits)"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("J2A wait sites exercised", j2a, CONTRACT_J2A_ACCESSES)
        sb.expect_eq("pin wait sites exercised", pin, CONTRACT_PIN_WAITS)

        await RisingEdge(dut.clk_smu_i)
        self.step_ts["PASS"] = float(get_sim_time(unit="ns"))
        order = ["S1", "S2", "S3", "S4", "PASS"]
        deltas = [self.step_ts[b] - self.step_ts[a] for a, b in zip(order, order[1:])]
        self._log(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<PASS "
            + " ".join(f"{a}->{b}={d:.0f}ns" for a, b, d in zip(order, order[1:], deltas))
        )
        sb.expect_eq(
            "CHK-NONVAC ordered fence with positive sim-time deltas",
            [d > 0 for d in deltas],
            [True] * len(deltas),
            evidence="CHK-NONVAC",
        )
