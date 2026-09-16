# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive processor-state monitor on the VeeR EL2 retirement trace.

Snoops the EL2 trace port surfaced as tb_top ports (``cpu_trace_*_o``,
``dbg_cpu_trace_exc_o``) and reconstructs where the firmware is and how it got
there, so a run that hangs, traps, or fails reports more than the absence of
console output:

  * **PC history** -- every retired PC feeds a tally (count + distinct set,
    the boot scoreboard's liveness evidence) and a bounded ring of the most
    recent retirements for post-mortem dumps.
  * **Shadow call stack** -- retired instructions are decoded (RV32IMC) for
    calls (``jal``/``jalr``/``c.jal``/``c.jalr`` linking ra/t0), returns
    (``jalr``/``c.jr`` through ra/t0), and ``mret``, maintaining a call stack
    that symbolizes into a firmware backtrace via
    :class:`env.sep_fw_symbols.SepFwSymbols`.
  * **Trap records** -- a retirement flagged as an exception is captured with
    ecause/interrupt/tval and pushed as a synthetic stack frame (popped by
    ``mret``), so a backtrace shows the trap and where it hit.
  * **Hang watch** -- after the first retirement, a long retirement-free gap
    out of reset logs a one-shot warning with a full dump. Diagnostic only:
    a core idling in a wait loop or halt is legitimate.

Passive and self-gating: idles unless the ``+cpu_boot`` run mode is active
(the no-CPU shim ties the trace struct to zero). Sampling is reset-aware --
``sep_cpu_reset_n_o`` low flushes the shadow stack (the core restarts) while
keeping history and tallies. Reconstruction hiccups (pop of an empty stack,
depth overflow) are logged and tallied, never failed: pass/fail judgement
stays in the boot scoreboard.

``+cpu_trace_log`` additionally streams every retirement to ``cpu_trace.log``
in the run directory (cycle, PC, encoding, symbol) -- off by default for log
volume.
"""

from __future__ import annotations

import logging
from collections import deque

import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import uvm_component

from .sep_fw_symbols import SepFwSymbols

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


def _decode_flow(insn: int) -> tuple[str, int] | None:
    """Classify one retired RV32IMC encoding as control-flow of interest.

    Returns ``("call", rd)``, ``("ret", rs1)``, ``("mret", 0)``, or None.
    The trace carries compressed encodings unexpanded; 16-vs-32-bit is the
    standard low-two-bits test.
    """
    if insn & 0x3 == 0x3:  # 32-bit
        opcode = insn & 0x7F
        rd = (insn >> 7) & 0x1F
        rs1 = (insn >> 15) & 0x1F
        if opcode == 0x6F:  # JAL
            return ("call", rd) if rd in _LINK_REGS else None
        if opcode == 0x67:  # JALR
            if rd in _LINK_REGS:
                return ("call", rd)
            if rd == 0 and rs1 in _LINK_REGS:
                return ("ret", rs1)
            return None
        if insn == _MRET:
            return ("mret", 0)
        return None
    c = insn & 0xFFFF  # 16-bit compressed
    quad = c & 0x3
    funct3 = (c >> 13) & 0x7
    if quad == 0x1 and funct3 == 0x1:  # c.jal (RV32) links ra
        return ("call", 1)
    if quad == 0x2 and funct3 == 0x4:
        rs1 = (c >> 7) & 0x1F
        rs2 = (c >> 2) & 0x1F
        if rs2 == 0 and rs1 != 0:
            if c & 0x1000:  # c.jalr rs1 links ra
                return ("call", 1)
            if rs1 in _LINK_REGS:  # c.jr through a link reg
                return ("ret", rs1)
    return None


class SepCpuTraceMonitor(uvm_component):
    """Retirement-trace observer: PC history, shadow call stack, trap records."""

    # Retirement-free cycles (out of reset, after first retirement) before the
    # one-shot hang warning. Overridable per test before run_phase.
    hang_cycles = 20_000

    def build_phase(self) -> None:
        self.symbols = SepFwSymbols()
        self.active = False
        self.trace_count = 0
        self.pcs: set[int] = set()
        self.last_pc = 0
        self.ring: deque[tuple[int, int, int]] = deque(maxlen=_RING_DEPTH)
        # Frames are lists for the lazy target fill: ["call", site_pc, target]
        # or ["trap", pc, ecause, interrupt, tval]. Index 0 is outermost.
        self.stack: list[list] = []
        self.max_depth = 0
        self.trap_events: list[tuple[int, int, int, int, int]] = []
        self.reset_flushes = 0
        self.resync_notes = 0
        self._fill_target = False
        self._hang_warned = False
        self._trace_file = None

    def add_symbols(self, path) -> None:
        """Merge one nm listing (missing file is a warning, not an error --
        symbolization is a debug aid, never a pass gate)."""
        try:
            n = self.symbols.load(path)
            self.logger.info("loaded %d code symbols from %s", n, path)
        except OSError as exc:
            self.logger.warning("symbol file unavailable (%s); PCs stay numeric", exc)

    # ------------------------------------------------------------------
    # Reconstruction
    # ------------------------------------------------------------------
    def _sym(self, pc: int) -> str:
        return self.symbols.lookup(pc)

    def _note_retire(
        self, cycle: int, pc: int, insn: int, exc: int, ecause: int, interrupt: int, tval: int
    ) -> None:
        self.trace_count += 1
        self.last_pc = pc
        self.pcs.add(pc)
        self.ring.append((cycle, pc, insn))
        if self._trace_file is not None:
            self._trace_file.write(f"{cycle:>10} {pc:08x} {insn:08x} {self._sym(pc)}\n")
        if self._fill_target:
            # First retirement after a call is the callee entry.
            self.stack[-1][2] = pc
            self._fill_target = False
        if exc:
            self.trap_events.append((cycle, pc, ecause, interrupt, tval))
            self._push(["trap", pc, ecause, interrupt, tval])
            self.logger.warning(
                "trap at cycle %d: %s pc=0x%08x (%s) tval=0x%08x",
                cycle,
                self._cause_str(ecause, interrupt),
                pc,
                self._sym(pc),
                tval,
            )
            return
        kind_rd = _decode_flow(insn)
        if kind_rd is None:
            return
        kind, _ = kind_rd
        if kind == "call":
            self._push(["call", pc, None])
            self._fill_target = True
        elif kind == "ret":
            if self.stack and self.stack[-1][0] == "call":
                self.stack.pop()
            else:
                self.resync_notes += 1
        elif kind == "mret":
            # Unwind to (and including) the innermost trap frame; call frames
            # above it belong to the handler and are dead after mret.
            while self.stack and self.stack[-1][0] != "trap":
                self.stack.pop()
            if self.stack:
                self.stack.pop()
            else:
                self.resync_notes += 1

    def _push(self, frame: list) -> None:
        self.stack.append(frame)
        self.max_depth = max(self.max_depth, len(self.stack))
        if len(self.stack) > _STACK_CAP:
            self.stack.pop(0)
            self.resync_notes += 1

    @staticmethod
    def _cause_str(ecause: int, interrupt: int) -> str:
        if interrupt:
            return f"interrupt cause={ecause}"
        return _MCAUSE_NAMES.get(ecause, f"exception cause={ecause}")

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    async def run_phase(self) -> None:
        if "cpu_boot" not in cocotb.plusargs:
            return
        dut = cocotb.top
        sig = {
            n: getattr(dut, n, None)
            for n in (
                "cpu_trace_valid_o",
                "cpu_trace_addr_o",
                "cpu_trace_insn_o",
                "dbg_cpu_trace_exc_o",
                "cpu_trace_ecause_o",
                "cpu_trace_interrupt_o",
                "cpu_trace_tval_o",
                "sep_cpu_reset_n_o",
            )
        }
        if sig["cpu_trace_valid_o"] is None or sig["cpu_trace_addr_o"] is None:
            self.logger.warning("cpu trace ports not found; CPU trace monitor idle")
            return
        if "cpu_trace_log" in cocotb.plusargs:
            self._trace_file = open("cpu_trace.log", "w")
        self.active = True
        self.logger.info("CPU trace monitor active (hang watch at %d cycles)", self.hang_cycles)

        def rd(name: str) -> int:
            s = sig[name]
            if s is None:
                return 0
            try:
                return int(s.value)
            except Exception:
                return 0

        clk = dut.clk_i
        cycle = 0
        idle = 0
        was_in_reset = True
        while True:
            await RisingEdge(clk)
            cycle += 1
            if not rd("sep_cpu_reset_n_o"):
                if not was_in_reset and (self.stack or self._fill_target):
                    # Warm CPU reset (e.g. WDT bite): the core restarts, so the
                    # in-flight call stack is dead. History/tallies survive.
                    self.logger.info(
                        "CPU reset asserted at cycle %d; flushing shadow stack (depth %d)",
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
            if rd("cpu_trace_valid_o"):
                idle = 0
                self._hang_warned = False
                self._note_retire(
                    cycle,
                    rd("cpu_trace_addr_o") & 0xFFFF_FFFF,
                    rd("cpu_trace_insn_o") & 0xFFFF_FFFF,
                    rd("dbg_cpu_trace_exc_o"),
                    rd("cpu_trace_ecause_o"),
                    rd("cpu_trace_interrupt_o"),
                    rd("cpu_trace_tval_o") & 0xFFFF_FFFF,
                )
            elif self.trace_count and not self._hang_warned:
                idle += 1
                if idle >= self.hang_cycles:
                    self._hang_warned = True
                    self.logger.warning(
                        "no instruction retired for %d cycles (last pc 0x%08x %s); "
                        "possible hang -- diagnostic only, idle/halt is legitimate",
                        idle,
                        self.last_pc,
                        self._sym(self.last_pc),
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
            "CPU state: %d retired, %d distinct PCs, last pc 0x%08x (%s), "
            "max call depth %d, %d trap(s), %d reset flush(es), %d resync note(s)",
            self.trace_count,
            len(self.pcs),
            self.last_pc,
            self._sym(self.last_pc),
            self.max_depth,
            len(self.trap_events),
            self.reset_flushes,
            self.resync_notes,
        )
        if self.stack:
            log(level, "firmware call stack (innermost first):")
            for i, frame in enumerate(reversed(self.stack)):
                if frame[0] == "call":
                    _, site, target = frame
                    where = self._sym(target) if target is not None else "?"
                    log(
                        level,
                        "  #%d %s <- called from 0x%08x (%s)",
                        i,
                        where,
                        site,
                        self._sym(site),
                    )
                else:
                    _, pc, ecause, interrupt, tval = frame
                    log(
                        level,
                        "  #%d [trap] %s at 0x%08x (%s) tval=0x%08x",
                        i,
                        self._cause_str(ecause, interrupt),
                        pc,
                        self._sym(pc),
                        tval,
                    )
        for cyc, pc, ecause, interrupt, tval in self.trap_events:
            log(
                level,
                "trap record: cycle %d %s pc=0x%08x (%s) tval=0x%08x",
                cyc,
                self._cause_str(ecause, interrupt),
                pc,
                self._sym(pc),
                tval,
            )
        if self.ring:
            tail = list(self.ring)[-ring_tail:]
            log(level, "last %d retirements (cycle pc insn symbol):", len(tail))
            for cyc, pc, insn in tail:
                log(level, "  %10d %08x %08x %s", cyc, pc, insn, self._sym(pc))

    def report_phase(self) -> None:
        if self._trace_file is not None:
            self._trace_file.close()
            self._trace_file = None
        if self.active:
            self.dump_diagnostics(logging.INFO)
