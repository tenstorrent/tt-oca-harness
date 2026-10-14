# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCTS reset state, strap-low readback and SECONDARY ignore of TIMER_START.

Spec: system_timer_octs.rdl (CTRL, TIMER_START, STATUS.MODE/RUNNING and reset values);
architecture.adoc and interface.adoc (secondary role, timer_count_o); cpu_ctrl.rdl
(SMC_ATTRIBUTES.chiplet_is_primary); port_table.adoc (chiplet_is_primary_i, timer_count_o).

The default-strap reads of SMC_ATTRIBUTES and STATUS.MODE are the control for the strap-low leg,
and a PRIMARY-mode START that runs the timer is the control for the SECONDARY hold.

32-bit CSRs at addr[2]=1 use the upper 64-bit J2A lane (wstrb 0xF0).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import cpu_ctrl_bm, smc_addr, system_timer_octs_bm
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

_OCTS = "SMC_TOP_SMC_SYSTEM_TIMER_OCTS_"
ADDR_CTRL = smc_addr(f"{_OCTS}CTRL_BASE_ADDR")
ADDR_START = smc_addr(f"{_OCTS}TIMER_START_BASE_ADDR")
ADDR_PRESET_LO = smc_addr(f"{_OCTS}TIMER_PRESET_LO_BASE_ADDR")
ADDR_PRESET_HI = smc_addr(f"{_OCTS}TIMER_PRESET_HI_BASE_ADDR")
ADDR_COUNT_LO = smc_addr(f"{_OCTS}TIMER_COUNT_LO_BASE_ADDR")
ADDR_COUNT_HI = smc_addr(f"{_OCTS}TIMER_COUNT_HI_BASE_ADDR")
ADDR_CREDIT_EXPIRED = smc_addr(f"{_OCTS}CREDIT_EXPIRED_BASE_ADDR")
ADDR_GPIO_ENABLE = smc_addr(f"{_OCTS}TIMER_GPIO_ENABLE_BASE_ADDR")
ADDR_STATUS = smc_addr(f"{_OCTS}STATUS_BASE_ADDR")
ADDR_ATTRS = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")

_P = "SYSTEM_TIMER_OCTS__"
CTRL_RESET = sum(
    system_timer_octs_bm(f"{_P}CTRL__{f}_reset") << system_timer_octs_bm(f"{_P}CTRL__{f}_bp")
    for f in ("STEP", "PULSE_WIDTH", "CREDIT_VAL")
)
STATUS_RUNNING_BM = system_timer_octs_bm(f"{_P}STATUS__RUNNING_bm")
STATUS_MODE_BM = system_timer_octs_bm(f"{_P}STATUS__MODE_bm")
STATUS_RUNNING_RESET = system_timer_octs_bm(f"{_P}STATUS__RUNNING_reset")
ATTR_PRIMARY_BM = cpu_ctrl_bm("CPU_CTRL__SMC_ATTRIBUTES__CHIPLET_IS_PRIMARY_bm")
# system_timer_octs.rdl STATUS.MODE: 0=PRIMARY (is_primary_i=1), 1=SECONDARY (is_primary_i=0).
MODE_PRIMARY = 0
MODE_SECONDARY = 1
ZERO_CELLS = (
    ("TIMER_START", ADDR_START),
    ("TIMER_PRESET_LO", ADDR_PRESET_LO),
    ("TIMER_PRESET_HI", ADDR_PRESET_HI),
    ("TIMER_COUNT_LO", ADDR_COUNT_LO),
    ("TIMER_COUNT_HI", ADDR_COUNT_HI),
    ("CREDIT_EXPIRED", ADDR_CREDIT_EXPIRED),
    ("TIMER_GPIO_ENABLE", ADDR_GPIO_ENABLE),
)

J2A_POLL_LIMIT = 128
RESET_DONE_BOUND = 5000
RESET_SAMPLER_BOUND = 4_000_000
EXPECTED_WAIT_SITES = 5
HOLD_SAMPLES = 1024
STRAP_SETTLE_CYCLES = 64
HOLD_PRESET = 0x0001_0000
MASK64 = (1 << 64) - 1


class smu_octs_reset_and_secondary_hold_test_seq:
    """OCTS reset reads, strap-low readback and the SECONDARY START hold."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.jtag = None
        self.j2a = 0
        self.sites: dict[str, dict] = {}
        self.stop_sampling = False
        self.reset_samples = 0
        self.reset_nonzero = 0
        self.reset_first_nonzero = None

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _site(self, name: str, bound: str) -> dict:
        """Return the record of a bounded wait, registering it when first entered."""
        return self.sites.setdefault(
            name, {"bound": bound, "count": 0, "last": "none", "expired": 0, "done": False}
        )

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, addr: int, text: str) -> None:
        self._log(f"CELL {name} addr=0x{addr:08x} {text}")

    def _pin(self) -> int:
        val = self.dut.tb_timer_count.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on tb_timer_count: {val}")
        return int(val) & MASK64

    async def _j2a_rd32(self, addr: int, label: str) -> int:
        rec = self._site("j2a", f"{J2A_POLL_LIMIT} polls")
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
            rec["last"] = f"EXPIRED RD {label} {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A RD {label} @0x{addr:08x}")
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"RD {label} status={status}"
        rec["done"] = True
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {label} @0x{addr:08x} status={status}")
        raw = int(rdata)
        return (raw >> 32) & 0xFFFFFFFF if addr & 0x4 else raw & 0xFFFFFFFF

    async def _j2a_wr32(self, addr: int, data: int, label: str) -> None:
        rec = self._site("j2a", f"{J2A_POLL_LIMIT} polls")
        word = data & 0xFFFFFFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        try:
            status, _ = await jtag2axi_single_write(
                self.jtag,
                addr,
                packed,
                wstrb=wstrb,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED WR {label} {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A WR {label} @0x{addr:08x}")
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"WR {label} status={status}"
        rec["done"] = True
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {label} @0x{addr:08x} status={status}")

    async def _reset_sampler(self) -> None:
        """Sample tb_timer_count each clk_smu_i until stop_sampling or the cycle bound."""
        rec = self._site("reset_pin_sampler", f"{RESET_SAMPLER_BOUND} clk_smu")
        for _ in range(RESET_SAMPLER_BOUND):
            if self.stop_sampling:
                rec["last"] = f"stopped samples={self.reset_samples}"
                rec["done"] = True
                return
            await RisingEdge(self.dut.clk_smu_i)
            value = self._pin()
            self.reset_samples += 1
            if value:
                self.reset_nonzero += 1
                if self.reset_first_nonzero is None:
                    self.reset_first_nonzero = (self.reset_samples, value)
            rec["count"] = self.reset_samples
            rec["last"] = f"samples={self.reset_samples} nonzero={self.reset_nonzero}"
        rec["expired"] += 1
        rec["last"] = f"EXPIRED samples={self.reset_samples} nonzero={self.reset_nonzero}"
        self._log(f"TIMEOUT-PATH reset_pin_sampler: EXPIRED last={rec['last']}")
        raise AssertionError(f"reset pin sampler expired: {rec['last']}")

    async def _wait_reset_done(self) -> None:
        """Poll reset_done on clk_smu_i for at most RESET_DONE_BOUND cycles."""
        rec = self._site("reset_done", f"{RESET_DONE_BOUND} clk_smu")
        for i in range(RESET_DONE_BOUND):
            if self.cfg.reset_done.is_set():
                rec["count"] = i + 1
                rec["last"] = f"reset_done set after {i} polls"
                rec["done"] = True
                return
            await RisingEdge(self.dut.clk_smu_i)
        rec["expired"] += 1
        rec["last"] = f"EXPIRED reset_done not set after {RESET_DONE_BOUND} clk_smu"
        self._log(f"TIMEOUT-PATH reset_done: EXPIRED last={rec['last']}")
        raise AssertionError(rec["last"])

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        self._mark("S1", "SETUP: bring-up, IDCODE, J2A gate open, pin sampler started")
        await self._wait_reset_done()
        sampler = cocotb.start_soon(self._reset_sampler())
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self._log(f"CELL setup idcode=0x{idcode:08x} security_disable={int(gate)}")

        self._mark("S2", "read the nine OCTS reset cells and SMC_ATTRIBUTES at the default strap")
        ctrl = await self._j2a_rd32(ADDR_CTRL, "CTRL")
        self._cell("CTRL", ADDR_CTRL, f"value=0x{ctrl:08x} want=0x{CTRL_RESET:08x}")
        sb.expect_eq("CHK-OCTSR-RESET-CSR CTRL", ctrl, CTRL_RESET, evidence="OCTSR_RESET_CSR")
        for name, addr in ZERO_CELLS:
            val = await self._j2a_rd32(addr, name)
            self._cell(name, addr, f"value=0x{val:08x}")
            sb.expect_eq(f"CHK-OCTSR-RESET-CSR {name}", val, 0, evidence="OCTSR_RESET_CSR")
        status = await self._j2a_rd32(ADDR_STATUS, "STATUS")
        self._cell("STATUS", ADDR_STATUS, f"value=0x{status:08x}")
        sb.expect_eq(
            "CHK-OCTSR-RESET-CSR STATUS.RUNNING",
            int(bool(status & STATUS_RUNNING_BM)),
            STATUS_RUNNING_RESET,
            evidence="OCTSR_RESET_CSR",
        )
        default_attrs = await self._j2a_rd32(ADDR_ATTRS, "SMC_ATTRIBUTES default strap")
        self._cell("SMC_ATTRIBUTES", ADDR_ATTRS, f"default strap value=0x{default_attrs:08x}")
        sb.expect_eq(
            "CHK-OCTSR-STRAP-LOW default strap: chiplet_is_primary and STATUS.MODE",
            (default_attrs & ATTR_PRIMARY_BM, status & STATUS_MODE_BM),
            (ATTR_PRIMARY_BM, MODE_PRIMARY),
            evidence="OCTSR_STRAP_LOW",
        )

        self._mark("S3", "timer_count_o samples since reset release are all zero")
        self._log(
            f"CHK-OCTSR-RESET-PIN: samples={self.reset_samples} nonzero={self.reset_nonzero} "
            f"first_nonzero={self.reset_first_nonzero}"
        )
        self._cell("timer_count_o", 0, f"samples={self.reset_samples} nonzero={self.reset_nonzero}")
        sb.expect_true(
            "CHK-OCTSR-RESET-PIN sampler observed cycles",
            self.reset_samples > 0,
            evidence="OCTSR_RESET_PIN",
        )
        sb.expect_eq(
            "CHK-OCTSR-RESET-PIN nonzero samples before START",
            self.reset_nonzero,
            0,
            evidence="OCTSR_RESET_PIN",
        )

        self._mark("S4", "strap low: first read logged, second read compared")
        dut.tb_chiplet_secondary.value = 1
        await ClockCycles(dut.clk_smu_i, STRAP_SETTLE_CYCLES)
        first_attrs = await self._j2a_rd32(ADDR_ATTRS, "SMC_ATTRIBUTES first")
        first_status = await self._j2a_rd32(ADDR_STATUS, "STATUS first")
        self._log(
            f"CHK-OCTSR-STRAP-LOW: first_read attrs=0x{first_attrs:08x} "
            f"chiplet_is_primary={int(bool(first_attrs & ATTR_PRIMARY_BM))} "
            f"status=0x{first_status:08x}"
        )
        await ClockCycles(dut.clk_smu_i, STRAP_SETTLE_CYCLES)
        attrs = await self._j2a_rd32(ADDR_ATTRS, "SMC_ATTRIBUTES")
        status = await self._j2a_rd32(ADDR_STATUS, "STATUS")
        self._cell("SMC_ATTRIBUTES", ADDR_ATTRS, f"value=0x{attrs:08x}")
        self._cell("STATUS", ADDR_STATUS, f"value=0x{status:08x}")
        sb.expect_eq(
            "CHK-OCTSR-STRAP-LOW SMC_ATTRIBUTES.chiplet_is_primary",
            attrs & ATTR_PRIMARY_BM,
            0,
            evidence="OCTSR_STRAP_LOW",
        )
        sb.expect_eq(
            "CHK-OCTSR-STRAP-LOW STATUS.MODE",
            status & STATUS_MODE_BM,
            MODE_SECONDARY,
            evidence="OCTSR_STRAP_LOW",
        )

        self._mark("S5", "strap low: START written, count held at zero")
        await self._j2a_wr32(ADDR_PRESET_LO, HOLD_PRESET, "TIMER_PRESET_LO")
        await self._j2a_wr32(ADDR_PRESET_HI, 0, "TIMER_PRESET_HI")
        self.stop_sampling = True
        await sampler
        self._log(
            f"CHK-OCTSR-RESET-PIN: final samples={self.reset_samples} "
            f"nonzero={self.reset_nonzero} first_nonzero={self.reset_first_nonzero}"
        )
        sb.expect_eq(
            "CHK-OCTSR-RESET-PIN final nonzero samples before START",
            self.reset_nonzero,
            0,
            evidence="OCTSR_RESET_PIN",
        )
        await self._j2a_wr32(ADDR_START, 1, "TIMER_START")
        status = await self._j2a_rd32(ADDR_STATUS, "STATUS")
        self._cell("STATUS.RUNNING", ADDR_STATUS, f"value=0x{status:08x}")
        sb.expect_eq(
            "CHK-OCTSR-SECONDARY-HOLD STATUS.RUNNING",
            int(bool(status & STATUS_RUNNING_BM)),
            0,
            evidence="OCTSR_SECONDARY_HOLD",
        )
        rec = self._site("hold_pin_sampler", f"{HOLD_SAMPLES} clk_smu")
        hold = []
        for i in range(HOLD_SAMPLES):
            await RisingEdge(dut.clk_smu_i)
            hold.append(self._pin())
            rec["count"] = i + 1
            rec["last"] = f"samples={i + 1} value=0x{hold[-1]:016x}"
        rec["done"] = True
        hold_nonzero = sum(1 for v in hold if v)
        self._log(
            f"CHK-OCTSR-SECONDARY-HOLD: samples={len(hold)} nonzero={hold_nonzero} "
            f"max=0x{max(hold):016x}"
        )
        self._cell("timer_count_o", 0, f"hold samples={len(hold)} nonzero={hold_nonzero}")
        sb.expect_eq(
            "CHK-OCTSR-SECONDARY-HOLD samples",
            len(hold),
            HOLD_SAMPLES,
            evidence="OCTSR_SECONDARY_HOLD",
        )
        sb.expect_eq(
            "CHK-OCTSR-SECONDARY-HOLD nonzero samples",
            hold_nonzero,
            0,
            evidence="OCTSR_SECONDARY_HOLD",
        )
        dut.tb_chiplet_secondary.value = 0
        self._log("CELL tb_chiplet_secondary restored=0")

        self._mark("S6", "strap high: START in PRIMARY mode runs the timer")
        await ClockCycles(dut.clk_smu_i, STRAP_SETTLE_CYCLES)
        await self._j2a_wr32(ADDR_START, 1, "TIMER_START primary")
        status = await self._j2a_rd32(ADDR_STATUS, "STATUS primary")
        self._cell("STATUS.RUNNING", ADDR_STATUS, f"primary value=0x{status:08x}")
        rec = self._site("run_pin_wait", f"{HOLD_SAMPLES} clk_smu")
        first = self._pin()
        moved = None
        for i in range(HOLD_SAMPLES):
            await RisingEdge(dut.clk_smu_i)
            value = self._pin()
            rec["count"] = i + 1
            rec["last"] = f"edges={i + 1} first=0x{first:016x} value=0x{value:016x}"
            if value != first:
                moved = value
                break
        if moved is None:
            rec["expired"] += 1
            self._log(f"TIMEOUT-PATH run_pin_wait: EXPIRED last={rec['last']}")
        rec["done"] = True
        self._cell("timer_count_o", 0, f"primary run {rec['last']}")
        sb.expect_eq(
            "CHK-OCTSR-SECONDARY-HOLD control: PRIMARY START sets RUNNING and moves timer_count_o",
            (int(bool(status & STATUS_RUNNING_BM)), moved is not None),
            (1, True),
            evidence="OCTSR_SECONDARY_HOLD",
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
        expired = sum(1 for rec in self.sites.values() if rec["expired"] or not rec["done"])
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(lines)} expired={expired} "
            f"j2a_accesses_counted={self.j2a} (counted at the call sites of this seq)"
        )
        sb.expect_eq(
            "TIMEOUT-PATH site count equals the declared waits",
            sum(1 for rec in self.sites.values() if rec["count"] > 0),
            EXPECTED_WAIT_SITES,
            evidence="CHK_TIMEOUT_PATHS",
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        self.done = True
