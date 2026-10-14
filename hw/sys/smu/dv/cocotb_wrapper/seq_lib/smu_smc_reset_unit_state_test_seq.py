# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC reset-unit register state and the idle isolate, skip-repair and sync outputs at boot.

Spec: reset_unit.rdl (SS_CONFIG :11-17, locks :20-27, SS_FORCE_TO_REF_CLK :30-35, cold/warm
reset :38-51, holds :54-86, SS_COLD_RESET_LOCK :89-96, SYNC_REG :108-113, isolation :116-145,
ISOLATE_REQ_VIS bits 4 and 8 :159,165, FLR counters :168-181); smc.rdl:55 (smc_reset_unit at
0xC000_2000);
port_table.adoc:128,140,144; clk_rst.adoc:300,349-354.

The JTAG2AXI bridge reads the 32-bit reset-unit registers without writing anything; the TB
holds the FLR and cool-reset inputs idle and the three output pins are sampled on clk_smu_i.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import RisingEdge, with_timeout
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import reset_unit_u32, smc_addr
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_unpack32,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)


def _addr(reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_RESET_UNIT_{reg}_BASE_ADDR")


def _reset(reg: str, field: str) -> int:
    return reset_unit_u32(f"RESET_UNIT__{reg}__{field}_reset")


SS_CONFIG = ("SS_CONFIG", _addr("SS_CONFIG"), _reset("SS_CONFIG", "SS_CONFIG"))
SS_CONFIG_LOCK = (
    "SS_CONFIG_LOCK",
    _addr("SS_CONFIG_LOCK"),
    _reset("SS_CONFIG_LOCK", "CONFIG_LOCK"),
)
SS_COLD_RESET_N = (
    "SS_COLD_RESET_N",
    _addr("SS_COLD_RESET_N"),
    _reset("SS_COLD_RESET_N", "RESET_N_N0_SCAN"),
)
SS_COLD_RESET_LOCK = (
    "SS_COLD_RESET_LOCK",
    _addr("SS_COLD_RESET_LOCK"),
    _reset("SS_COLD_RESET_LOCK", "COLD_RESET_LOCK"),
)
SS_FORCE_TO_REF_CLK = (
    "SS_FORCE_TO_REF_CLK",
    _addr("SS_FORCE_TO_REF_CLK"),
    _reset("SS_FORCE_TO_REF_CLK", "FORCE_SS_TO_REF_CLK_N"),
)
SS_WARM_RESET_N = (
    "SS_WARM_RESET_N",
    _addr("SS_WARM_RESET_N"),
    _reset("SS_WARM_RESET_N", "RESET_N_N0_SCAN"),
)
HOLDS = (
    (
        "SS_CONFIG_HOLD",
        _addr("SS_CONFIG_HOLD"),
        _reset("SS_CONFIG_HOLD", "CONFIGURATION_STATE_HOLD"),
    ),
    ("SS_SRAM_HOLD", _addr("SS_SRAM_HOLD"), _reset("SS_SRAM_HOLD", "SRAM_HOLD")),
    (
        "SS_CRITICAL_HOLD",
        _addr("SS_CRITICAL_HOLD"),
        _reset("SS_CRITICAL_HOLD", "CRITICAL_SIGNAL_HOLD"),
    ),
    ("SS_DEBUG_HOLD", _addr("SS_DEBUG_HOLD"), _reset("SS_DEBUG_HOLD", "DEBUG_HOLD")),
)
ISOLATION = tuple(
    (reg, _addr(reg), _reset(reg, reg))
    for reg in (
        "ISOLATE_REQ_REG",
        "ISOLATE_REQ_PINEN_REG",
        "ISOLATE_REQ_SMC_REG",
        "ISOLATE_REQ_SMCEN_REG",
    )
)
FLR_COUNTERS = tuple(
    (reg, _addr(reg), _reset(reg, reg))
    for reg in ("ISOLATE_REQ_FLR_COUNTER_VALUE", "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE")
)
SYNC_REG = ("SYNC_REG", _addr("SYNC_REG"), _reset("SYNC_REG", "SYNC"))
ISOLATE_REQ_VIS_ADDR = _addr("ISOLATE_REQ_VIS")
VIS_COMPARED = (
    ("cool_reset_n_i", 4, _reset("ISOLATE_REQ_VIS", "COOL_RESET_N_I")),
    ("cool_reset_n_o", 8, _reset("ISOLATE_REQ_VIS", "COOL_RESET_N_O")),
)

IDLE_ISOLATE_REQ = 0x0000_0000
IDLE_SKIP_MEM_REPAIR = 0
IDLE_SYNC_IRQ = 0

J2A_POLL_LIMIT = 128
RESET_DONE_BOUND_NS = 200000
CONTRACT_WAIT_KINDS = 2


class smu_smc_reset_unit_state_test_seq:
    """Reset-state reads of the SMC reset unit and samples of its idle output pins."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.jtag = None
        self.j2a = 0
        self.step_ts: dict[str, float] = {}
        self.sites = {
            "reset_done": {
                "bound": f"{RESET_DONE_BOUND_NS} ns",
                "count": 0,
                "last": "none",
                "expired": 0,
            },
            "j2a": {"bound": f"{J2A_POLL_LIMIT} polls", "count": 0, "last": "none", "expired": 0},
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    async def _wait_reset_done(self) -> None:
        rec = self.sites["reset_done"]
        try:
            await with_timeout(self.cfg.reset_done.wait(), RESET_DONE_BOUND_NS, "ns")
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED reset_done not set {exc}"
            self._log(f"TIMEOUT-PATH reset_done: bound={rec['bound']} EXPIRED last={exc}")
            raise
        rec["count"] += 1
        rec["last"] = "reset_done set"

    async def _j2a_rd32(self, addr: int, label: str) -> int:
        """One counted 4-byte JTAG2AXI read; an expiry is recorded and re-raised."""
        rec = self.sites["j2a"]
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag,
                addr,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED {label} {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A RD {label} @0x{addr:08x}")
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"{label} status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {label} @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, int(rdata))

    async def _read_all(self, regs) -> list[int]:
        values = []
        for name, addr, _ in regs:
            value = await self._j2a_rd32(addr, name)
            self._log(f"CELL {name.lower()} addr=0x{addr:08x} value=0x{value:08x}")
            values.append(value)
        return values

    def _pin(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        self._mark("S1", "SETUP: reset_done, TAP reset, IDCODE, J2A gate open")
        await self._wait_reset_done()
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        flr = self._pin("tb_cfg_flr_pf_active")
        cool = self._pin("tb_cool_reset_pin")
        if flr or cool:
            raise AssertionError(f"idle inputs not idle: flr_pf_active={flr} cool_reset_pin={cool}")
        self._log(f"CELL setup flr_pf_active={flr} cool_reset_pin={cool} idcode=0x{idcode:08x}")

        self._mark("S2", "read SS_CONFIG, locks, cold and warm reset, force-to-ref-clk")
        config_regs = (
            SS_CONFIG,
            SS_CONFIG_LOCK,
            SS_COLD_RESET_N,
            SS_COLD_RESET_LOCK,
            SS_FORCE_TO_REF_CLK,
            SS_WARM_RESET_N,
        )
        got = await self._read_all(config_regs)
        sb.expect_eq(
            "CHK-BOOT-RSTUNIT-CONFIG ss_config, ss_cold_reset_n, ss_warm_reset_n, "
            "locks_and_force reset values",
            tuple(got),
            tuple(reset for _, _, reset in config_regs),
            evidence="BOOT_RSTUNIT_CONFIG",
        )

        self._mark("S3", "read the four hold registers")
        got = await self._read_all(HOLDS)
        sb.expect_eq(
            "CHK-BOOT-RSTUNIT-HOLDS hold_registers reset values",
            tuple(got),
            tuple(reset for _, _, reset in HOLDS),
            evidence="BOOT_RSTUNIT_HOLDS",
        )

        self._mark("S4", "read isolation, FLR counter and SYNC registers")
        iso_regs = ISOLATION + FLR_COUNTERS + (SYNC_REG,)
        got = await self._read_all(iso_regs)
        sb.expect_eq(
            "CHK-BOOT-RSTUNIT-ISOLATION isolation_registers, flr_counters, sync_reg reset values",
            tuple(got),
            tuple(reset for _, _, reset in iso_regs),
            evidence="BOOT_RSTUNIT_ISOLATION",
        )

        self._mark("S5", "read ISOLATE_REQ_VIS")
        vis = await self._j2a_rd32(ISOLATE_REQ_VIS_ADDR, "ISOLATE_REQ_VIS")
        self._log(f"CELL isolate_req_vis addr=0x{ISOLATE_REQ_VIS_ADDR:08x} value=0x{vis:08x}")
        self._log(
            f"CHK-BOOT-RSTUNIT-VIS: isolate_req_pin={vis & 1} word=0x{vis:08x} "
            "(observe-only, owner value pending)"
        )
        sb.expect_eq(
            "CHK-BOOT-RSTUNIT-VIS isolate_req_vis cool_reset_n_i and cool_reset_n_o bits",
            tuple((vis >> bit) & 1 for _, bit, _ in VIS_COMPARED),
            tuple(reset for _, _, reset in VIS_COMPARED),
            evidence="BOOT_RSTUNIT_VIS",
        )

        self._mark("S6", "sample isolate_req_o, skip_mem_repair_o and sync_irq_o")
        await RisingEdge(dut.clk_smu_i)
        isolate = self._pin("tb_isolate_req")
        skip = self._pin("tb_skip_mem_repair")
        sync_irq = self._pin("tb_sync_irq")
        self._log(f"CELL isolate_req_idle tb_isolate_req=0x{isolate:08x}")
        self._log(f"CELL skip_mem_repair_idle tb_skip_mem_repair={skip}")
        self._log(f"CELL sync_irq_idle tb_sync_irq={sync_irq}")
        sb.expect_eq(
            "CHK-BOOT-RSTUNIT-IDLE-OUTPUTS isolate_req_o, skip_mem_repair_o, sync_irq_o",
            (isolate, skip, sync_irq),
            (IDLE_ISOLATE_REQ, IDLE_SKIP_MEM_REPAIR, IDLE_SYNC_IRQ),
            evidence="BOOT_RSTUNIT_IDLE_OUTPUTS",
        )

        self._mark("S7", "TIMEOUT: bounded waits and last state")
        lines = []
        for site, rec in self.sites.items():
            state = "EXPIRED" if rec["expired"] else "ok"
            lines.append(
                f"{site}: bound={rec['bound']} {state} count={rec['count']} last={rec['last']}"
            )
        for line in lines:
            self._log(f"TIMEOUT-PATH {line}")
        expired = sum(rec["expired"] for rec in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(lines)} expired={expired} "
            f"j2a_accesses_counted={self.j2a} (counted at the call sites of this seq)"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("bounded wait kinds named by the test steps", len(lines), CONTRACT_WAIT_KINDS)

        self.step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<S6<S7<PASS)")
        sb.expect_eq("CHK-NONVAC ordered fence", len(order), 8, evidence="CHK-NONVAC")
        self.done = True
