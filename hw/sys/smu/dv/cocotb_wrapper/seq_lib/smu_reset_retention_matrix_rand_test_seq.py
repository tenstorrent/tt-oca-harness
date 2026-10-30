# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC register retention across a cool, a cold and a warm reset, with seed-drawn patterns.

``hw/sys/smc/doc/clk_rst.adoc`` ("Reset Architecture") places ``u_reset_unit_reg`` and the
``SS_CONFIG`` and ``SS_COLD_RESET_N`` registers on ``rst_primary_smc_clk_no``, the CPU control
registers (``WDT_TIMEOUT`` among them) on the primary reset as well, and the isolation registers
and FLR counters on the stable cold reset only. The primary reset is asserted by the stable cold
and the stable cool reset (the ``rst_primary_n`` equation), and the warm reset by the primary
reset and the watchdog term (``rst_warm_n``). So a cool reset clears the configuration and CPU
control banks and keeps the isolation bank, a cold reset clears all three, and a CORE0 watchdog
warm reset keeps all three. ``SS_WARM_RESET_N`` has a reset value (all ones, ``reset_unit.rdl``)
and no domain sentence: it is graded after the cold reset, which asserts every SMC reset of the
chapter, and logged after the cool reset. Each ``isolate_req_o`` bit is the OR of
``ISOLATE_REQ_REG[i]`` and the two qualified requests ("Isolation Controls"), so a set register
bit holds the bit at 1 across a cool reset; after a cold reset it reads the OR of the register
reset values.

All three kinds run on every seed, in a drawn order. Per kind the seed draws a pattern for each
register under its writable mask, different from its reset value and from the value it holds
before the write, the ``ISOLATE_REQ_REG`` bit whose ``isolate_req_o`` lane is sampled (set in
the drawn pattern), one word of each scratch bank and its pattern, and a JTAG2AXI
operation (none, a write or a read), its target and its issue cycle before the reset trigger
(under the warm kind, after the arming access); the operation is not held in flight across the
reset.
A register whose reset value is all zeros is compared on a four-state simulator only; on
Verilator its value is printed. The scratch banks, the ``ss_reset_ctrl_o`` lanes, the target of
the operation and the SINGLE_OP capture after the reset are printed, not compared.

Every register access is a JTAG2AXI access on the SMC fabric; nothing is forced.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import NamedTuple

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    _CPU_CTRL_H,
    c_header_u32,
    cpu_ctrl_bm,
    reset_unit_u32,
    smc_addr,
    smc_indexed_addr,
    wdt_u32,
)
from seq_lib.smu_compose_helpers import hier
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    pack_single_op,
    require_jtag_tdo_resolved,
    unpack_single_op,
    wdt_unlock,
)
from seq_lib.smu_lc_export_seq import _ReadCounter
from seq_lib.smu_tb_pins import smc_primary_reset, smu_scope

COOL, COLD, WARM = "cool", "cold", "warm"
KINDS = (COOL, COLD, WARM)

# Registers of the draw: name -> (address, writable mask, reset value, bank).
CFG_BANK, ISO_BANK, CPU_BANK = "config", "isolation", "cpu_ctrl"
REGS: dict[str, tuple[int, int, int, str]] = {
    "SS_CONFIG": (
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR"),
        reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_bm"),
        reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_reset"),
        CFG_BANK,
    ),
    "SS_COLD_RESET_N": (
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR"),
        reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_bm"),
        reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_reset"),
        CFG_BANK,
    ),
    "SS_WARM_RESET_N": (
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR"),
        reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_bm"),
        reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_reset"),
        CFG_BANK,
    ),
    "ISOLATE_REQ_REG": (
        smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR"),
        reset_unit_u32("RESET_UNIT__ISOLATE_REQ_REG__ISOLATE_REQ_REG_bm"),
        reset_unit_u32("RESET_UNIT__ISOLATE_REQ_REG__ISOLATE_REQ_REG_reset"),
        ISO_BANK,
    ),
    "ISOLATE_REQ_FLR_COUNTER_VALUE": (
        smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR"),
        reset_unit_u32(
            "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_bm"
        ),
        reset_unit_u32(
            "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_reset"
        ),
        ISO_BANK,
    ),
    "WDT_TIMEOUT": (
        smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR"),
        cpu_ctrl_bm("CPU_CTRL__WDT_TIMEOUT__DATA_bm"),
        c_header_u32(_CPU_CTRL_H, "CPU_CTRL__WDT_TIMEOUT__DATA_reset"),
        CPU_BANK,
    ),
}
SS_WARM = "SS_WARM_RESET_N"
SS_COLD = "SS_COLD_RESET_N"
ISO_REG = "ISOLATE_REQ_REG"
WDT_TIMEOUT = "WDT_TIMEOUT"

# clk_rst.adoc "Reset Architecture": the banks each kind clears. SS_WARM_RESET_N has no domain
# sentence; the cold pin asserts every SMC reset of the chapter, the cool pin only the primary and
# warm resets, so it is graded under the cold kind and logged under the cool kind.
CLEARED_BANKS = {COOL: (CFG_BANK, CPU_BANK), COLD: (CFG_BANK, ISO_BANK, CPU_BANK), WARM: ()}
LOGGED_ONLY = {COOL: (SS_WARM,), COLD: (), WARM: ()}

# Targets of the operation issued before the reset: registers outside the CHK-RETMX-RESETVAL
# cells.
OP_TARGETS = ("SS_CONFIG", "ISOLATE_REQ_FLR_COUNTER_VALUE")
OP_KINDS = ("none", "write", "read")
OP_LEAD_MAX = 31

# Scratch banks, measured only: (name, indexed macro, word count).
SCRATCH_BANKS = (
    ("CPU_CTRL SCRATCH", "SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 16),
    (
        "SCRATCH_COLD_WARM SCRATCH",
        "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR",
        8,
    ),
)
SCRATCH_MASK = 0xFFFF_FFFF

# Isolation terms of clk_rst.adoc ("Isolation Controls"), at their reset values.
SMCEN_RESET = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMCEN_REG__ISOLATE_REQ_SMCEN_REG_reset")
SMC_REQ_RESET = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_reset")
ISOLATION_PIN_GPIO = 53
ISO_LANES = 32

# CORE0 watchdog arming of the warm kind (wdt.rdl CTRL bits, CMP field).
WDT_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
WDT_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
WDT_ARM_BITS = (
    wdt_u32("WDT__CTRL__WDOGRSTEN_bm")
    | wdt_u32("WDT__CTRL__WDOGENALWAYS_bm")
    | wdt_u32("WDT__CTRL__WDOGZEROCMP_bm")
)
WDT_CMP_ARMED = 0x10
# The second-stage count at a 5 ns sys clock, scaled to the period in use.
WDT_TIMEOUT_5NS_CYCLES = 16384

WARM_RESET_PATH = "u_smc.rst_warm_smc_clk_n"
NET_RELEASED = 1
NET_ASSERTED = 0

# Bounds of the waits: time for the reset edges, clk_smu_i cycles for the rest.
RESET_PULSE_REF_CYCLES = 64
ASSERT_BOUND_NS = 1_280
RELEASE_BOUND_NS = 81_920
EVENT_RISE_BOUND_NS = 980_000
EVENT_FALL_BOUND = 4096
REINIT_BOUND = 64
POST_RELEASE_SAMPLES = 64
SYNC_CYCLES = 32
J2A_POLL_LIMIT = 128
STEP_CLOCK_GAP = 2
MAX_REDRAWS = 16

EXPECTED_SITE_KINDS = {"assert": 2, "event": 2, "release": 4, "reinit": 4, "j2a": 1}
EXPECTED_SITES = sum(EXPECTED_SITE_KINDS.values())
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")


def four_state_simulator() -> bool:
    name = str(getattr(cocotb, "SIM_NAME", "") or "").lower()
    return "verilator" not in name


def _draw_word(rng: random.Random, mask: int, avoid: set[int], force: int = 0) -> tuple[int, int]:
    """A word under ``mask`` with the ``force`` bits set, outside ``avoid``; (word, redraws)."""
    for redraws in range(MAX_REDRAWS):
        word = (rng.randrange(0, mask + 1) | force) & mask
        if word not in avoid:
            return word, redraws
    raise AssertionError(f"no word under 0x{mask:x} outside {sorted(avoid)} in {MAX_REDRAWS}")


def draw_plan(seed: int, arming: int) -> dict:
    """Every drawn value of the run; ``arming`` is the warm kind's WDT_TIMEOUT count."""
    rng = random.Random(seed)
    order = list(KINDS)
    rng.shuffle(order)
    held = {name: reset for name, (_a, _m, reset, _b) in REGS.items()}
    kinds = {}
    max_redraws = 0
    for kind in order:
        iso_bit = rng.randrange(ISO_LANES)
        patterns = {}
        for name, (_addr, mask, reset, _bank) in REGS.items():
            if kind == WARM and name == WDT_TIMEOUT:
                patterns[name] = arming
                continue
            force = 1 << iso_bit if name == ISO_REG else 0
            word, redraws = _draw_word(rng, mask, {reset, held[name]}, force)
            patterns[name] = word
            max_redraws = max(max_redraws, redraws)
        op = rng.choice(OP_KINDS)
        target = rng.choice(OP_TARGETS)
        _a, tmask, treset, _b = REGS[target]
        op_value, redraws = _draw_word(rng, tmask, {treset, patterns[target]})
        max_redraws = max(max_redraws, redraws)
        lead = rng.randint(0, OP_LEAD_MAX)
        scratch = []
        used: set[int] = set()
        for _label, _macro, words in SCRATCH_BANKS:
            idx = rng.randrange(words)
            value, redraws = _draw_word(rng, SCRATCH_MASK, used | {0})
            used.add(value)
            max_redraws = max(max_redraws, redraws)
            scratch.append((idx, value))
        kinds[kind] = {
            "iso_bit": iso_bit,
            "patterns": patterns,
            "op": op,
            "target": target,
            "op_value": op_value,
            "lead": lead,
            "scratch": scratch,
        }
        for name, word in patterns.items():
            held[name] = word
    return {"order": order, "kinds": kinds, "max_redraws": max_redraws}


def expected_after(kind: str, name: str, pattern: int) -> int:
    """The model: the reset value when the bank is in the kind's domain, the pattern otherwise."""
    _addr, _mask, reset, bank = REGS[name]
    return reset if bank in CLEARED_BANKS[kind] else pattern


def iso_bit_after_cold(bit: int) -> int:
    """isolate_req_o bit after a cold reset, from the register reset values, pin held low."""
    reg = REGS[ISO_REG][2]
    return ((reg >> bit) & 1) | ((SMCEN_RESET >> bit) & 1 & SMC_REQ_RESET & 1)


class Sample(NamedTuple):
    """One clk_smu_i sample; -1 marks an unresolved level."""

    t_ps: int
    iso: int
    primary: int
    warm: int
    second: int
    ss_cold: int
    ss_warm: int


def _level(signal, bit: int | None = None) -> int:
    val = signal.value
    if hasattr(val, "is_resolvable") and not val.is_resolvable:
        return -1
    out = int(val)
    return out if bit is None else (out >> bit) & 1


class smu_reset_retention_matrix_rand_test_seq:
    """Retained and cleared SMC registers across drawn cool, cold and warm resets."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.clk = self.dut.clk_smu_i
        self.period_ns = self.cfg.smu_clk_period_ns
        self.primary = smc_primary_reset(self.dut)
        self.warm = hier(smu_scope(self.dut), WARM_RESET_PATH)
        self.arming = int(WDT_TIMEOUT_5NS_CYCLES * 5 / self.period_ns)
        if self.arming == REGS[WDT_TIMEOUT][2] or self.arming > REGS[WDT_TIMEOUT][1]:
            raise AssertionError(f"WDT_TIMEOUT arming count 0x{self.arming:x} not usable")
        self.seed = test.random_seed()
        self.plan = draw_plan(self.seed, self.arming)
        self.four_state = four_state_simulator()
        self.sites: list[dict] = []
        self.stamp_ps: dict[str, int] = {}
        self.j2a_polls: list[int] = []
        self.j2a_busy = 0
        self.j2a_last = ""
        self.results: dict[str, dict] = {}
        self.done = False

    # Access helpers.

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    def _now(self) -> int:
        return int(get_sim_time(unit="ps"))

    def _account(self, tap: _ReadCounter, what: str, status: int) -> None:
        """Record the status polls one JTAG2AXI access used; a BUSY status is an expiry."""
        self.j2a_polls.append(tap.reads)
        self.j2a_last = f"{what} status={status} polls={tap.reads}"
        if status == J2A_STATUS_BUSY:
            self.j2a_busy += 1
            raise AssertionError(
                f"TIMEOUT j2a {what}: bound={J2A_POLL_LIMIT} polls used={tap.reads} polls"
            )

    async def _rd32(self, addr: int, what: str) -> int:
        tap = _ReadCounter(self.jtag)
        status, rdata = await jtag2axi_single_read(
            tap, addr, size=SMC_DBG_AXSIZE_4B, poll_limit=J2A_POLL_LIMIT
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        self._account(tap, f"RD {what}", status)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        wstrb, beat = axi64_pack32(addr, data)
        tap = _ReadCounter(self.jtag)
        status, _ = await jtag2axi_single_write(
            tap, addr, beat, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B, poll_limit=J2A_POLL_LIMIT
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        self._account(tap, f"WR {what}", status)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def _unlock(self) -> None:
        status = await wdt_unlock(self.jtag)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock status={status}")

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.stamp_ps[step] = self._now()
        self.log.info("STEP %s @%.3fns: %s", step, self.stamp_ps[step] / 1000, text)

    def _site(self, kind: str, label: str, bound: int, used: int, last: str, met: bool) -> None:
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "unit": "clk_smu_i cycles",
                "used": used,
                "last": last,
                "expired": int(not met),
            }
        )
        if not met:
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={bound} used={used} last_state={last}"
            )

    async def _wait_until(self, kind: str, label: str, pred, bound: int, state) -> int:
        """Tick clk_smu_i until ``pred`` holds; the site is recorded with its last state."""
        used = 0
        while not pred() and used < bound:
            await RisingEdge(self.clk)
            used += 1
        self._site(kind, label, bound, used, state(), pred())
        return used

    def _cycles(self, bound_ns: int) -> int:
        return int(bound_ns / self.period_ns)

    async def _open_tap(self, label: str) -> None:
        self.jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = "tb_smc_jtag2axi_security_disable"
        await self._wait_until(
            "reinit",
            f"JTAG2AXI gate open {label}",
            lambda: self._bit(gate) == 0,
            REINIT_BOUND,
            lambda: f"{gate}={self._bit(gate)}",
        )

    def _drive_isolation_pin_low(self) -> None:
        dut = self.dut
        mask = 1 << ISOLATION_PIN_GPIO
        dut.tb_gpio_drive_val.value = int(dut.tb_gpio_drive_val.value) & ~mask
        dut.tb_gpio_drive_en.value = int(dut.tb_gpio_drive_en.value) | mask

    # Sampler of the isolation lane, the reset nets and the subsystem reset lanes.

    async def _sampler(self, bit: int, trace: list[Sample]) -> None:
        dut = self.dut
        while True:
            await RisingEdge(self.clk)
            trace.append(
                Sample(
                    self._now(),
                    _level(dut.tb_isolate_req, bit),
                    _level(self.primary),
                    _level(self.warm),
                    _level(dut.tb_smc_wdt_second_timeout),
                    _level(dut.tb_ss_cold_reset_n, bit),
                    _level(dut.tb_ss_warm_reset_n, bit),
                )
            )

    # Reset triggers.

    async def _issue_op(self, cell: dict) -> None:
        """Issue the drawn single operation without polling it."""
        if cell["op"] == "none":
            return
        addr = REGS[cell["target"]][0]
        if cell["op"] == "write":
            wstrb, beat = axi64_pack32(addr, cell["op_value"])
            raw = pack_single_op(J2A_OP_WRITE, addr, beat, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B)
        else:
            raw = pack_single_op(J2A_OP_READ, addr, 0, wstrb=0, size=SMC_DBG_AXSIZE_4B)
        await self.jtag.write("SMC_AXI_SINGLE_OP", raw)
        require_jtag_tdo_resolved(f"pre-reset {cell['op']} issue @0x{addr:08x}")

    @staticmethod
    def _first(trace: list[Sample], field: str, level: int, start: int = 0) -> int:
        for idx in range(max(start, 0), len(trace)):
            if getattr(trace[idx], field) == level:
                return idx
        return -1

    def _state(self, trace: list[Sample]):
        def last() -> str:
            if not trace:
                return "no sample"
            s = trace[-1]
            return f"primary={s.primary} warm={s.warm} second={s.second} iso={s.iso}"

        return last

    async def _pin_reset(self, kind: str, cell: dict, trace: list[Sample]) -> None:
        dut = self.dut
        await self._issue_op(cell)
        await ClockCycles(self.clk, cell["lead"] + 1)
        start = len(trace)
        if kind == COOL:
            dut.tb_cool_reset_pin.value = 1
        else:
            dut.rst_cold_ni.value = 0
        await self._wait_until(
            "assert",
            f"{kind} primary reset low",
            lambda: self._first(trace, "primary", NET_ASSERTED, start) >= 0,
            self._cycles(ASSERT_BOUND_NS),
            self._state(trace),
        )
        await ClockCycles(dut.clk_ref_i, RESET_PULSE_REF_CYCLES)
        if kind == COOL:
            dut.tb_cool_reset_pin.value = 0
        else:
            dut.rst_cold_ni.value = 1
        low = self._first(trace, "primary", NET_ASSERTED, start)
        await self._wait_until(
            "release",
            f"{kind} primary reset release",
            lambda: self._first(trace, "primary", NET_RELEASED, low) >= 0,
            self._cycles(RELEASE_BOUND_NS),
            self._state(trace),
        )

    async def _warm_reset(self, cell: dict, trace: list[Sample]) -> None:
        await self._unlock()
        await self._wr32(WDT_CMP, WDT_CMP_ARMED, "CORE0 WDT CMP")
        await self._unlock()
        start = len(trace)
        await self._wr32(WDT_CTRL, WDT_ARM_BITS, "CORE0 WDT CTRL")
        await ClockCycles(self.clk, cell["lead"] + 1)
        await self._issue_op(cell)
        state = self._state(trace)
        await self._wait_until(
            "event",
            "second timeout rise",
            lambda: self._first(trace, "second", 1, start) >= 0,
            self._cycles(EVENT_RISE_BOUND_NS),
            state,
        )
        await self._wait_until(
            "event",
            "warm reset fall",
            lambda: self._first(trace, "warm", NET_ASSERTED, start) >= 0,
            EVENT_FALL_BOUND,
            state,
        )
        fell = self._first(trace, "warm", NET_ASSERTED, start)
        rose = self._first(trace, "second", 1, start)
        await self._wait_until(
            "release",
            "warm reset release",
            lambda: self._first(trace, "warm", NET_RELEASED, fell) >= 0,
            self._cycles(RELEASE_BOUND_NS),
            state,
        )
        await self._wait_until(
            "release",
            "second timeout return",
            lambda: self._first(trace, "second", 0, rose) >= 0,
            self._cycles(RELEASE_BOUND_NS),
            state,
        )
        self.log.info(
            "OBSERVATION warm: second timeout rose %d and the warm reset fell %d clk_smu_i "
            "samples after the arming access",
            rose - start,
            fell - start,
        )

    # One kind.

    async def _run_kind(self, kind: str, cell: dict, step_prog: str, step_reset: str) -> dict:
        bit = cell["iso_bit"]
        before = {}
        for name, (addr, _mask, _reset, _bank) in REGS.items():
            await self._wr32(addr, cell["patterns"][name], name)
            before[name] = await self._rd32(addr, name)
        scratch_before = []
        for (label, macro, _words), (idx, value) in zip(SCRATCH_BANKS, cell["scratch"]):
            addr = smc_indexed_addr(macro, idx)
            await self._wr32(addr, value, f"{label}[{idx}]")
            scratch_before.append(await self._rd32(addr, f"{label}[{idx}]"))
        iso_before = _level(self.dut.tb_isolate_req, bit)
        await self._mark(
            step_prog,
            f"{kind}: every register of the draw programmed and read back, scratch written",
        )

        trace: list[Sample] = []
        sampler = cocotb.start_soon(self._sampler(bit, trace))
        if kind == WARM:
            await self._warm_reset(cell, trace)
        else:
            await self._pin_reset(kind, cell, trace)
        await ClockCycles(self.clk, POST_RELEASE_SAMPLES)
        sampler.cancel()
        await ClockCycles(self.clk, SYNC_CYCLES)
        await self._open_tap(f"after the {kind} reset")
        capt = await self.jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
        require_jtag_tdo_resolved("SINGLE_OP status after the reset")
        op_status, op_data = unpack_single_op(capt)

        after = {}
        for name, (addr, _mask, _reset, _bank) in REGS.items():
            after[name] = await self._rd32(addr, name)
        iso_after = _level(self.dut.tb_isolate_req, bit)
        scratch_after = []
        for (label, macro, _words), (idx, _value) in zip(SCRATCH_BANKS, cell["scratch"]):
            scratch_after.append(await self._rd32(smc_indexed_addr(macro, idx), f"{label}[{idx}]"))
        await self._mark(step_reset, f"{kind} reset applied, released and every register read")

        for (label, _macro, _words), (idx, value), b, a in zip(
            SCRATCH_BANKS, cell["scratch"], scratch_before, scratch_after
        ):
            self.log.info(
                "OBSERVATION %s %s[%d] written=0x%08x before=0x%08x after=0x%08x; "
                "no chapter names its domain, logged only",
                kind,
                label,
                idx,
                value,
                b,
                a,
            )
        self.log.info(
            "OBSERVATION %s pre-reset op %s target=%s value=0x%08x lead=%d clk_smu_i: SINGLE_OP "
            "capture after the reset op=%d data=0x%x, target after=0x%08x; logged only",
            kind,
            cell["op"],
            cell["target"],
            cell["op_value"],
            cell["lead"],
            op_status,
            op_data,
            after[cell["target"]],
        )
        lanes = Counter((s.ss_cold, s.ss_warm) for s in trace)
        self.log.info(
            "OBSERVATION %s ss_reset_ctrl_o lane %d (cold_reset_n, warm_reset_n) sample counts "
            "%s over %d clk_smu_i samples; logged, not compared",
            kind,
            bit,
            dict(lanes),
            len(trace),
        )
        return {
            "before": before,
            "after": after,
            "iso_before": iso_before,
            "iso_after": iso_after,
            "trace": trace,
        }

    async def run(self) -> None:
        order = self.plan["order"]
        drawn = " ".join(
            f"{k}:(iso_bit={c['iso_bit']} op={c['op']} target={c['target']} lead={c['lead']} "
            + ",".join(f"{n}=0x{v:x}" for n, v in c["patterns"].items())
            + ")"
            for k, c in ((k, self.plan["kinds"][k]) for k in order)
        )
        self.log.info(
            "SEED: RANDOM_SEED=%d drawn order=%s %s; pinned every kind on every seed, "
            "WDT_TIMEOUT=0x%x under the warm kind; four-state=%s",
            self.seed,
            order,
            drawn,
            self.arming,
            self.four_state,
        )
        await self.cfg.reset_done.wait()
        self._drive_isolation_pin_low()
        await self._open_tap("after bring-up")
        resets = {}
        for name, (addr, _mask, _reset, _bank) in REGS.items():
            resets[name] = await self._rd32(addr, name)
        self.log.info(
            "OBSERVATION reset values after the bring-up cold reset %s (header %s); the control "
            "CHK-CSR-RESET-VALUES-S2 of smu_reset_csr_access_test, logged only",
            {n: f"0x{v:08x}" for n, v in resets.items()},
            {n: f"0x{r:08x}" for n, (_a, _m, r, _b) in REGS.items()},
        )
        await self._mark("S1", "TAP open, isolation pin low, reset values read")

        steps = iter(STEPS[1:7])
        for kind in order:
            self.results[kind] = await self._run_kind(
                kind, self.plan["kinds"][kind], next(steps), next(steps)
            )
        await ClockCycles(self.clk, STEP_CLOCK_GAP)
        self.stamp_ps["S8"] = self._now()
        self.log.info("STEP S8 @%.3fns: PASS stamp", self.stamp_ps["S8"] / 1000)

        self._check_cleared()
        self._check_kept()
        self._check_resetval()
        self._check_isolate()
        self._check_integrity()
        self.done = True

    # Checks.

    def _cells(self, kind: str):
        cell = self.plan["kinds"][kind]
        res = self.results[kind]
        excluded = cell["target"] if cell["op"] != "none" else None
        for name, (_addr, _mask, reset, bank) in REGS.items():
            if name == excluded or name in LOGGED_ONLY[kind]:
                continue
            yield name, reset, bank, cell["patterns"][name], res["before"][name], res["after"][name]

    def _check_cleared(self) -> None:
        got, want, printed = {}, {}, {}
        for kind in self.plan["order"]:
            for name, reset, bank, pattern, before, after in self._cells(kind):
                if bank not in CLEARED_BANKS[kind]:
                    continue
                key = f"{kind} {name}"
                cell = (before, after, before != reset)
                if reset == 0 and not self.four_state:
                    printed[key] = cell
                    continue
                got[key] = cell
                want[key] = (pattern, reset, True)
            for name in LOGGED_ONLY[kind]:
                res = self.results[kind]
                self.log.info(
                    "OBSERVATION %s %s before=0x%08x after=0x%08x (reset value 0x%08x); no "
                    "sentence states its value after a cool reset, logged only",
                    kind,
                    name,
                    res["before"][name],
                    res["after"][name],
                    REGS[name][2],
                )
        for key, (before, after, _d) in printed.items():
            self.log.info(
                "OBSERVATION CHK-RETMX-CLEARED %s before=0x%08x after=0x%08x: all-zero reset "
                "value, compared on a four-state simulator only",
                key,
                before,
                after,
            )
        self.log.info(
            "CHK-RETMX-CLEARED: (before, after, before differs from reset) %s expected %s",
            {k: (f"0x{b:08x}", f"0x{a:08x}", d) for k, (b, a, d) in got.items()},
            {k: (f"0x{b:08x}", f"0x{a:08x}", d) for k, (b, a, d) in want.items()},
        )
        self.sb.expect_eq(
            f"CHK-RETMX-CLEARED every graded register in the drawn kind's domain reads its reset "
            f"value, drawn order={self.plan['order']}",
            got,
            want,
            evidence="CHK-RETMX-CLEARED",
        )

    def _check_kept(self) -> None:
        got, want = {}, {}
        for kind in self.plan["order"]:
            for name, reset, bank, pattern, before, after in self._cells(kind):
                if bank in CLEARED_BANKS[kind]:
                    continue
                key = f"{kind} {name}"
                got[key] = (before, after, before != reset)
                want[key] = (pattern, pattern, True)
        self.log.info(
            "CHK-RETMX-KEPT: (before, after, before differs from reset) %s expected %s",
            {k: (f"0x{b:08x}", f"0x{a:08x}", d) for k, (b, a, d) in got.items()},
            {k: (f"0x{b:08x}", f"0x{a:08x}", d) for k, (b, a, d) in want.items()},
        )
        self.sb.expect_eq(
            f"CHK-RETMX-KEPT every register outside the drawn kind's domain keeps its drawn "
            f"pattern, WDT_TIMEOUT its arming value 0x{self.arming:x} under the warm kind",
            got,
            want,
            evidence="CHK-RETMX-KEPT",
        )

    def _check_resetval(self) -> None:
        got, want = {}, {}
        for kind in (COOL, COLD):
            cell = self.plan["kinds"][kind]
            res = self.results[kind]
            excluded = cell["target"] if cell["op"] != "none" else None
            names = [SS_COLD] + ([SS_WARM] if kind == COLD else [])
            for name in names:
                if name == excluded:
                    continue
                reset = REGS[name][2]
                key = f"{kind} {name}"
                cell_val = (res["before"][name], res["after"][name])
                if reset == 0 and not self.four_state:
                    self.log.info(
                        "OBSERVATION CHK-RETMX-RESETVAL %s before=0x%08x after=0x%08x: all-zero "
                        "reset value, compared on a four-state simulator only",
                        key,
                        *cell_val,
                    )
                    continue
                got[key] = (cell_val[0] != reset, cell_val[1])
                want[key] = (True, reset)
        self.log.info("CHK-RETMX-RESETVAL: %s expected %s", got, want)
        self.sb.expect_eq(
            "CHK-RETMX-RESETVAL SS_WARM_RESET_N reads all ones after the drawn cold reset "
            "(SS_COLD_RESET_N 0 on a four-state simulator)",
            got,
            want,
            evidence="CHK-RETMX-RESETVAL",
        )

    def _check_isolate(self) -> None:
        cool = self.results[COOL]
        bit = self.plan["kinds"][COOL]["iso_bit"]
        trace = cool["trace"]
        a = next((i for i, s in enumerate(trace) if s.primary == NET_ASSERTED), -1)
        r = next((i for i in range(max(a, 0), len(trace)) if trace[i].primary == NET_RELEASED), -1)
        window = trace[a:] if a >= 0 and r >= 0 else []
        held = sum(1 for s in window if s.iso == 1)
        cool_got = (
            cool["iso_before"],
            a >= 0,
            r >= 0,
            len(trace) - r >= POST_RELEASE_SAMPLES,
            held,
            cool["iso_after"],
        )
        cool_want = (1, True, True, True, len(window), 1)
        cold = self.results[COLD]
        cbit = self.plan["kinds"][COLD]["iso_bit"]
        cold_got = (cold["iso_before"], cold["iso_after"])
        cold_want = (1, iso_bit_after_cold(cbit))
        for kind in self.plan["order"]:
            states = Counter(s.iso for s in self.results[kind]["trace"])
            self.log.info(
                "OBSERVATION %s isolate_req_o bit %d sample counts %s",
                kind,
                self.plan["kinds"][kind]["iso_bit"],
                dict(states),
            )
        self.log.info(
            "CHK-RETMX-ISOLATE-ALIVE: cool bit %d (before, assert seen, release seen, at least "
            "64 samples from the release, samples at 1, after)=%s expected %s over %d samples; "
            "cold bit %d "
            "(before, after read-back)=%s expected %s",
            bit,
            cool_got,
            cool_want,
            len(window),
            cbit,
            cold_got,
            cold_want,
        )
        self.sb.expect_eq(
            f"CHK-RETMX-ISOLATE-ALIVE drawn cool bit {bit} held at 1 on every clk_smu_i edge "
            f"through the cool reset, drawn cold bit {cbit} at the register reset OR after the "
            "cold reset",
            (cool_got, cold_got),
            (cool_want, cold_want),
            evidence="CHK-RETMX-ISOLATE-ALIVE",
        )

    @staticmethod
    def _falls(trace: list[Sample], field: str) -> int:
        """Assertions of a reset net in a trace: samples at 0 that follow a sample not at 0."""
        levels = [getattr(s, field) for s in trace]
        return sum(1 for a, b in zip(levels, levels[1:]) if a != NET_ASSERTED and b == NET_ASSERTED)

    def _check_integrity(self) -> None:
        self.sites.append(
            {
                "kind": "j2a",
                "label": f"{len(self.j2a_polls)} JTAG2AXI accesses, the most polls one used",
                "bound": J2A_POLL_LIMIT,
                "unit": "polls",
                "used": max(self.j2a_polls, default=0),
                "last": self.j2a_last,
                "expired": self.j2a_busy,
            }
        )
        for rec in self.sites:
            self.log.info(
                "TIMEOUT-PATH %s %s: bound=%d %s used=%d %s %s last=%s",
                rec["kind"],
                rec["label"],
                rec["bound"],
                rec["unit"],
                rec["used"],
                rec["unit"],
                "EXPIRED" if rec["expired"] else "ok",
                rec["last"],
            )
        expired = sum(r["expired"] for r in self.sites)
        kinds = dict(Counter(r["kind"] for r in self.sites))
        self.log.info(
            "CHK-TIMEOUT-PATHS: sites=%d expected=%d kinds=%s expiries=%d; the JTAG2AXI record "
            "counts the status polls of each access against the poll limit",
            len(self.sites),
            EXPECTED_SITES,
            kinds,
            expired,
        )
        self.sb.expect_eq("expired waits", expired, 0, evidence="CHK-TIMEOUT-PATHS")
        self.sb.expect_eq(
            "bounded wait sites per kind",
            (len(self.sites), kinds),
            (EXPECTED_SITES, EXPECTED_SITE_KINDS),
            evidence="CHK-TIMEOUT-PATHS",
        )

        stamps = [self.stamp_ps[s] for s in STEPS]
        fence = "<".join(f"{s}@{t / 1000:.1f}" for s, t in zip(STEPS, stamps))
        self.log.info("OBSERVATION sim-time fence %s (logged, not compared)", fence)
        counts = {
            k: (
                len(self.results[k]["before"]),
                len(self.results[k]["after"]),
            )
            for k in self.plan["order"]
        }
        falls = {
            k: (
                self._falls(self.results[k]["trace"], "primary"),
                self._falls(self.results[k]["trace"], "warm"),
            )
            for k in self.plan["order"]
        }
        asserted = {
            COOL: falls[COOL][0],
            COLD: falls[COLD][0],
            WARM: (falls[WARM][1], falls[WARM][0]),
        }
        self.log.info(
            "CHK-NONVAC: registers programmed and read per kind %s; (primary, warm) reset "
            "assertions in each kind's clk_smu_i trace %s",
            counts,
            falls,
        )
        self.sb.expect_eq(
            "CHK-NONVAC one primary reset assertion in the cool and the cold trace, one warm "
            "reset assertion and no primary assertion in the warm trace",
            asserted,
            {COOL: 1, COLD: 1, WARM: (1, 0)},
            evidence="CHK-NONVAC",
        )
