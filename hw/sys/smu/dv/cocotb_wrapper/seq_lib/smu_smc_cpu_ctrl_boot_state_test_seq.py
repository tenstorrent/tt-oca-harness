# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL reset-state registers read through the SMC fabric JTAG2AXI bridge.

Spec: cpu_ctrl.rdl:11-18 (RESET_VECTOR), :21-88 (RESET_CTRL), :91-111 (CORE_RESET_PULSE_COUNT),
:115-124 (RESET_TIMEOUT), :164-199 (WDT_TIMEOUT, WDT_TIMEOUT_RESET), :213-221 (SCRATCH),
:224-261 (SMC_ATTRIBUTES), :300-352 (DUMMY_ROM), :358-390 (offsets); smc.rdl:89 (CPU_CTRL base);
cpu.adoc:9-10, :88; periphs.adoc SMC Peripheral Parameter Overrides; port_table.adoc:67 and the
chiplet_is_primary_i row.

SMC_ATTRIBUTES num_cpu_interrupts, no_output_remap and the upper word of each SCRATCH register
are logged and not compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import with_timeout
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import cpu_ctrl_bm, smc_addr, smc_indexed_addr, smc_indexed_stride
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    axi64_unpack32,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

_P = "SMC_TOP_SMC_CPU_CTRL_"
_C = "CPU_CTRL__"
_SCRATCH_SYMBOL = f"{_P}SCRATCH_BASE_ADDR"
SCRATCH_STRIDE = smc_indexed_stride(_SCRATCH_SYMBOL)
SCRATCH_COUNT = 16
LOW32 = 0xFFFF_FFFF

ADDR_RESET_CTRL = smc_addr(f"{_P}RESET_CTRL_BASE_ADDR")
ADDR_PULSE_COUNT = smc_addr(f"{_P}CORE_RESET_PULSE_COUNT_BASE_ADDR")
ADDR_RESET_TIMEOUT = smc_addr(f"{_P}RESET_TIMEOUT_BASE_ADDR")
ADDR_WDT_TIMEOUT = smc_addr(f"{_P}WDT_TIMEOUT_BASE_ADDR")
ADDR_WDT_TIMEOUT_RESET = smc_addr(f"{_P}WDT_TIMEOUT_RESET_BASE_ADDR")
ADDR_ATTRIBUTES = smc_addr(f"{_P}SMC_ATTRIBUTES_BASE_ADDR")
ADDR_DUMMY_ROM = [smc_addr(f"{_P}DUMMY_ROM_{i}_BASE_ADDR") for i in range(4)]
DUMMY_ROM_NULL_COUNT = 4

RESET_VECTOR = cpu_ctrl_bm(f"{_C}RESET_VECTOR__VECTOR_reset")
RESET_CTRL_FIELDS = (
    "CORE0_RESET_N_N0_SCAN",
    "CORE1_RESET_N_N0_SCAN",
    "CORE2_RESET_N_N0_SCAN",
    "CORE3_RESET_N_N0_SCAN",
    "CORE0_RESET_PULSE_START_N0_SCAN",
    "CORE1_RESET_PULSE_START_N0_SCAN",
    "CORE2_RESET_PULSE_START_N0_SCAN",
    "CORE3_RESET_PULSE_START_N0_SCAN",
    "UNCORE_RESET_N_N0_SCAN",
    "DEBUG_RESET_N_N0_SCAN",
)
PULSE_COUNT_FIELDS = ("PRE_RESET_COUNT", "POST_RESET_COUNT", "CORE_RESETS_DONE")
DUMMY_ROM_WORDS = [cpu_ctrl_bm(f"{_C}DUMMY_ROM_{i}__DUMMY_ROM_WORD_{i}_reset") for i in range(4)]

# Scenario sources: cpu.adoc:9 (four cores), cpu.adoc:10 and :88 (1 MiB = 2^20), periphs.adoc
# SMC Peripheral Parameter Overrides table (NumMailboxes 32, MailboxDepth 2), port_table.adoc:67
# (width 256), cpu_ctrl.rdl SMC_ATTRIBUTES chiplet_is_primary ("Driven by strap") and the
# port_table.adoc chiplet_is_primary_i row: the test drives the strap to primary.
ATTR_EXPECT = {
    "NUM_CORES": 4,
    "SRAM_SIZE": 20,
    "NUM_MAILBOXES": 32,
    "MAILBOX_DEPTH": 2,
    "NUM_EXT_INTERRUPTS": 256,
    "CHIPLET_IS_PRIMARY": 1,
}
ATTR_OBSERVE = ("NO_OUTPUT_REMAP", "NUM_CPU_INTERRUPTS")

J2A_POLL_LIMIT = 128
RESET_DONE_BOUND_NS = 200_000
EXPECTED_WAIT_KINDS_EXERCISED = 2


def scratch_addr(n: int) -> int:
    return smc_indexed_addr(_SCRATCH_SYMBOL, n)


def vector_addr(n: int) -> int:
    return smc_indexed_addr(f"{_P}RESET_VECTOR_BASE_ADDR", n)


def null_addr(n: int) -> int:
    return smc_indexed_addr(f"{_P}DUMMY_ROM_NULL_BASE_ADDR", n)


def _field(raw: int, mask: int) -> int:
    return (raw & mask) >> ((mask & -mask).bit_length() - 1)


def _assemble(fields: tuple[str, ...], reg: str) -> int:
    word = 0
    for f in fields:
        mask = cpu_ctrl_bm(f"{_C}{reg}__{f}_bm")
        word |= (cpu_ctrl_bm(f"{_C}{reg}__{f}_reset") << ((mask & -mask).bit_length() - 1)) & mask
    return word


RESET_CTRL_VALUE = _assemble(RESET_CTRL_FIELDS, "RESET_CTRL")
PULSE_COUNT_VALUE = _assemble(PULSE_COUNT_FIELDS, "CORE_RESET_PULSE_COUNT")
RESET_TIMEOUT_VALUE = cpu_ctrl_bm(f"{_C}RESET_TIMEOUT__TIMEOUT_VALUE_reset")
WDT_TIMEOUT_VALUE = cpu_ctrl_bm(f"{_C}WDT_TIMEOUT__DATA_reset")
WDT_TIMEOUT_RESET_VALUE = 0
for _i in range(4):
    WDT_TIMEOUT_RESET_VALUE |= (
        cpu_ctrl_bm(f"{_C}WDT_TIMEOUT_RESET__RESET_CYCLE_COUNT_{_i}_reset") << _i
    )
SCRATCH_RESET = cpu_ctrl_bm(f"{_C}SCRATCH__DATA_reset")


class smu_smc_cpu_ctrl_boot_state_test_seq:
    """Reads CPU_CTRL registers after boot and compares them with the RDL reset values."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.jtag = None
        self.j2a = 0
        self.sites = {
            "j2a": {"bound": f"{J2A_POLL_LIMIT} polls", "count": 0, "last": "none", "expired": 0},
            "reset_done": {
                "bound": f"{RESET_DONE_BOUND_NS} ns",
                "count": 0,
                "last": "none",
                "expired": 0,
            },
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, addr: int, text: str) -> None:
        self._log(f"CELL {name} addr=0x{addr:08x} {text}")

    async def _wait_reset_done(self) -> None:
        rec = self.sites["reset_done"]
        start = float(get_sim_time(unit="ns"))
        try:
            await with_timeout(self.cfg.reset_done.wait(), RESET_DONE_BOUND_NS, "ns")
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED reset_done not set {exc}"
            self._log(f"TIMEOUT-PATH reset_done: bound={rec['bound']} EXPIRED last={exc}")
            raise
        waited = float(get_sim_time(unit="ns")) - start
        rec["count"] += 1
        rec["last"] = f"reset_done set after {waited:.0f} ns"

    async def _j2a_rd(self, addr: int, size: int, label: str) -> int:
        rec = self.sites["j2a"]
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag, addr, size=size, poll_limit=J2A_POLL_LIMIT, require_complete=True
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
        return int(rdata)

    async def _rd64(self, addr: int, label: str) -> int:
        raw = await self._j2a_rd(addr, SMC_DBG_AXSIZE_8B, label)
        self._cell(label, addr, f"raw=0x{raw:016x}")
        return raw

    async def _rd32(self, addr: int, label: str) -> int:
        beat = await self._j2a_rd(addr, SMC_DBG_AXSIZE_4B, label)
        val = axi64_unpack32(addr, beat)
        self._cell(label, addr, f"raw=0x{val:08x}")
        return val

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        self._mark("S1", "SETUP: reset_done, IDCODE, J2A gate sample")
        await self._wait_reset_done()
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:08x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable:
            raise AssertionError(f"X/Z on j2a gate={gate}")
        self._cell("setup", 0, f"idcode=0x{idcode:08x} security_disable={int(gate)}")
        self.j2a = 0

        self._mark("S2", "SCRATCH[0] reset value")
        raw = await self._rd64(scratch_addr(0), "scratch0_reset_value")
        mirror = dut.smc_scratch_0_o.value
        self._log(
            "CHK-BOOT-SCRATCH0-RESET: smc_scratch_0_o="
            + (f"0x{int(mirror):08x}" if mirror.is_resolvable else str(mirror))
        )
        sb.expect_eq(
            "CHK-BOOT-SCRATCH0-RESET SCRATCH[0] bits[31:0]",
            raw & LOW32,
            SCRATCH_RESET,
            evidence="BOOT_SCRATCH0_RESET",
        )
        upper = raw >> 32
        self._log(f"CHK-BOOT-SCRATCH0-UPPER: upper=0x{upper:08x}")
        self._cell("upper_word", scratch_addr(0), f"upper=0x{upper:08x} status=SUCCESS")

        self._mark("S3", "RESET_VECTOR[0..3]")
        vectors = [await self._rd64(vector_addr(i), f"reset_vector_{i}") for i in range(4)]
        sb.expect_eq(
            "CHK-BOOT-RESET-VECTORS RESET_VECTOR[0..3]",
            vectors,
            [RESET_VECTOR] * 4,
            evidence="BOOT_RESET_VECTORS",
        )
        self._cell("reset_vector_0_to_3", vector_addr(0), f"words={[hex(v) for v in vectors]}")

        self._mark("S4", "RESET_CTRL, CORE_RESET_PULSE_COUNT, RESET_TIMEOUT")
        reset_ctrl = await self._rd64(ADDR_RESET_CTRL, "reset_ctrl_value")
        pulse = await self._rd64(ADDR_PULSE_COUNT, "pulse_count_value")
        timeout = await self._rd64(ADDR_RESET_TIMEOUT, "reset_timeout_value")
        sb.expect_eq(
            "CHK-BOOT-RESET-CTRL-VALUES RESET_CTRL, PULSE_COUNT, RESET_TIMEOUT",
            [reset_ctrl, pulse, timeout],
            [RESET_CTRL_VALUE, PULSE_COUNT_VALUE, RESET_TIMEOUT_VALUE],
            evidence="BOOT_RESET_CTRL_VALUES",
        )

        self._mark("S5", "WDT_TIMEOUT and WDT_TIMEOUT_RESET")
        wdt = await self._rd32(ADDR_WDT_TIMEOUT, "wdt_timeout_value")
        wdt_reset = await self._rd32(ADDR_WDT_TIMEOUT_RESET, "wdt_timeout_reset_value")
        sb.expect_eq(
            "CHK-BOOT-WDT-TIMEOUT-RESET WDT_TIMEOUT, WDT_TIMEOUT_RESET",
            [wdt, wdt_reset],
            [WDT_TIMEOUT_VALUE, WDT_TIMEOUT_RESET_VALUE],
            evidence="BOOT_WDT_TIMEOUT_RESET",
        )

        self._mark("S6", "SCRATCH[1..15]")
        lows = []
        for n in range(1, SCRATCH_COUNT):
            word = await self._rd64(scratch_addr(n), f"scratch_{n}")
            self._log(f"CHK-BOOT-SCRATCH-1-15: scratch_{n} upper=0x{word >> 32:08x}")
            lows.append(word & LOW32)
        sb.expect_eq(
            "CHK-BOOT-SCRATCH-1-15 SCRATCH[1..15] bits[31:0]",
            lows,
            [SCRATCH_RESET] * (SCRATCH_COUNT - 1),
            evidence="BOOT_SCRATCH_1_15",
        )
        self._cell("scratch_1_to_15", scratch_addr(1), f"lows={[hex(v) for v in lows]}")

        self._mark("S7", "SMC_ATTRIBUTES")
        attr = await self._rd64(ADDR_ATTRIBUTES, "attr_fields")
        got = {k: _field(attr, cpu_ctrl_bm(f"{_C}SMC_ATTRIBUTES__{k}_bm")) for k in ATTR_EXPECT}
        obs = {k: _field(attr, cpu_ctrl_bm(f"{_C}SMC_ATTRIBUTES__{k}_bm")) for k in ATTR_OBSERVE}
        self._log(
            f"CHK-BOOT-ATTRIBUTES: no_output_remap={obs['NO_OUTPUT_REMAP']} "
            f"num_cpu_interrupts={obs['NUM_CPU_INTERRUPTS']}"
        )
        self._cell("attr_decoded", ADDR_ATTRIBUTES, " ".join(f"{k}={v}" for k, v in got.items()))
        sb.expect_eq(
            "CHK-BOOT-ATTRIBUTES SMC_ATTRIBUTES fields",
            got,
            ATTR_EXPECT,
            evidence="BOOT_ATTRIBUTES",
        )

        self._mark("S8", "DUMMY_ROM_0..3 and DUMMY_ROM_NULL[0..3]")
        rom = [await self._rd64(ADDR_DUMMY_ROM[i], f"dummy_rom_{i}") for i in range(4)]
        null = [
            await self._rd64(null_addr(i), f"dummy_rom_null_{i}")
            for i in range(DUMMY_ROM_NULL_COUNT)
        ]
        sb.expect_eq(
            "CHK-BOOT-DUMMY-ROM DUMMY_ROM_0..3, DUMMY_ROM_NULL[0..3]",
            rom + null,
            DUMMY_ROM_WORDS + [0] * DUMMY_ROM_NULL_COUNT,
            evidence="BOOT_DUMMY_ROM",
        )
        self._cell("dummy_rom_words", ADDR_DUMMY_ROM[0], f"words={[hex(v) for v in rom + null]}")

        self._mark("S9", "TIMEOUT: bounded waits and last state")
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
            f"j2a_accesses_counted={self.j2a}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("bounded wait kinds exercised", len(lines), EXPECTED_WAIT_KINDS_EXERCISED)
        self.done = True
