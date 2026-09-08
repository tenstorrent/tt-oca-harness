# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive processor-state monitor on the SMC Rocket hart-0 retirement trace.

``tb_top.sv`` exports hart 0's CSR trace bundle -- ``io_trace_0_{valid, iaddr,
insn, exception}`` plus the ``io_cause`` / ``io_tval`` the core presents with
it -- as ``tb_cpu_trace_*`` (single instance) or ``<inst>_cpu_trace_*`` (dual
bench), masked while the core reset is asserted. From those samples the
monitor reconstructs where the firmware is and how it got there, so a run that
hangs, traps, or fails reports more than a retired PC:

  * **PC history** -- every retirement feeds a tally (count + distinct set) and
    a bounded ring of the most recent retirements for post-mortem dumps.
  * **Shadow call stack** -- retired instructions are decoded (RV64IMAC) for
    calls (``jal``/``jalr``/``c.jalr`` linking ra/t0), returns (``jalr``/``c.jr``
    through ra/t0), and ``mret``, maintaining a call stack that symbolizes into
    a firmware backtrace from the staged nm listing. RV64C has no ``c.jal``
    (that encoding is ``c.addiw``), so the compressed decode links only through
    ``c.jalr``.
  * **Trap records** -- a retirement flagged as an exception is captured with
    the cause (bit 63 = interrupt) and tval, and pushed as a synthetic stack
    frame that ``mret`` pops, so a backtrace shows the trap and where it hit.
  * **Hang watch** -- after the first retirement, a long retirement-free gap
    out of reset logs a one-shot warning with a full dump. Diagnostic only:
    a core parked in ``wfi`` or a terminal loop is legitimate.

Three pieces, so both SMC benches share one reconstruction:

  * :class:`SmcCpuTraceState` -- the reconstruction and its dump, plain Python
    over integer samples;
  * :func:`watch_cpu_trace` -- the cocotb sampler, one ``clk_smc_i`` edge per
    sample, usable from any bench as a ``start_soon`` task;
  * :class:`SmcCpuTraceMonitor` -- the PyUVM component ``SmcEnv`` builds. It
    idles unless a firmware plusarg (``+smc_rom_hex``, ``+smc_scratch_ram_hex``
    or ``+rom_bin64``) names an image, resolves the matching ``.sym`` in the
    simulator cwd, and dumps at report time. ``+smc_trace_log`` streams every
    retirement to ``smc_trace.log``.

Reconstruction hiccups (pop of an empty stack, depth overflow) are logged and
tallied, never failed: pass/fail judgement stays with the sequences and the
scoreboard. The SEP bench and the SMU wrapper carry the RV32 realizations of
the same monitor (``sep_cpu_trace_monitor.py``, ``smu_sep_cpu_trace_monitor.py``).
"""

from __future__ import annotations

import logging
import os
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import uvm_component

__all__ = [
    "SmcCpuTraceMonitor",
    "SmcCpuTraceState",
    "TrapRecord",
    "load_nm_symbols",
    "watch_cpu_trace",
]

# RISC-V link registers: x1/ra and x5/t0 alternate link. rd in the set =>
# call; jalr/c.jr with rd=x0 through the set => return.
_LINK_REGS = (1, 5)
_MRET = 0x3020_0073

# mcause exception codes (interrupt bit clear). Unknown causes print numerically.
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
    9: "ecall (S)",
    11: "ecall (M)",
    12: "insn page fault",
    13: "load page fault",
    15: "store page fault",
}

_RING_DEPTH = 512
_STACK_CAP = 64
# Traps past this count log at DEBUG: a core spinning through a fault handler
# would otherwise flood the log with one WARNING per cycle.
_TRAP_WARN_LIMIT = 8
# A PC this far past the nearest preceding symbol is not inside that function:
# it falls in the gap between two loaded images. Report bare hex instead.
_MAX_SYM_OFF = 0x1_0000
# Rocket's vaddrBitsExtended; the trace address and tval are this wide.
_PC_MASK = (1 << 58) - 1
_INSN_MASK = 0xFFFF_FFFF
_CAUSE_INTERRUPT_BIT = 63
_CAUSE_CODE_MASK = 0xFF
# nm type codes that mark code: text (t/T) plus weak (w/W) -- picolibc exports
# several weak entry points that are the only name a PC inside them has.
_CODE_TYPES = frozenset("tTwW")

# Plusargs whose presence means an SMC image is loaded and hart 0 executes.
FIRMWARE_PLUSARGS = ("smc_rom_hex", "smc_scratch_ram_hex", "rom_bin64")
# The `.sym` listing derived from each image plusarg: the shared firmware
# engine names it <test>.<mode>.sym, the production ROM Makefile <rom>.sym.
_SYM_FOR_IMAGE = {
    "smc_scratch_ram_hex": (".ecc.hex", ".sram.sym"),
    "smc_rom_hex": (".rom.hex", ".rom.sym"),
    "bfm_rom_hex": (".rom.hex", ".rom.sym"),
    "rom_bin64": (".bin64", ".sym"),
}
_TRACE_FIELDS = ("valid", "pc", "insn", "exc", "cause", "tval")


class _Flow(Enum):
    CALL = "call"
    RET = "ret"
    MRET = "mret"


@dataclass(frozen=True)
class TrapRecord:
    """One exception retirement as the trace bundle reported it."""

    cycle: int
    pc: int
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
    """Classify one retired RV64IMAC encoding as control flow of interest.

    The trace carries compressed encodings unexpanded in the low half-word;
    16-vs-32-bit is the standard low-two-bits test.
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
    if c & 0x3 == 0x2 and (c >> 13) & 0x7 == 0x4:
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


def load_nm_symbols(path: str) -> list[tuple[int, str]]:
    """``(addr, name)`` code symbols of one ``nm -B -n`` listing; ``[]`` if unreadable.

    Lines are ``<hex addr> <type> <name>``; undefined symbols have no address
    column and are skipped, as are non-code types (data would otherwise
    swallow PCs that fall past the last text symbol).
    """
    out: list[tuple[int, str]] = []
    try:
        with open(path, "r", encoding="ascii", errors="replace") as stream:
            for line in stream:
                parts = line.split(None, 2)
                if len(parts) != 3 or parts[1] not in _CODE_TYPES:
                    continue
                try:
                    out.append((int(parts[0], 16), parts[2].strip()))
                except ValueError:
                    continue
    except OSError:
        return []
    return sorted(out)


class SmcCpuTraceState:
    """Retirement-trace reconstruction: PC history, shadow call stack, traps.

    Bench-neutral: fed one clock at a time through :meth:`sample`, logs through
    the logger it is given, and never touches a simulator handle.
    """

    def __init__(self, name: str, logger: logging.Logger, *, hang_cycles: int = 20_000) -> None:
        self.name = name
        self.log = logger
        self.hang_cycles = hang_cycles
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
        self.symbol_files: list[str] = []
        self._syms: list[tuple[int, str]] = []
        self._addrs: list[int] = []
        self._fill_target = False
        self._idle = 0
        self._was_in_reset = True
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
        self.log.info("[%s] loaded %d code symbols from %s", self.name, len(syms), source)

    def attach_symbol_file(self, path: str) -> bool:
        """Attach the listing at ``path`` if it yields code symbols."""
        syms = load_nm_symbols(path)
        if not syms:
            return False
        self.attach_symbols(syms, path)
        return True

    def symbolize(self, pc: int) -> str:
        """``name+0xoff`` for the symbol covering ``pc``; bare hex outside any."""
        i = bisect_right(self._addrs, pc) - 1
        if i < 0:
            return f"0x{pc:010x}"
        addr, name = self._syms[i]
        off = pc - addr
        if off >= _MAX_SYM_OFF:
            return f"0x{pc:010x}"
        return name if off == 0 else f"{name}+0x{off:x}"

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    def open_trace_log(self, path: str) -> None:
        self._trace_file = open(path, "w")

    def close_trace_log(self) -> None:
        if self._trace_file is not None:
            self._trace_file.close()
            self._trace_file = None

    def sample(
        self,
        cycle: int,
        *,
        in_reset: bool,
        valid: bool,
        pc: int = 0,
        insn: int = 0,
        exc: int = 0,
        cause: int = 0,
        tval: int = 0,
    ) -> None:
        """Fold in one clock of the trace bundle."""
        if in_reset:
            if not self._was_in_reset and (self.stack or self._fill_target):
                self.log.info(
                    "[%s] core reset asserted at cycle %d; flushing shadow stack (depth %d)",
                    self.name,
                    cycle,
                    len(self.stack),
                )
                self.stack.clear()
                self._fill_target = False
                self.reset_flushes += 1
            self._was_in_reset = True
            self._idle = 0
            return
        self._was_in_reset = False
        if valid:
            self._idle = 0
            self._hang_warned = False
            self._note_retire(
                cycle, pc & _PC_MASK, insn & _INSN_MASK, exc=exc, cause=cause, tval=tval & _PC_MASK
            )
        elif self.trace_count and not self._hang_warned:
            self._idle += 1
            if self._idle >= self.hang_cycles:
                self._hang_warned = True
                self.log.warning(
                    "[%s] no instruction retired for %d cycles (last pc 0x%010x %s); "
                    "possible hang -- diagnostic only, wfi/terminal loops are legitimate",
                    self.name,
                    self._idle,
                    self.last_pc,
                    self.symbolize(self.last_pc),
                )
                self.dump(logging.WARNING)

    def _note_retire(
        self, cycle: int, pc: int, insn: int, *, exc: int, cause: int, tval: int
    ) -> None:
        self.trace_count += 1
        self.last_pc = pc
        self.pcs.add(pc)
        self.ring.append((cycle, pc, insn))
        if self._trace_file is not None:
            self._trace_file.write(f"{cycle:>10} {pc:010x} {insn:08x} {self.symbolize(pc)}\n")
        if self._fill_target:
            # First retirement after a call is the callee entry.
            top = self.stack[-1]
            if isinstance(top, _CallFrame):
                top.target = pc
            self._fill_target = False
        if exc:
            interrupt = (cause >> _CAUSE_INTERRUPT_BIT) & 1
            ecause = cause & _CAUSE_CODE_MASK
            self.trap_events.append(TrapRecord(cycle, pc, ecause, interrupt, tval))
            self._push(_TrapFrame(pc, ecause, interrupt, tval))
            level = logging.WARNING if len(self.trap_events) <= _TRAP_WARN_LIMIT else logging.DEBUG
            self.log.log(
                level,
                "[%s] trap at cycle %d: %s pc=0x%010x (%s) tval=0x%010x",
                self.name,
                cycle,
                _cause_str(ecause, interrupt),
                pc,
                self.symbolize(pc),
                tval,
            )
            return
        flow = _decode_flow(insn)
        if flow is None:
            return
        if flow is _Flow.CALL:
            self._push(_CallFrame(pc))
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
    # Reporting
    # ------------------------------------------------------------------
    def report_lines(self, ring_tail: int = 32) -> list[str]:
        """Symbolized processor-state report: call stack, traps, recent PCs."""
        lines = [
            f"[{self.name}] CPU state: {self.trace_count} retired, {len(self.pcs)} distinct PCs, "
            f"last pc 0x{self.last_pc:010x} ({self.symbolize(self.last_pc)}), "
            f"max call depth {self.max_depth}, {len(self.trap_events)} trap(s), "
            f"{self.reset_flushes} reset flush(es), {self.resync_notes} resync note(s)"
        ]
        if self.stack:
            lines.append(f"[{self.name}] firmware call stack (innermost first):")
            for i, frame in enumerate(reversed(self.stack)):
                if isinstance(frame, _CallFrame):
                    where = self.symbolize(frame.target) if frame.target is not None else "?"
                    lines.append(
                        f"  #{i} {where} <- called from 0x{frame.site:010x} "
                        f"({self.symbolize(frame.site)})"
                    )
                else:
                    lines.append(
                        f"  #{i} [trap] {_cause_str(frame.ecause, frame.interrupt)} at "
                        f"0x{frame.pc:010x} ({self.symbolize(frame.pc)}) tval=0x{frame.tval:010x}"
                    )
        for rec in self.trap_events[-ring_tail:]:
            lines.append(
                f"[{self.name}] trap record: cycle {rec.cycle} {_cause_str(rec.ecause, rec.interrupt)} "
                f"pc=0x{rec.pc:010x} ({self.symbolize(rec.pc)}) tval=0x{rec.tval:010x}"
            )
        if self.ring:
            tail = list(self.ring)[-ring_tail:]
            lines.append(f"[{self.name}] last {len(tail)} retirements (cycle pc insn symbol):")
            lines.extend(
                f"  {cyc:>10} {pc:010x} {insn:08x} {self.symbolize(pc)}" for cyc, pc, insn in tail
            )
        return lines

    def dump(self, level: int = logging.INFO, ring_tail: int = 32) -> None:
        for line in self.report_lines(ring_tail):
            self.log.log(level, "%s", line)


def _resolved_int(signal) -> int:
    """Resolved integer value; an X/Z sample reads as 0.

    The exported fields are masked while the core reset is asserted, so an
    unresolved sample can only occur before the bench drives the resets, when
    no retirement is possible.
    """
    value = signal.value
    if not value.is_resolvable:
        return 0
    return int(value)


async def watch_cpu_trace(
    dut: Any, clk: Any, state: SmcCpuTraceState, *, prefix: str, reset_name: str
) -> None:
    """Feed ``state`` one ``clk`` edge at a time from ``<prefix>_*`` and ``reset_name``.

    Returns without sampling when the ports are absent, so a bench without the
    trace taps keeps running with the monitor idle.
    """
    sig = {field: getattr(dut, f"{prefix}_{field}", None) for field in _TRACE_FIELDS}
    reset_n = getattr(dut, reset_name, None)
    if sig["valid"] is None or sig["pc"] is None or reset_n is None:
        state.log.warning(
            "[%s] trace ports %s_* not found; CPU trace monitor idle", state.name, prefix
        )
        return
    cycle = 0
    while True:
        await RisingEdge(clk)
        cycle += 1
        if not _resolved_int(reset_n):
            state.sample(cycle, in_reset=True, valid=False)
            continue
        if not _resolved_int(sig["valid"]):
            state.sample(cycle, in_reset=False, valid=False)
            continue
        state.sample(
            cycle,
            in_reset=False,
            valid=True,
            pc=_resolved_int(sig["pc"]),
            insn=_resolved_int(sig["insn"]),
            exc=_resolved_int(sig["exc"]),
            cause=_resolved_int(sig["cause"]),
            tval=_resolved_int(sig["tval"]),
        )


def symbol_file_for_image(plusarg: str, image: str) -> str | None:
    """Basename of the staged ``.sym`` matching one firmware image plusarg."""
    suffix, sym_suffix = _SYM_FOR_IMAGE[plusarg]
    base = os.path.basename(image)
    if base.endswith(suffix):
        return base[: -len(suffix)] + sym_suffix
    return None


class SmcCpuTraceMonitor(uvm_component):
    """PyUVM wrapper over :class:`SmcCpuTraceState` for the single-instance bench.

    Publishes nothing on an analysis port: consumers read the state directly
    (``env.cpu_trace_mon.state``). Idle unless a firmware plusarg is present.
    """

    def __init__(self, name: str, parent) -> None:
        super().__init__(name, parent)
        self.state = SmcCpuTraceState("smc-hart0", self.logger)
        self.active = False

    def build_phase(self) -> None:
        explicit = cocotb.plusargs.get("smc_sym")
        candidates: list[str] = [str(explicit)] if explicit is not None else []
        for plusarg in FIRMWARE_PLUSARGS:
            image = cocotb.plusargs.get(plusarg)
            if image is None:
                continue
            derived = symbol_file_for_image(plusarg, str(image))
            if derived is not None:
                candidates.append(derived)
        attached = [path for path in candidates if self.state.attach_symbol_file(path)]
        if candidates and not attached:
            self.logger.info("no SMC symbol listing among %s; trace PCs stay numeric", candidates)

    async def run_phase(self) -> None:
        if not any(name in cocotb.plusargs for name in FIRMWARE_PLUSARGS):
            return
        dut = cocotb.top
        if "smc_trace_log" in cocotb.plusargs:
            self.state.open_trace_log("smc_trace.log")
        self.active = True
        self.logger.info(
            "SMC CPU trace monitor active (hang watch at %d cycles)", self.state.hang_cycles
        )
        await watch_cpu_trace(
            dut, dut.clk_smc_i, self.state, prefix="tb_cpu_trace", reset_name="tb_cpu_core_reset_n"
        )

    def dump_diagnostics(self, level: int = logging.INFO) -> None:
        if self.active:
            self.state.dump(level)

    def report_phase(self) -> None:
        self.state.close_trace_log()
        self.dump_diagnostics(logging.INFO)
