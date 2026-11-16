# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Runtime warm reset: the production ROM dispatches again on a second CPU reset.

Each case cold boots the production ROM, writes ``cold_scratch[7]`` through the testbench
runtime deposit after the ROM has started, and then pulses ``wdt_rst_ni_i`` alone, so the
second ROM entry is a CPU warm reset with ``rst_ni`` and ``sep_reset_n`` held released.
``+runtime_warm_case`` selects the value and the expected leg of the ``vector.S`` dispatch
(rom.adoc SEP-ROM-CPU-110 to -140): ``valid`` jumps to a ``j .`` handler, ``zero`` cold
boots, ``below`` and ``upper`` hang, ``bad_instruction`` jumps to an all-zero ICCM word
and faults, and ``one_shot_rearm`` shows that one jump consumes the slot and that a
re-armed slot is taken again.

Every warm reset lands where no CPU LSU AXI transaction is outstanding: in the cold
boot's DCCM scrub, which follows the last MMIO access of ``vector.S`` and touches only
DCCM, or at the handler's ``j .`` in ICCM. The first ROM start therefore stops inside
``vector.S``, before any C code, peripheral set-up or ``cold_scratch[0]`` verdict.

Scope limits: the reset source is the ``wdt_rst_ni`` input, not a watchdog bite, and the
interrupted code is the ROM's own cold boot, not a BL1 image.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from rom_fw.sep_warm_dispatch_base import (
    COLD_POISON,
    RANGE_BASE,
    RANGE_END,
    STATUS_BOOTROM_START,
    STATUS_GENERAL_EXCEPTION,
    STATUS_PRESTART_DONE,
    STATUS_WARM_HANG,
    STATUS_WARM_JUMP,
    VERDICT_FAIL,
    sep_warm_dispatch_base,
)
from sep_reg_meta import sym

# +sep_iccm_word puts `j .` here for the cases that need a handler.
_HANDLER = RANGE_BASE + 0x100
_HANDLER_INSN = 0x0000_006F
# In range and away from the handler, so ICCM keeps its all-zero default there.
_BAD_TARGET = RANGE_BASE + 0x200
_MCAUSE_ILLEGAL_INSN = 0x0000_0002

_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
_SRAM_END = _SRAM_BASE + sym("SEP_SRAM_MEM_SIZE")

# `sw zero, 0(t0)`: the DCCM scrub store of vector.S, the cold boot's first DCCM access.
_SW_ZERO_T0 = 0x0002_A023
# The scrub loop is `sw zero; addi; bltu`.
_SCRUB_LOOP_BYTES = 12

_WORD = 0xFFFF_FFFF

# Bounds on event waits, not settle times.
_BOOT_LIMIT = 400_000
_DECISION_LIMIT = 200_000
_HANDSHAKE_LIMIT = 64
# The scrub loop stores to DCCM within a few instructions of its first PC.
_SCRUB_PROBE_LIMIT = 256
_RESET_EDGE_LIMIT = 4_096
# wdt_rst_ni_i stays low this many clk_i cycles after sep_cpu_reset_n falls.
_WARM_HOLD_CYCLES = 4

_ROM_SYMBOLS = ("_start", "warm_reset_hang", "cold_boot", "trap_vector_early", "trap_vector")


@dataclass(frozen=True)
class _Case:
    value: int
    # Pulse tcm_load_i so +sep_iccm_word places the handler.
    handler: bool


_CASES = {
    "valid": _Case(_HANDLER, True),
    "zero": _Case(0, False),
    # The largest address below ICCM; it is also above the SEP SRAM window.
    "below": _Case(RANGE_BASE - 4, False),
    "upper": _Case(RANGE_END, False),
    "bad_instruction": _Case(_BAD_TARGET, False),
    "one_shot_rearm": _Case(_HANDLER, True),
}


def _hx(values) -> list[str]:
    return [hex(v) for v in values]


def _rom_symbols(build_dir: str) -> dict[str, int]:
    path = os.path.join(build_dir, "boot_rom.sym")
    out: dict[str, int] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 3:
                out[parts[2]] = int(parts[0], 16)
    missing = [name for name in _ROM_SYMBOLS if name not in out]
    assert not missing, f"{path} has no {missing}; rebuild the production ROM"
    return out


@dataclass
class _Epoch:
    """One run of the CPU between two sep_cpu_reset_n edges.

    The sequences hold (cycle, value) for every change after the reset release; the
    ``*_start`` values are what the register held at the release.
    """

    index: int
    start: int
    status_start: int
    cold7_start: int
    verdict_start: int
    status: list[tuple[int, int]] = field(default_factory=list)
    cold7: list[tuple[int, int]] = field(default_factory=list)
    verdict: list[tuple[int, int]] = field(default_factory=list)
    first_pc: int | None = None
    # PC -> cycle of its first retirement.
    pcs: dict[int, int] = field(default_factory=dict)
    last_pc: int | None = None
    retired: int = 0
    dccm_first: int | None = None
    scrub_pc: int | None = None
    fall: int | None = None
    pc_at_fall: int | None = None

    @staticmethod
    def vals(seq: list[tuple[int, int]]) -> list[int]:
        return [v for _, v in seq]


class _EpochMonitor:
    """Sample the scratch words, the trace port and the resets on every clk_i edge."""

    def __init__(self, test: sep_warm_dispatch_base, cold_lo: int, cold_hi: int) -> None:
        self._test = test
        self._cold_lo = cold_lo
        self._cold_hi = cold_hi
        self.cycle = 0
        self.epochs: list[_Epoch] = []
        self.retired_in_reset = 0
        self.sep_reset_low = 0
        self.cold_reset_low = 0

    async def run(self) -> None:
        dut = cocotb.top
        rd = self._test.rd
        prev_cpu_rst = 0
        while True:
            await RisingEdge(dut.clk_i)
            self.cycle += 1
            if rd(dut.rst_ni, allow_unknown=True) != 1:
                if self.epochs:
                    self.cold_reset_low += 1
                prev_cpu_rst = 0
                continue
            cpu_rst = rd(dut.sep_cpu_reset_n_o)
            if not cpu_rst:
                if prev_cpu_rst and self.epochs:
                    ep = self.epochs[-1]
                    ep.fall = self.cycle
                    ep.pc_at_fall = ep.last_pc
                if self.epochs:
                    self.retired_in_reset += rd(dut.cpu_trace_valid_o)
                    self.sep_reset_low += 1 - rd(dut.dbg_sep_reset_n_o)
                prev_cpu_rst = 0
                continue
            probe = rd(dut.scratch_cold_probe_o)
            status = (probe >> 32) & _WORD
            cold7 = (probe >> 224) & _WORD
            verdict = probe & _WORD
            if not prev_cpu_rst:
                self.epochs.append(_Epoch(len(self.epochs), self.cycle, status, cold7, verdict))
            prev_cpu_rst = 1
            ep = self.epochs[-1]
            for seq, start, value in (
                (ep.status, ep.status_start, status),
                (ep.cold7, ep.cold7_start, cold7),
                (ep.verdict, ep.verdict_start, verdict),
            ):
                if value != (seq[-1][1] if seq else start):
                    seq.append((self.cycle, value))
            if rd(dut.cpu_trace_valid_o):
                # cpu_trace_addr_o is already a byte PC.
                pc = rd(dut.cpu_trace_addr_o)
                insn = rd(dut.cpu_trace_insn_o)
                ep.retired += 1
                ep.last_pc = pc
                ep.pcs.setdefault(pc, self.cycle)
                if ep.first_pc is None:
                    ep.first_pc = pc
                if (
                    ep.scrub_pc is None
                    and insn == _SW_ZERO_T0
                    and self._cold_lo <= pc < self._cold_hi
                ):
                    ep.scrub_pc = pc
            if ep.dccm_first is None and rd(dut.dbg_dccm_active_o):
                ep.dccm_first = self.cycle

    def summary(self) -> str:
        if not self.epochs:
            return "the CPU never left reset"
        ep = self.epochs[-1]
        last = "none" if ep.last_pc is None else hex(ep.last_pc)
        return (
            f"epoch {ep.index}: cold_scratch[1] {_hx(ep.vals(ep.status))} from "
            f"0x{ep.status_start:08x}, cold_scratch[7] {_hx(ep.vals(ep.cold7))} from "
            f"0x{ep.cold7_start:08x}, retired {ep.retired}, last PC {last}"
        )


@pyuvm.test()
class sep_runtime_warm_dispatch_test(sep_warm_dispatch_base):
    """Arm cold_scratch[7] after the ROM has started; prove the second dispatch."""

    # The base then refuses +sep_cold_scratch7: the first start must read the reset value.
    seed = None

    async def run_scenario(self) -> None:
        name = cocotb.plusargs.get("runtime_warm_case")
        assert name in _CASES, f"+runtime_warm_case={name!r}; expected one of {sorted(_CASES)}"
        case = _CASES[name]
        self.logger.info("CHK-CASE: runtime warm case %s, value 0x%08x", name, case.value)
        assert cocotb.plusargs.get("sep_cold_scratch7") is None, (
            "+sep_cold_scratch7 is set: this test arms cold_scratch[7] only through the "
            "runtime deposit; remove the plusarg from the testlist entry"
        )
        self._check_stimulus(name, case)
        self.stage_tcm = case.handler

        syms = _rom_symbols(self.rom_build_dir)
        self._rom_sym = syms
        assert syms["_start"] == sym("SEP_BOOT_ROM_MEM_BASE_ADDR"), (
            f"ROM _start 0x{syms['_start']:08x} is not the Boot ROM base "
            f"0x{sym('SEP_BOOT_ROM_MEM_BASE_ADDR'):08x}; the ROM build does not match the map"
        )
        self._mon = _EpochMonitor(self, syms["cold_boot"], syms["trap_vector_early"])
        cocotb.start_soon(self._mon.run())

        self._console = await self.bring_up_to_dispatch()
        first = await self._cold_boot_to_scrub(0)
        assert first.cold7_start == 0, (
            f"cold_scratch[7] read 0x{first.cold7_start:08x} at the first CPU release, not "
            f"its cold reset value 0: something armed the slot before the ROM started"
        )
        self.logger.info(
            "CHK-RUNTIME-WARM-FIRST-START PASS: first PC 0x%08x (_start), cold_scratch[7] "
            "0x0 -> 0x%08x, cold_scratch[1] %s, DCCM scrub entered at 0x%08x",
            first.first_pc,
            COLD_POISON,
            _hx(first.vals(first.status)),
            first.scrub_pc,
        )
        await getattr(self, f"_run_{name}")(case.value, first)

    def _check_stimulus(self, name: str, case: _Case) -> None:
        iccm_word = cocotb.plusargs.get("sep_iccm_word")
        if case.handler:
            assert iccm_word is not None, (
                f"+sep_iccm_word is not set: case {name} needs `j .` at 0x{_HANDLER:08x}; "
                f"add +sep_iccm_word={_HANDLER:08X}:{_HANDLER_INSN:08x}"
            )
            addr, _, data = str(iccm_word).partition(":")
            assert (int(addr, 16), int(data or "0", 16)) == (_HANDLER, _HANDLER_INSN), (
                f"+sep_iccm_word={iccm_word} does not place `j .` (0x{_HANDLER_INSN:08x}) "
                f"at the handler 0x{_HANDLER:08x}"
            )
        else:
            assert iccm_word is None, (
                f"+sep_iccm_word={iccm_word} is set, but case {name} stages no ICCM image; "
                f"remove it from the testlist entry"
            )
        v = case.value
        if v:
            assert v != COLD_POISON, (
                f"0x{v:08x} is cold_boot's own poison; a cold boot would leave the same value"
            )
        if name in ("valid", "one_shot_rearm", "bad_instruction"):
            assert RANGE_BASE <= v < RANGE_END and v % 4 == 0, (
                f"0x{v:08x} is not an aligned ICCM address; the range check would not accept it"
            )
        if name == "bad_instruction":
            assert v != _HANDLER, "the bad target must not be the address +sep_iccm_word fills"
        if name == "below":
            assert v == RANGE_BASE - 4 and not _SRAM_BASE <= v < _SRAM_END, (
                f"0x{v:08x} is not the last word below ICCM outside the SEP SRAM window"
            )
        if name == "upper":
            assert v == RANGE_END, f"0x{v:08x} is not the ICCM end 0x{RANGE_END:08x}"

    def _assert_console_alive(self) -> None:
        assert not self.console_task.done(), (
            "the console decoder stopped before the check, so an empty console proves nothing"
        )

    def _cold7(self) -> int:
        return (self.rd(cocotb.top.scratch_cold_probe_o) >> 224) & _WORD

    async def _wait_for(self, cond, what: str, limit: int) -> None:
        clk = cocotb.top.clk_i
        for _ in range(limit):
            if cond():
                return
            await RisingEdge(clk)
        assert cond(), f"{what} did not happen within {limit} clk_i cycles; {self._mon.summary()}"

    @staticmethod
    def _scrub_loop(ep: _Epoch) -> set[int]:
        return set(range(ep.scrub_pc, ep.scrub_pc + _SCRUB_LOOP_BYTES, 4))

    async def _cold_boot_to_scrub(self, index: int) -> _Epoch:
        """Wait for epoch ``index`` to reach the DCCM scrub and grade its cold boot."""
        mon = self._mon
        await self._wait_for(
            lambda: len(mon.epochs) > index and mon.epochs[index].scrub_pc is not None,
            f"the DCCM scrub of CPU run {index}",
            _BOOT_LIMIT,
        )
        ep = mon.epochs[index]
        st = ep.vals(ep.status)
        c7 = ep.vals(ep.cold7)
        assert ep.first_pc == self._rom_sym["_start"], (
            f"run {index}: first retired PC 0x{ep.first_pc:08x} is not _start "
            f"0x{self._rom_sym['_start']:08x}; the CPU did not fetch the ROM reset vector"
        )
        assert c7 and c7[0] == COLD_POISON, (
            f"run {index}: cold_scratch[7] went {_hx(c7)} from 0x{ep.cold7_start:08x}; "
            f"cold_boot writes 0x{COLD_POISON:08x} first (boot-flow.adoc)"
        )
        assert STATUS_BOOTROM_START in st and STATUS_PRESTART_DONE in st, (
            f"run {index}: cold_scratch[1] {_hx(st)} lacks BOOTROM_START or PRESTART_DONE"
        )
        assert st.index(STATUS_BOOTROM_START) < st.index(STATUS_PRESTART_DONE), (
            f"run {index}: PRESTART_DONE came before BOOTROM_START in {_hx(st)}"
        )
        assert STATUS_WARM_JUMP not in st and STATUS_WARM_HANG not in st, (
            f"run {index}: a warm decision word appears in {_hx(st)} on the cold path"
        )
        assert not ep.verdict, (
            f"run {index}: cold_scratch[0] went {_hx(ep.vals(ep.verdict))} before the DCCM "
            f"scrub; no verdict exists that early"
        )
        # The scrub writes DCCM, so the probe must rise here; that makes its silence on the
        # warm path evidence.
        await self._wait_for(
            lambda: ep.dccm_first is not None,
            f"dbg_dccm_active_o during the DCCM scrub of CPU run {index}",
            _SCRUB_PROBE_LIMIT,
        )
        assert ep.dccm_first > ep.cold7[0][0], (
            f"run {index}: DCCM access at cycle {ep.dccm_first}, before cold_boot wrote "
            f"cold_scratch[7] at cycle {ep.cold7[0][0]}; the slot must be read before any "
            f"DCCM access (SEP-ROM-CPU-110)"
        )
        return ep

    async def runtime_write_cold7(self, value: int) -> None:
        """Arm cold_scratch[7] through the tb deposit handshake and read it back."""
        dut = cocotb.top
        mon = self._mon
        assert self.rd(dut.runtime_cold_scratch7_ack_o) == 0, (
            "runtime_cold_scratch7_ack_o is high before the request; the deposit handshake "
            "is not idle"
        )
        before = self._cold7()
        assert before != value, (
            f"cold_scratch[7] already holds 0x{value:08x}; the readback could not show "
            f"that the deposit took"
        )
        requested = mon.cycle
        dut.runtime_cold_scratch7_wdata_i.value = value
        dut.runtime_cold_scratch7_we_i.value = 1
        await self._wait_for(
            lambda: self.rd(dut.runtime_cold_scratch7_ack_o) == 1,
            "runtime_cold_scratch7_ack_o rise",
            _HANDSHAKE_LIMIT,
        )
        acked = mon.cycle
        readback = self._cold7()
        assert acked - requested == 1, (
            f"runtime_cold_scratch7_ack_o rose {acked - requested} clk_i cycles after the request; "
            f"the deposit contract is one cycle"
        )
        dut.runtime_cold_scratch7_we_i.value = 0
        await self._wait_for(
            lambda: self.rd(dut.runtime_cold_scratch7_ack_o) == 0,
            "runtime_cold_scratch7_ack_o fall after the request dropped",
            _HANDSHAKE_LIMIT,
        )
        assert readback == value, (
            f"cold_scratch[7] read 0x{readback:08x} at the deposit ack, not 0x{value:08x}; "
            f"the tb deposit does not reach the slot the ROM reads"
        )
        self.logger.info(
            "CHK-RUNTIME-WARM-DEPOSIT PASS: cold_scratch[7] 0x%08x -> 0x%08x, ack %d clk_i "
            "after the request, readback 0x%08x, ack dropped with the request",
            before,
            value,
            acked - requested,
            readback,
        )

    async def pulse_cpu_warm_reset(self) -> None:
        """Pulse wdt_rst_ni_i alone through one sep_cpu_reset_n fall and rise."""
        dut = cocotb.top
        mon = self._mon
        prev = mon.epochs[-1]
        n = len(mon.epochs)
        dut.wdt_rst_ni_i.value = 0
        await self._wait_for(
            lambda: prev.fall is not None,
            "sep_cpu_reset_n_o fall after wdt_rst_ni_i went low",
            _RESET_EDGE_LIMIT,
        )
        await ClockCycles(dut.clk_i, _WARM_HOLD_CYCLES)
        dut.wdt_rst_ni_i.value = 1
        await self._wait_for(
            lambda: len(mon.epochs) > n,
            "sep_cpu_reset_n_o rise after wdt_rst_ni_i was released",
            _RESET_EDGE_LIMIT,
        )

    async def _warm_reset(self, quiet_pcs: set[int], cold7_expected: int) -> _Epoch:
        """Warm reset at a quiet point; grade the edge and the ROM re-entry."""
        mon = self._mon
        prev = mon.epochs[-1]
        await self.pulse_cpu_warm_reset()
        ep = mon.epochs[prev.index + 1]
        await self._wait_for(
            lambda: ep.first_pc is not None,
            "the first retirement after the warm reset",
            _DECISION_LIMIT,
        )
        assert prev.pc_at_fall in quiet_pcs, (
            f"the CPU reset fell with the last retired PC at "
            f"{'none' if prev.pc_at_fall is None else hex(prev.pc_at_fall)}, outside the quiet "
            f"point {_hx(sorted(quiet_pcs))}; an LSU transaction may have straddled the reset"
        )
        assert mon.cold_reset_low == 0 and mon.sep_reset_low == 0, (
            f"rst_ni was low for {mon.cold_reset_low} and sep_reset_n for {mon.sep_reset_low} "
            f"sampled cycles after the first start; the pulse was not a CPU-only warm reset"
        )
        assert mon.retired_in_reset == 0, (
            f"{mon.retired_in_reset} instruction(s) retired while sep_cpu_reset_n was low"
        )
        assert ep.cold7_start == cold7_expected, (
            f"cold_scratch[7] read 0x{ep.cold7_start:08x} at the CPU reset release, not the "
            f"0x{cold7_expected:08x} it held before the reset; the COLD bank must retain "
            f"across a warm reset (rom.adoc cold_scratch[7])"
        )
        assert ep.first_pc == self._rom_sym["_start"], (
            f"first retired PC after the warm reset is 0x{ep.first_pc:08x}, not _start "
            f"0x{self._rom_sym['_start']:08x}; the CPU did not re-fetch the ROM reset vector"
        )
        self.logger.info(
            "CHK-RUNTIME-WARM-EDGE PASS: wdt_rst_ni_i pulse dropped sep_cpu_reset_n at cycle "
            "%d and released it at cycle %d with rst_ni and sep_reset_n held high and no "
            "retirement while low; last PC before 0x%08x, first PC after 0x%08x (_start); "
            "cold_scratch[7] retained 0x%08x",
            prev.fall,
            ep.start,
            prev.pc_at_fall,
            ep.first_pc,
            ep.cold7_start,
        )
        return ep

    async def _arm_and_reset(self, value: int, quiet_pcs: set[int]) -> _Epoch:
        await self.runtime_write_cold7(value)
        return await self._warm_reset(quiet_pcs, value)

    async def _expect_handler(self, ep: _Epoch) -> None:
        """Grade an accepted dispatch into the `j .` handler."""
        await self._wait_for(
            lambda: _HANDLER in ep.pcs,
            f"retirement at the handler 0x{_HANDLER:08x}",
            _DECISION_LIMIT,
        )
        quiesce = await self.observe_quiesce(STATUS_WARM_JUMP)
        st = ep.vals(ep.status)
        c7 = ep.vals(ep.cold7)
        assert st and st[0] == STATUS_WARM_JUMP, (
            f"cold_scratch[1] after the warm reset went {_hx(st)}; the accept arm writes "
            f"WARM_JUMP 0x{STATUS_WARM_JUMP:08x} first"
        )
        for word, label in (
            (STATUS_WARM_HANG, "WARM_HANG"),
            (STATUS_BOOTROM_START, "BOOTROM_START"),
            (STATUS_PRESTART_DONE, "PRESTART_DONE"),
            (STATUS_GENERAL_EXCEPTION, "GENERAL_EXCEPTION"),
        ):
            assert word not in st, f"cold_scratch[1] took {label} on the accept arm: {_hx(st)}"
        # Only the ROM can write the slot here: the handler is `j .` and the deposit is idle.
        assert c7 == [0], (
            f"cold_scratch[7] went {_hx(c7)} from 0x{ep.cold7_start:08x}; the ROM must write "
            f"0 once before the jump (SEP-ROM-CPU-130) and must not poison it as a cold boot"
        )
        assert ep.dccm_first is None, (
            f"DCCM access at cycle {ep.dccm_first} on the warm path; the dispatch must not "
            f"touch DCCM (SEP-ROM-CPU-110)"
        )
        assert not ep.verdict, f"cold_scratch[0] went {_hx(ep.vals(ep.verdict))} on a jump"
        assert not quiesce["moved"] and quiesce["pcs"] == {_HANDLER}, (
            f"after the jump the CPU retired {_hx(sorted(quiesce['pcs']))} with status moved="
            f"{quiesce['moved']}; expected the handler 0x{_HANDLER:08x} alone"
        )
        self._assert_console_alive()
        assert not self._console, f"ROM printed {self._console}; the warm path runs no C code"
        self.logger.info(
            "warm jump: status 0x%08x at cycle %d, cold_scratch[7] 0x%08x -> 0x0 at cycle %d, "
            "handler 0x%08x first retired at cycle %d",
            STATUS_WARM_JUMP,
            ep.status[0][0],
            ep.cold7_start,
            ep.cold7[0][0],
            _HANDLER,
            ep.pcs[_HANDLER],
        )

    async def _run_valid(self, value: int, first: _Epoch) -> None:
        ep = await self._arm_and_reset(value, self._scrub_loop(first))
        await self._expect_handler(ep)
        self.logger.info(
            "CHK-RUNTIME-WARM-VALID PASS: WARM_JUMP, cold_scratch[7] cleared to 0, handler "
            "0x%08x retired alone, no DCCM access",
            _HANDLER,
        )

    async def _run_zero(self, value: int, first: _Epoch) -> None:
        ep = await self._arm_and_reset(value, self._scrub_loop(first))
        await self._cold_boot_to_scrub(ep.index)
        self.logger.info(
            "CHK-RUNTIME-WARM-ZERO PASS: slot 0 cold booted: cold_scratch[7] 0x0 -> 0x%08x, "
            "cold_scratch[1] %s, no warm decision",
            COLD_POISON,
            _hx(ep.vals(ep.status)),
        )

    async def _run_hang(self, value: int, first: _Epoch, token: str) -> None:
        ep = await self._arm_and_reset(value, self._scrub_loop(first))
        await self._wait_for(
            lambda: STATUS_WARM_HANG in ep.vals(ep.status),
            f"WARM_HANG 0x{STATUS_WARM_HANG:08x} after the warm reset",
            _DECISION_LIMIT,
        )
        quiesce = await self.observe_quiesce(STATUS_WARM_HANG)
        st = ep.vals(ep.status)
        c7 = ep.vals(ep.cold7)
        assert st[0] == STATUS_WARM_HANG, (
            f"cold_scratch[1] after the warm reset went {_hx(st)}; the reject arm writes "
            f"WARM_HANG first"
        )
        for word, label in (
            (STATUS_WARM_JUMP, "WARM_JUMP"),
            (STATUS_BOOTROM_START, "BOOTROM_START"),
            (STATUS_PRESTART_DONE, "PRESTART_DONE"),
        ):
            assert word not in st, f"cold_scratch[1] took {label} on the reject arm: {_hx(st)}"
        assert COLD_POISON not in c7, (
            f"cold_scratch[7] went {_hx(c7)}: the ROM fell through to cold_boot after "
            f"rejecting 0x{value:08x} (SEP-ROM-CPU-140)"
        )
        assert ep.dccm_first is None, (
            f"DCCM access at cycle {ep.dccm_first} on the reject arm (SEP-ROM-CPU-110)"
        )
        assert not ep.verdict, f"cold_scratch[0] went {_hx(ep.vals(ep.verdict))} on the hang"
        self.assert_hung(quiesce, STATUS_WARM_HANG)
        lo, hi = self._rom_sym["warm_reset_hang"], self._rom_sym["cold_boot"]
        assert all(lo <= pc < hi for pc in quiesce["pcs"]), (
            f"the spin PCs {_hx(sorted(quiesce['pcs']))} are outside warm_reset_hang "
            f"[0x{lo:08x}, 0x{hi:08x})"
        )
        self._assert_console_alive()
        assert not self._console, f"ROM printed {self._console}; the reject arm runs no C code"
        self.logger.info(
            "%s PASS: 0x%08x rejected: WARM_HANG, spin inside warm_reset_hang at %s, no "
            "cold boot, no DCCM access",
            token,
            value,
            _hx(sorted(quiesce["pcs"])),
        )

    async def _run_below(self, value: int, first: _Epoch) -> None:
        await self._run_hang(value, first, "CHK-RUNTIME-WARM-BELOW")

    async def _run_upper(self, value: int, first: _Epoch) -> None:
        await self._run_hang(value, first, "CHK-RUNTIME-WARM-UPPER")

    async def _run_bad_instruction(self, value: int, first: _Epoch) -> None:
        ep = await self._arm_and_reset(value, self._scrub_loop(first))
        await self._wait_for(
            lambda: VERDICT_FAIL in ep.vals(ep.verdict),
            f"FAIL verdict 0x{VERDICT_FAIL:08x} after the warm reset",
            _DECISION_LIMIT,
        )
        quiesce = await self.observe_quiesce(STATUS_GENERAL_EXCEPTION)
        st = ep.vals(ep.status)
        c7 = ep.vals(ep.cold7)
        assert st and st[0] == STATUS_WARM_JUMP, (
            f"cold_scratch[1] after the warm reset went {_hx(st)}; an in-range target must be "
            f"accepted with WARM_JUMP first"
        )
        assert STATUS_GENERAL_EXCEPTION in st, (
            f"cold_scratch[1] {_hx(st)} never took GENERAL_EXCEPTION after the jump"
        )
        after_exc = st[st.index(STATUS_GENERAL_EXCEPTION) :]
        assert value in after_exc and _MCAUSE_ILLEGAL_INSN in after_exc, (
            f"trap_vector_early reported {_hx(after_exc)}; expected mcause "
            f"{_MCAUSE_ILLEGAL_INSN} and mepc 0x{value:08x}"
        )
        for word, label in (
            (STATUS_WARM_HANG, "WARM_HANG"),
            (STATUS_BOOTROM_START, "BOOTROM_START"),
            (STATUS_PRESTART_DONE, "PRESTART_DONE"),
        ):
            assert word not in st, f"cold_scratch[1] took {label} after the bad jump: {_hx(st)}"
        assert c7 == [0], (
            f"cold_scratch[7] went {_hx(c7)} from 0x{ep.cold7_start:08x}; the ROM must write "
            f"0 once before the jump and must not reach cold_boot"
        )
        assert ep.verdict_start == 0 and ep.vals(ep.verdict) == [VERDICT_FAIL], (
            f"cold_scratch[0] went {_hx(ep.vals(ep.verdict))} from 0x{ep.verdict_start:08x}; "
            f"expected one fresh 0x{VERDICT_FAIL:08x} from trap_vector_early"
        )
        assert ep.dccm_first is None, (
            f"DCCM access at cycle {ep.dccm_first} before the fault (SEP-ROM-CPU-110)"
        )
        lo, hi = self._rom_sym["trap_vector_early"], self._rom_sym["trap_vector"]
        assert (
            not quiesce["moved"] and quiesce["pcs"] and all(lo <= pc < hi for pc in quiesce["pcs"])
        ), (
            f"after the fault the CPU retired {_hx(sorted(quiesce['pcs']))} with status "
            f"moved={quiesce['moved']}; expected the spin inside trap_vector_early "
            f"[0x{lo:08x}, 0x{hi:08x})"
        )
        self._assert_console_alive()
        assert not self._console, f"ROM printed {self._console}; the early trap runs no C code"
        self.logger.info(
            "CHK-RUNTIME-WARM-BAD-INSTRUCTION PASS: WARM_JUMP to 0x%08x, cold_scratch[7] "
            "cleared, GENERAL_EXCEPTION with mcause %d and mepc 0x%08x, cold_scratch[0] "
            "0x0 -> 0x%08x, spin in trap_vector_early, no cold boot",
            value,
            _MCAUSE_ILLEGAL_INSN,
            value,
            VERDICT_FAIL,
        )

    async def _run_one_shot_rearm(self, value: int, first: _Epoch) -> None:
        jump1 = await self._arm_and_reset(value, self._scrub_loop(first))
        await self._expect_handler(jump1)
        assert self._cold7() == 0, (
            f"cold_scratch[7] reads 0x{self._cold7():08x} in the handler; the jump must "
            f"consume the slot"
        )
        self.logger.info("one-shot: warm reset 1 jumped and left cold_scratch[7] at 0x0")

        cold = await self._warm_reset({_HANDLER}, 0)
        await self._cold_boot_to_scrub(cold.index)
        assert _HANDLER not in cold.pcs, (
            f"the handler 0x{_HANDLER:08x} retired after an unarmed warm reset; the ROM "
            f"re-used a consumed pointer"
        )
        self.logger.info("one-shot: warm reset 2 without a re-arm cold booted")

        jump2 = await self._arm_and_reset(value, self._scrub_loop(cold))
        await self._expect_handler(jump2)
        self.logger.info(
            "CHK-RUNTIME-WARM-ONE-SHOT-REARM PASS: jump, slot 0x0, unarmed reset cold "
            "booted, re-armed reset jumped to 0x%08x again",
            _HANDLER,
        )
