# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-cycle recorder of a Boot ROM run, for checks on the order of ROM actions.

Every record carries the simulation time in ps of the clk_i edge that showed it,
sampled in ReadOnly after that edge like SepFabricTap beats, so a leaf can order a
status word, a console line, a retirement, a watched port change and a bus beat.

Status, verdict and console words are cold_scratch registers written by CPU stores, so
each change lags the retirement of its store by 1 to STORE_LAG_MAX_CYCLES clk cycles.
Status and verdict are recorded on change only: a repeated identical word adds no record.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from env.sep_rom_console import RomConsoleDecoder, console_word
from env.sep_rv32_trace_decode import (
    INSN_MRET,
    OP_SYSTEM,
    RegTracker,
    decode_csr,
    is_fence,
    is_fence_i,
    is_store,
    opcode,
    writes_rd,
)
from env.sep_verdict import decode_verdict

ROM_BUILD = Path(__file__).resolve().parents[3] / "bootrom" / "prod" / "build"
# Bound on store retirement to cold_scratch change; sep_rom_observer_smoke_test grades it.
STORE_LAG_MAX_CYCLES = 64
_WORD = 0xFFFF_FFFF
# csrrw x0, mscratch, x0: a SYSTEM word a keep filter must retain for csr_writes().
_CSR_PROBE = (0x340 << 20) | (1 << 12) | 0x73


def load_rom_syms(path: Path | str = ROM_BUILD / "boot_rom.sym") -> dict[str, int]:
    """Every symbol of the ROM ELF, from the nm -B -n listing the ROM build writes."""
    syms: dict[str, int] = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)
    if not syms:
        raise FileNotFoundError(f"no symbols in {path}; build the boot_rom firmware first")
    return syms


def keep_system_fence_store(insn: int) -> bool:
    """Default retirement filter: CSR, mret, fences and stores."""
    return opcode(insn) == OP_SYSTEM or is_fence(insn) or is_fence_i(insn) or is_store(insn)


@dataclass(frozen=True)
class Retire:
    """One retirement; csr_value is the CSR write operand (csrrs/csrrc mask), mem_addr the
    load/store address and mem_data the stored value, each when the tracker knows its register."""

    cycle: int
    t_ps: int
    pc: int
    insn: int
    exc: bool
    ecause: int
    interrupt: bool
    csr_value: int | None
    mem_addr: int | None = None
    mem_data: int | None = None


class SepRomObserver:
    """Records one ROM run; start before reset release, stop before grading."""

    def __init__(
        self,
        test,
        *,
        keep: Callable[[int], bool] = keep_system_fence_store,
        head: int = 256,
        ring: int = 64,
        watch: tuple[str, ...] = (),
        tracker: bool = True,
        pc_window: tuple[int, int] | None = None,
        pc_watch: frozenset[int] = frozenset(),
    ) -> None:
        self._test = test
        self._keep = keep
        self._head = head
        self._ring_depth = ring
        self._watch = watch
        self._tracker = RegTracker() if tracker else None
        self._pc_window = pc_window
        self._pc_watch = pc_watch
        self.pc_hits: list[tuple[int, int]] = []
        self.cycle = 0
        self.retired = 0
        self.status: list[tuple[int, int]] = []
        self.verdict: list[tuple[int, int]] = []
        self.console: list[tuple[int, str]] = []
        self.retires: list[Retire] = []
        self.first: list[Retire] = []
        self.traps: list[Retire] = []
        self.pre_mret: list[Retire] = []
        self.post_mret: Retire | None = None
        self.reg_writes: list[tuple[int, int, int]] = []
        self.outside_window: list[Retire] = []
        self.watched: dict[str, list[tuple[int, int]]] = {n: [] for n in watch}
        self._ring: list[Retire] = []
        self._console = RomConsoleDecoder()
        self._mret_seen = False
        self._stopping = False
        self._task = None

    # -- life ----------------------------------------------------------------

    def start(self) -> SepRomObserver:
        self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        self._stopping = True
        await RisingEdge(cocotb.top.clk_i)
        await RisingEdge(cocotb.top.clk_i)
        if self.retired == 0:
            raise AssertionError(
                "SepRomObserver saw no retirement; check that it started before reset "
                "release and that cpu_trace_valid_o is driven"
            )

    async def run_until(self, pred: Callable[[SepRomObserver], bool], max_cycles: int) -> bool:
        """Wait until pred(self) holds or max_cycles pass; returns whether it held."""
        dut = cocotb.top
        for _ in range(max_cycles):
            await RisingEdge(dut.clk_i)
            if pred(self):
                return True
        return False

    # -- sampling ------------------------------------------------------------

    async def _run(self) -> None:
        dut = cocotb.top
        rd = self._test.rd
        last_status = last_verdict = None
        last_watch: dict[str, int | None] = {n: None for n in self._watch}
        while not self._stopping:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.cycle += 1
            t = int(get_sim_time("ps"))
            probe = rd(dut.scratch_cold_probe_o, allow_unknown=True)
            status = (probe >> 32) & _WORD
            if status != last_status:
                last_status = status
                self.status.append((t, status))
            verdict = probe & _WORD
            if verdict != last_verdict:
                last_verdict = verdict
                self.verdict.append((t, verdict))
            for line in self._console.feed(console_word(probe)):
                self._test.logger.info("ROM> %s", line)
                self.console.append((t, line))
            for name in self._watch:
                v = rd(getattr(dut, name), allow_unknown=True)
                if v != last_watch[name]:
                    last_watch[name] = v
                    self.watched[name].append((t, v))
            if rd(dut.cpu_trace_valid_o, allow_unknown=True):
                self._retire(t, rd)

    def _retire(self, t: int, rd) -> None:
        dut = cocotb.top
        self.record(
            t,
            rd(dut.cpu_trace_addr_o, allow_unknown=True),
            rd(dut.cpu_trace_insn_o, allow_unknown=True),
            bool(rd(dut.dbg_cpu_trace_exc_o, allow_unknown=True)),
            rd(dut.cpu_trace_ecause_o, allow_unknown=True),
            bool(rd(dut.cpu_trace_interrupt_o, allow_unknown=True)),
        )

    def record(self, t: int, pc: int, insn: int, exc: bool, ecause: int, interrupt: bool) -> Retire:
        """Classify one retirement into the record; needs no simulator."""
        trapped = exc or interrupt
        csr_value = mem_addr = mem_data = None
        if self._tracker is not None and not trapped:
            op = decode_csr(insn)
            if op is not None and op.writes:
                csr_value = self._tracker.csr_operand(insn)
            mem_addr = self._tracker.mem_addr(insn)
            mem_data = self._tracker.store_data(insn)
        r = Retire(self.cycle, t, pc, insn, exc, ecause, interrupt, csr_value, mem_addr, mem_data)
        # A trapped retirement did not write its destination register.
        if self._tracker is not None and not trapped:
            self._tracker.step(insn, pc)
            dest = writes_rd(insn)
            if dest is not None and self._tracker.value(dest) is not None:
                self.reg_writes.append((t, dest, self._tracker.value(dest)))
        self.retired += 1
        if pc in self._pc_watch:
            self.pc_hits.append((t, pc))
        if len(self.first) < self._head:
            self.first.append(r)
        if trapped:
            self.traps.append(r)
        if self._keep(insn):
            self.retires.append(r)
        if self._mret_seen and self.post_mret is None:
            self.post_mret = r
        if not self._mret_seen:
            self._ring.append(r)
            if len(self._ring) > self._ring_depth:
                self._ring.pop(0)
            if self._pc_window is not None and not (self._pc_window[0] <= pc < self._pc_window[1]):
                if len(self.outside_window) < 32:
                    self.outside_window.append(r)
            if insn == INSN_MRET and not trapped:
                self._mret_seen = True
                self.pre_mret = list(self._ring)
        return r

    # -- queries -------------------------------------------------------------

    def lines(self) -> list[str]:
        return [line for _, line in self.console]

    def line_t(self, marker: str) -> int | None:
        """Time of the first console line that contains marker."""
        return next((t for t, line in self.console if marker in line), None)

    def statuses(self) -> list[int]:
        return [w for _, w in self.status]

    def status_t(self, word: int) -> int | None:
        return next((t for t, w in self.status if w == word), None)

    def verdict_pass(self) -> bool | None:
        """True or False once cold_scratch[0] holds a verdict, else None."""
        if not self.verdict:
            return None
        got = decode_verdict(self.verdict[-1][1])
        return None if got is None else bool(got[1])

    def csr_writes(self, csr_lo: int, csr_hi: int | None = None) -> list[Retire]:
        """Kept retirements that write a CSR in [csr_lo, csr_hi] without trapping."""
        if not self._keep(_CSR_PROBE):
            raise ValueError("csr_writes() needs a keep filter that retains SYSTEM instructions")
        hi = csr_lo if csr_hi is None else csr_hi
        out = []
        for r in self.retires:
            if r.exc or r.interrupt:
                continue
            op = decode_csr(r.insn)
            if op is not None and op.writes and csr_lo <= op.csr <= hi:
                out.append(r)
        return out

    def last_store(self, addr: int, t_ps: int) -> Retire | None:
        """Latest kept non-trapping store to addr that retired at or before t_ps."""
        hit = None
        for r in self.retires:
            if r.t_ps > t_ps:
                break
            if r.mem_addr == addr and is_store(r.insn) and not (r.exc or r.interrupt):
                hit = r
        return hit


def _selftest() -> None:
    import sep_rv32_asm as asm

    obs = SepRomObserver(
        None, ring=4, head=3, pc_window=(0x1000, 0x2000), pc_watch=frozenset({0x1008})
    )

    def ret(pc: int, insn: int, exc: bool = False, interrupt: bool = False) -> Retire:
        obs.cycle += 1
        return obs.record(obs.cycle * 10, pc, insn, exc, 2 if exc else 0, interrupt)

    nop = asm.addi(asm.ZERO, asm.ZERO, 0)
    ret(0x1000, asm.lui(asm.T0, 0x10802))
    store = ret(0x1004, asm.sw(asm.T0, asm.T0, 8))
    assert store.mem_addr == 0x1080_2008 and store.mem_data == 0x1080_2000, store
    assert store in obs.retires, "the default filter keeps stores"
    ret(0x1008, nop)
    assert obs.pc_hits == [(30, 0x1008)] and nop not in [r.insn for r in obs.retires]
    fence = ret(0x100C, 0x0FF0_000F)
    assert fence in obs.retires, "the default filter keeps fences"
    exc = ret(0x1010, asm.lui(asm.T0, 0x20000), exc=True)
    assert obs.traps == [exc] and obs._tracker.value(asm.T0) == 0x1080_2000, "trap must not step"
    irq = ret(0x1014, nop, interrupt=True)
    assert obs.traps == [exc, irq], "an interrupt is a trap"
    out = ret(0x3000, nop)
    assert obs.outside_window == [out], obs.outside_window
    csr = ret(0x1018, asm.csrw(0x3B0, asm.T0))
    assert csr.csr_value == 0x1080_2000 and obs.csr_writes(0x3B0) == [csr], csr
    trapped_csr = ret(0x101C, asm.csrw(0x3B0, asm.T0), exc=True)
    assert trapped_csr.csr_value is None and obs.csr_writes(0x3B0) == [csr]
    assert obs.last_store(0x1080_2008, 1000) == store and obs.last_store(0x1080_2008, 10) is None
    mret = ret(0x1020, INSN_MRET)
    assert obs.pre_mret[-1] == mret and len(obs.pre_mret) == 4 and obs.post_mret is None
    post = ret(0xC000_0000, nop)
    assert obs.post_mret == post and obs.outside_window == [out], "window applies before mret only"
    ret(0xC000_0004, INSN_MRET)
    assert obs.pre_mret[-1] == mret and obs.post_mret == post, "only the first mret counts"
    assert len(obs.first) == 3 and obs.retired == 12 and obs.first[0].pc == 0x1000
    drop = SepRomObserver(None, keep=is_store)
    try:
        drop.csr_writes(0x3B0)
    except ValueError:
        pass
    else:
        raise AssertionError("csr_writes must refuse a filter that drops SYSTEM")
    print("sep_rom_observer self-test PASS")


if __name__ == "__main__":
    _selftest()
