# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive processor-state monitor on the SEP's EL2 retirement trace.

Snoops the retirement record ``tb_wrapper_top.sv`` exports as ``sep_trace_*_o``
/ ``sep_pc_o`` and reconstructs where the SEP firmware is and how it got there,
so a wrapper run that hangs, traps, or fails reports more than a PC profile:

  * **PC history** -- every retired PC feeds a tally (count + distinct set, the
    SEP boot scoreboard's liveness evidence) and a bounded ring of the most
    recent retirements for post-mortem dumps.
  * **Shadow call stack** -- retired instructions are decoded (RV32IMC) for
    calls (``jal``/``jalr``/``c.jal``/``c.jalr`` linking ra/t0), returns
    (``jalr``/``c.jr`` through ra/t0), and ``mret``, maintaining a call stack
    that symbolizes into a firmware backtrace from the staged nm listing.
  * **Trap records** -- a retirement flagged as an exception is captured with
    ecause/interrupt/tval and pushed as a synthetic stack frame (popped by
    ``mret``), so a backtrace shows the trap and where it hit.
  * **Hang watch** -- after the first retirement, a long retirement-free gap
    out of reset logs a one-shot warning with a full dump. Diagnostic only:
    a core idling in ``wfi`` or a terminal loop is legitimate.

Passive and self-gating: idles unless ``+sep_itcm_hex`` names a SEP image (the
no-SEP compile exports the ports tied to zero). Sampling is reset-aware --
``sep_reset_n_o`` low flushes the shadow stack (the SMC arm firmware releases
the SEP after the wrapper's own cold reset) while keeping history and tallies.
Reconstruction hiccups (pop of an empty stack, depth overflow) are logged and
tallied, never failed: pass/fail judgement stays with the sequences and the
boot scoreboard.

``+sep_trace_log`` additionally streams every retirement to ``sep_trace.log``
in the run directory (cycle, PC, encoding, symbol) -- off by default for log
volume.

The SEP standalone bench carries the same monitor as
``hw/sys/sep/dv/cocotb/env/sep_cpu_trace_monitor.py``.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import uvm_component

__all__ = ["SmuSepCpuTraceMonitor", "TrapRecord"]

# RISC-V link registers (RV32I calling convention): x1/ra and x5/t0 alternate
# link. rd in the set => call; jalr/c.jr with rd=x0 through the set => return.
_LINK_REGS = (1, 5)
_MRET = 0x3020_0073

# RISC-V mcause codes (interrupt bit clear). Enough for firmware diagnosis;
# unknown causes print numerically.
_MCAUSE_NAMES = {
    0: "insn addr misaligned",
    1: "insn access fault",
    2: "illegal instruction",
    3: "breakpoint",
    4: "load addr misaligned",
    5: "load access fault",
    6: "store addr misaligned",
    7: "store access fault",
    8: "ecall (U)",
    11: "ecall (M)",
}

_RING_DEPTH = 512
_STACK_CAP = 64
# A PC this far past the nearest preceding symbol is not inside that function:
# it falls in the gap between two loaded images. Report bare hex instead.
_MAX_SYM_OFF = 0x1_0000
_PC_MASK = 0xFFFF_FFFF

_SIGNALS = (
    "sep_trace_valid_o",
    "sep_pc_o",
    "sep_trace_insn_o",
    "sep_trace_exc_o",
    "sep_trace_ecause_o",
    "sep_trace_interrupt_o",
    "sep_trace_tval_o",
    "sep_reset_n_o",
)


class _Flow(Enum):
    CALL = "call"
    RET = "ret"
    MRET = "mret"


@dataclass(frozen=True)
class TrapRecord:
    """One exception retirement as the trace port reported it."""

    cycle: int
    pc: int
    ecause: int
    interrupt: int
    tval: int


@dataclass(frozen=True)
class _Retirement:
    """One sample of the trace port with ``sep_trace_valid_o`` high."""

    cycle: int
    pc: int
    insn: int
    exc: int
    ecause: int
    interrupt: int
    tval: int


@dataclass
class _CallFrame:
    site: int
    target: int | None = None


@dataclass(frozen=True)
class _TrapFrame:
    pc: int
    ecause: int
    interrupt: int
    tval: int


def _decode_flow(insn: int) -> _Flow | None:
    """Classify one retired RV32IMC encoding as control flow of interest.

    The trace carries compressed encodings unexpanded; 16-vs-32-bit is the
    standard low-two-bits test.
    """
    if insn & 0x3 == 0x3:  # 32-bit
        opcode = insn & 0x7F
        rd = (insn >> 7) & 0x1F
        rs1 = (insn >> 15) & 0x1F
        if opcode == 0x6F:  # JAL
            return _Flow.CALL if rd in _LINK_REGS else None
        if opcode == 0x67:  # JALR
            if rd in _LINK_REGS:
                return _Flow.CALL
            if rd == 0 and rs1 in _LINK_REGS:
                return _Flow.RET
            return None
        if insn == _MRET:
            return _Flow.MRET
        return None
    c = insn & 0xFFFF  # 16-bit compressed
    quad = c & 0x3
    funct3 = (c >> 13) & 0x7
    if quad == 0x1 and funct3 == 0x1:  # c.jal (RV32) links ra
        return _Flow.CALL
    if quad == 0x2 and funct3 == 0x4:
        rs1 = (c >> 7) & 0x1F
        rs2 = (c >> 2) & 0x1F
        if rs2 == 0 and rs1 != 0:
            if c & 0x1000:  # c.jalr rs1 links ra
                return _Flow.CALL
            if rs1 in _LINK_REGS:  # c.jr through a link reg
                return _Flow.RET
    return None


def _cause_str(ecause: int, interrupt: int) -> str:
    if interrupt:
        return f"interrupt cause={ecause}"
    return _MCAUSE_NAMES.get(ecause, f"exception cause={ecause}")


class SmuSepCpuTraceMonitor(uvm_component):
    """Retirement-trace observer: PC history, shadow call stack, trap records.

    Publishes nothing on an analysis port: consumers read the tallies and
    records directly (the boot scoreboard through ``ConfigDB`` key
    ``sep_trace_mon``, sequences through the test's attribute).
    """

    # Retirement-free cycles (out of reset, after the first retirement) before
    # the one-shot hang warning. Overridable per test before run_phase.
    hang_cycles = 20_000

    def __init__(self, name: str, parent) -> None:
        super().__init__(name, parent)
        # The symbol table is fed from the parent's build_phase, which runs
        # before this component's own build_phase.
        self.symbol_files: list[str] = []
        self._syms: list[tuple[int, str]] = []
        self._addrs: list[int] = []

    def build_phase(self) -> None:
        self.active = False
        self.trace_count = 0
        self.pcs: set[int] = set()
        self.last_pc = 0
        self.ring: deque[tuple[int, int, int]] = deque(maxlen=_RING_DEPTH)
        # Index 0 is the outermost frame.
        self.stack: list[_CallFrame | _TrapFrame] = []
        self.max_depth = 0
        self.trap_events: list[TrapRecord] = []
        self.reset_flushes = 0
        self.resync_notes = 0
        self._fill_target = False
        self._hang_warned = False
        self._trace_file = None

    # ------------------------------------------------------------------
    # Symbols
    # ------------------------------------------------------------------
    def attach_symbols(self, syms: Sequence[tuple[int, str]], source: str) -> None:
        """Merge one ``(addr, name)`` listing; PCs stay numeric without one."""
        self._syms = sorted(set(self._syms) | set(syms))
        self._addrs = [addr for addr, _ in self._syms]
        self.symbol_files.append(source)
        self.logger.info("loaded %d code symbols from %s", len(syms), source)

    def symbolize(self, pc: int) -> str:
        """``name+0xoff`` for the symbol covering ``pc``; bare hex outside any."""
        i = bisect_right(self._addrs, pc) - 1
        if i < 0:
            return f"0x{pc:08x}"
        addr, name = self._syms[i]
        off = pc - addr
        if off >= _MAX_SYM_OFF:
            return f"0x{pc:08x}"
        return name if off == 0 else f"{name}+0x{off:x}"

    # ------------------------------------------------------------------
    # Reconstruction
    # ------------------------------------------------------------------
    def _note_retire(self, r: _Retirement) -> None:
        self.trace_count += 1
        self.last_pc = r.pc
        self.pcs.add(r.pc)
        self.ring.append((r.cycle, r.pc, r.insn))
        if self._trace_file is not None:
            self._trace_file.write(
                f"{r.cycle:>10} {r.pc:08x} {r.insn:08x} {self.symbolize(r.pc)}\n"
            )
        if self._fill_target:
            # First retirement after a call is the callee entry.
            top = self.stack[-1]
            if isinstance(top, _CallFrame):
                top.target = r.pc
            self._fill_target = False
        if r.exc:
            self.trap_events.append(TrapRecord(r.cycle, r.pc, r.ecause, r.interrupt, r.tval))
            self._push(_TrapFrame(r.pc, r.ecause, r.interrupt, r.tval))
            self.logger.warning(
                "trap at cycle %d: %s pc=0x%08x (%s) tval=0x%08x",
                r.cycle,
                _cause_str(r.ecause, r.interrupt),
                r.pc,
                self.symbolize(r.pc),
                r.tval,
            )
            return
        flow = _decode_flow(r.insn)
        if flow is None:
            return
        if flow is _Flow.CALL:
            self._push(_CallFrame(r.pc))
            self._fill_target = True
        elif flow is _Flow.RET:
            if self.stack and isinstance(self.stack[-1], _CallFrame):
                self.stack.pop()
            else:
                self.resync_notes += 1
        else:
            # mret unwinds to and including the innermost trap frame; call
            # frames above it belong to the handler and are dead after mret.
            while self.stack and not isinstance(self.stack[-1], _TrapFrame):
                self.stack.pop()
            if self.stack:
                self.stack.pop()
            else:
                self.resync_notes += 1

    def _push(self, frame: _CallFrame | _TrapFrame) -> None:
        self.stack.append(frame)
        self.max_depth = max(self.max_depth, len(self.stack))
        if len(self.stack) > _STACK_CAP:
            self.stack.pop(0)
            self.resync_notes += 1

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    @staticmethod
    def _rd(signal) -> int:
        """Resolved integer value; an X/Z sample reads as 0.

        The ports are masked to zero while the SEP is in reset, so an
        unresolved sample can only occur before cocotb has driven the wrapper
        resets, when no retirement is possible.
        """
        if signal is None:
            return 0
        value = signal.value
        if not value.is_resolvable:
            return 0
        return int(value)

    async def run_phase(self) -> None:
        if "sep_itcm_hex" not in cocotb.plusargs:
            return
        dut = cocotb.top
        sig = {name: getattr(dut, name, None) for name in _SIGNALS}
        if sig["sep_trace_valid_o"] is None or sig["sep_pc_o"] is None:
            self.logger.warning("SEP trace ports not found; CPU trace monitor idle")
            return
        if "sep_trace_log" in cocotb.plusargs:
            self._trace_file = open("sep_trace.log", "w")
        self.active = True
        self.logger.info("SEP CPU trace monitor active (hang watch at %d cycles)", self.hang_cycles)

        clk = dut.clk_smu_i
        cycle = 0
        idle = 0
        was_in_reset = True
        while True:
            await RisingEdge(clk)
            cycle += 1
            if not self._rd(sig["sep_reset_n_o"]):
                if not was_in_reset and (self.stack or self._fill_target):
                    self.logger.info(
                        "SEP reset asserted at cycle %d; flushing shadow stack (depth %d)",
                        cycle,
                        len(self.stack),
                    )
                    self.stack.clear()
                    self._fill_target = False
                    self.reset_flushes += 1
                was_in_reset = True
                idle = 0
                continue
            was_in_reset = False
            if self._rd(sig["sep_trace_valid_o"]):
                idle = 0
                self._hang_warned = False
                self._note_retire(
                    _Retirement(
                        cycle=cycle,
                        pc=self._rd(sig["sep_pc_o"]) & _PC_MASK,
                        insn=self._rd(sig["sep_trace_insn_o"]) & _PC_MASK,
                        exc=self._rd(sig["sep_trace_exc_o"]),
                        ecause=self._rd(sig["sep_trace_ecause_o"]),
                        interrupt=self._rd(sig["sep_trace_interrupt_o"]),
                        tval=self._rd(sig["sep_trace_tval_o"]) & _PC_MASK,
                    )
                )
            elif self.trace_count and not self._hang_warned:
                idle += 1
                if idle >= self.hang_cycles:
                    self._hang_warned = True
                    self.logger.warning(
                        "no instruction retired for %d cycles (last pc 0x%08x %s); "
                        "possible hang -- diagnostic only, wfi/terminal loops are legitimate",
                        idle,
                        self.last_pc,
                        self.symbolize(self.last_pc),
                    )
                    self.dump_diagnostics(logging.WARNING)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def dump_diagnostics(self, level: int = logging.INFO, ring_tail: int = 32) -> None:
        """Symbolized processor-state dump: call stack, traps, recent PCs."""
        log = self.logger.log
        log(
            level,
            "SEP CPU state: %d retired, %d distinct PCs, last pc 0x%08x (%s), "
            "max call depth %d, %d trap(s), %d reset flush(es), %d resync note(s)",
            self.trace_count,
            len(self.pcs),
            self.last_pc,
            self.symbolize(self.last_pc),
            self.max_depth,
            len(self.trap_events),
            self.reset_flushes,
            self.resync_notes,
        )
        if self.stack:
            log(level, "SEP firmware call stack (innermost first):")
            for i, frame in enumerate(reversed(self.stack)):
                if isinstance(frame, _CallFrame):
                    where = self.symbolize(frame.target) if frame.target is not None else "?"
                    log(
                        level,
                        "  #%d %s <- called from 0x%08x (%s)",
                        i,
                        where,
                        frame.site,
                        self.symbolize(frame.site),
                    )
                else:
                    log(
                        level,
                        "  #%d [trap] %s at 0x%08x (%s) tval=0x%08x",
                        i,
                        _cause_str(frame.ecause, frame.interrupt),
                        frame.pc,
                        self.symbolize(frame.pc),
                        frame.tval,
                    )
        for rec in self.trap_events:
            log(
                level,
                "trap record: cycle %d %s pc=0x%08x (%s) tval=0x%08x",
                rec.cycle,
                _cause_str(rec.ecause, rec.interrupt),
                rec.pc,
                self.symbolize(rec.pc),
                rec.tval,
            )
        if self.ring:
            tail = list(self.ring)[-ring_tail:]
            log(level, "last %d SEP retirements (cycle pc insn symbol):", len(tail))
            for cyc, pc, insn in tail:
                log(level, "  %10d %08x %08x %s", cyc, pc, insn, self.symbolize(pc))

    def report_phase(self) -> None:
        if self._trace_file is not None:
            self._trace_file.close()
            self._trace_file = None
        if self.active:
            self.dump_diagnostics(logging.INFO)
