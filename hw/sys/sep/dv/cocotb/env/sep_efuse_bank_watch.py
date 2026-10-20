# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTP bank snapshot and bit diff, and the post-guard fuse command monitor.

Both read tb_top observation taps and drive nothing (docs/SEP_TB_ARCH.adoc,
observation probes):

* ``otp_bank_probe_o`` -- the 256 bank words that SEP reaches, word i at bits
  [32i+31:32i]. The bench has no bank write hook, so a bank bit changes only by a
  fuse program.
* ``efuse_shim_cmd_{valid,command,address,program_data,len}_o`` -- the fuse command
  at the ``sep`` output ``efuse_shim_command_req_o``, after the guard. The request
  valids of the read and program interfaces sit before the guard and cannot show a
  refusal; this tap can.
* ``efuse_bank_psel_o`` -- the APB ``psel`` of the shim request to the bank model.

``SepEfuseBank`` takes a snapshot and diffs a later read against it, bit by bit.
``SepEfuseBankWatch`` compares the bank with a reference on every clock and records
each clock on which it differs (the "no bank bit changes before sense done" window,
and ``t_land`` of a program). ``SepShimCmdMonitor`` records every command at the tap
and, built with ``psel=True``, also every clock with ``psel`` 1; ``pulses_between``
counts the clocks with post-guard valid 1 and with ``psel`` 1 between two marks, so a
pulse of one clock is counted.

Command record rule: a command is recorded on the first clock of a valid run, and
again on a clock where valid stays 1 and the command, address, data or length
changes. A command that the shim re-issues after a response shows as a new valid
run, so a held program that repeats shows one record per repeat.

The background tasks use ``MonitorLife`` (env/sep_monitor_life.py): a query raises
``MonitorLifeError`` if the task ended without ``stop`` or the mark is from an
earlier run, and ``BankWatchIdleError`` if the watcher took no sample after the mark,
so a "never changed" or "no command" statement cannot pass on an empty record. An
X or Z bit in a sampled tap raises ``BankWatchXZError`` (Verilator is 2-state).

The decode and diff functions at module level are pure and need no simulator.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from sep_monitor_life import MonitorLife

BANK_WORDS = 256
WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1

# efuse_pkg::fuse_command_e (hw/ip/efuse/doc/interface.adoc, Fuse Command Protocol).
FUSE_COMMAND_READ = 0b00
FUSE_COMMAND_PROGRAM = 0b01
FUSE_COMMAND_PROGRAM_READ_BACK = 0b10
COMMAND_NAMES = {
    FUSE_COMMAND_READ: "READ",
    FUSE_COMMAND_PROGRAM: "PROGRAM",
    FUSE_COMMAND_PROGRAM_READ_BACK: "PROGRAM_READ_BACK",
}
PROGRAM_COMMANDS = (FUSE_COMMAND_PROGRAM, FUSE_COMMAND_PROGRAM_READ_BACK)

BANK_PROBE = "otp_bank_probe_o"
CMD_TAPS = {
    "valid": "efuse_shim_cmd_valid_o",
    "command": "efuse_shim_cmd_command_o",
    "address": "efuse_shim_cmd_address_o",
    "data": "efuse_shim_cmd_program_data_o",
    "length": "efuse_shim_cmd_len_o",
}
PSEL_TAP = "efuse_bank_psel_o"


class BankWatchXZError(AssertionError):
    """A sampled tap bit resolved to X or Z."""


class BankWatchIdleError(AssertionError):
    """A query covers a window in which the watcher took no sample."""


class BankWatchTimeout(AssertionError):
    """A bounded wait of a watcher expired."""


# --------------------------------------------------------------------------
# Pure decode and diff
# --------------------------------------------------------------------------


def _binstr(value: Any) -> str:
    s = getattr(value, "binstr", None)
    return (s if s is not None else str(value)).strip()


def decode_bits(bits: str, name: str) -> int:
    """Integer of a 0/1 string, MSB first; raise on X or Z."""
    bad = [i for i, c in enumerate(bits) if c not in "01"]
    if bad:
        raise BankWatchXZError(
            f"BANK-WATCH-XZ FAIL: {name} has {len(bad)} X/Z bits (first at msb-index {bad[0]})"
        )
    return int(bits, 2) if bits else 0


def bank_words(value: int) -> tuple[int, ...]:
    """The 256 bank words of the packed probe value, word i at bits [32i+31:32i]."""
    return tuple((value >> (WORD_BITS * i)) & WORD_MASK for i in range(BANK_WORDS))


@dataclass(frozen=True)
class BitChange:
    """One bank bit that differs between two images."""

    word: int
    bit: int
    old: int
    new: int

    @property
    def addr(self) -> int:
        """Bit address of the changed bit (8 x byte offset + bit index)."""
        return WORD_BITS * self.word + self.bit


def bank_diff(old: Sequence[int], new: Sequence[int]) -> list[BitChange]:
    """Every bit that differs between two 256-word images, in bit-address order."""
    if len(old) != BANK_WORDS or len(new) != BANK_WORDS:
        raise ValueError(f"bank_diff needs two {BANK_WORDS}-word images")
    out = []
    for w, (a, b) in enumerate(zip(old, new)):
        x = (a ^ b) & WORD_MASK
        while x:
            bit = (x & -x).bit_length() - 1
            out.append(BitChange(w, bit, (a >> bit) & 1, (b >> bit) & 1))
            x &= x - 1
    return out


def diff_is_exactly(changes: Sequence[BitChange], bit_addr: int) -> bool:
    """True when the diff is one 0->1 change at ``bit_addr`` (a landed program)."""
    return (
        len(changes) == 1
        and changes[0].addr == bit_addr
        and changes[0].old == 0
        and changes[0].new == 1
    )


def diff_log(changes: Sequence[BitChange], limit: int = 8) -> str:
    """Short log form of a diff: count and the first changed bit addresses."""
    head = ",".join(f"0x{c.addr:x}:{c.old}->{c.new}" for c in changes[:limit])
    more = "" if len(changes) <= limit else f",+{len(changes) - limit}"
    return f"n={len(changes)} bits=[{head}{more}]"


@dataclass(frozen=True)
class ShimCmd:
    """One fuse command at the post-guard tap."""

    clk: int
    command: int
    address: int
    data: int
    length: int

    @property
    def name(self) -> str:
        return COMMAND_NAMES.get(self.command, f"UNKNOWN_{self.command}")

    @property
    def is_program(self) -> bool:
        return self.command in PROGRAM_COMMANDS

    @property
    def is_read(self) -> bool:
        return self.command == FUSE_COMMAND_READ


def command_edges(samples: Sequence[tuple[int, int, int, int, int, int]]) -> list[ShimCmd]:
    """Commands of a per-clock sample list ``(clk, valid, command, address, data, length)``.

    A record starts on the first clock of a valid run and on a clock where valid stays
    1 and any field changes (the module record rule).
    """
    out: list[ShimCmd] = []
    prev: tuple[int, int, int, int, int] | None = None
    for clk, valid, command, address, data, length in samples:
        cur = (valid, command, address, data, length)
        if is_command_edge(prev, cur):
            out.append(ShimCmd(clk, command, address, data, length))
        prev = cur
    return out


def is_command_edge(
    prev: tuple[int, int, int, int, int] | None, cur: tuple[int, int, int, int, int]
) -> bool:
    """True when ``cur`` (valid, command, address, data, length) starts a command record."""
    return bool(cur[0]) and (prev is None or not prev[0] or prev[1:] != cur[1:])


def select_commands(
    cmds: Sequence[ShimCmd], *, program: bool | None = None, address: int | None = None
) -> list[ShimCmd]:
    """Commands that are (not) programs, at ``address`` when given."""
    out = []
    for c in cmds:
        if program is not None and c.is_program != program:
            continue
        if address is not None and c.address != address:
            continue
        out.append(c)
    return out


# --------------------------------------------------------------------------
# Simulator-side watchers
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PulseCount:
    """Clocks sampled between two marks, and those with post-guard valid 1 and psel 1."""

    edges: int
    valid: int
    psel: int


@dataclass(frozen=True)
class WatchMark:
    """A point in a watcher record: the clock, the record length and the run epoch."""

    clk: int
    index: int
    epoch: int


class SepEfuseBank:
    """Snapshot of ``otp_bank_probe_o`` and the bit diff of a later read."""

    def __init__(self, dut: Any = None) -> None:
        self.dut: Any = dut if dut is not None else cocotb.top
        self.sig = getattr(self.dut, BANK_PROBE)

    def read(self) -> tuple[int, ...]:
        """The 256 bank words now."""
        return bank_words(decode_bits(_binstr(self.sig.value), BANK_PROBE))

    def snapshot(self) -> tuple[int, ...]:
        return self.read()

    def diff_since(self, snap: Sequence[int]) -> list[BitChange]:
        return bank_diff(snap, self.read())


class SepEfuseBankWatch:
    """Compares the bank with a reference image on every clock.

    ``start(reference)`` begins the per-clock compare; ``changed_clks_since(mark)``
    returns every clock after the mark on which the bank differed from the reference,
    and ``first_change_since(mark)`` the first one (``t_land``).
    """

    def __init__(self, dut: Any = None) -> None:
        self.dut: Any = dut if dut is not None else cocotb.top
        self.bank = SepEfuseBank(self.dut)
        self.clk = 0
        self.reference: tuple[int, ...] | None = None
        self.changed: list[tuple[int, list[BitChange]]] = []
        self._task: Any = None
        self.life = MonitorLife("BANK-WATCH", lambda: self.clk)
        self.log = logging.getLogger("cocotb.sep_efuse_bank_watch")

    def start(self, reference: Sequence[int] | None = None) -> SepEfuseBankWatch:
        """Start the compare against ``reference`` (default: the bank now)."""
        self.reference = tuple(reference) if reference is not None else self.bank.read()
        if len(self.reference) != BANK_WORDS:
            raise ValueError(f"reference must hold {BANK_WORDS} words")
        if self._task is None:
            self._task = self.life.start(self._run())
        return self

    async def stop(self) -> None:
        self._task = None
        await self.life.stop()

    def mark(self) -> WatchMark:
        return WatchMark(self.clk, len(self.changed), self.life.mark_epoch())

    def _require_sampled(self, mark: WatchMark) -> None:
        self.life.check(mark.epoch)
        if self.clk <= mark.clk:
            raise BankWatchIdleError(
                f"BANK-WATCH FAIL: no sample after the mark (clk={self.clk} mark_clk={mark.clk})"
            )

    def sampled_clks_since(self, mark: WatchMark) -> int:
        self._require_sampled(mark)
        return self.clk - mark.clk

    def changed_clks_since(self, mark: WatchMark) -> list[int]:
        self._require_sampled(mark)
        return [c for c, _d in self.changed[mark.index :]]

    def first_change_since(self, mark: WatchMark) -> tuple[int, list[BitChange]] | None:
        self._require_sampled(mark)
        rest = self.changed[mark.index :]
        return rest[0] if rest else None

    async def wait_change(self, mark: WatchMark, bound: int) -> tuple[int, list[BitChange]]:
        """Wait at most ``bound`` clocks for a clock on which the bank differs."""
        for _ in range(bound + 1):
            self.life.check(mark.epoch)
            if len(self.changed) > mark.index:
                return self.changed[mark.index]
            self.life.require_running()
            await RisingEdge(self.dut.clk_i)
        raise BankWatchTimeout(f"bank did not change within {bound} clocks after clock {mark.clk}")

    async def _run(self) -> None:
        clk = self.dut.clk_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            self.clk += 1
            words = self.bank.read()
            assert self.reference is not None
            if words != self.reference:
                self.changed.append((self.clk, bank_diff(self.reference, words)))


class SepShimCmdMonitor:
    """Records every fuse command at the post-guard tap ``efuse_shim_cmd_*_o``.

    With ``psel=True`` it also samples ``efuse_bank_psel_o``; an X or Z on it raises.
    """

    def __init__(self, dut: Any = None, *, psel: bool = False) -> None:
        self.dut: Any = dut if dut is not None else cocotb.top
        self.sigs = {k: getattr(self.dut, v) for k, v in CMD_TAPS.items()}
        self.psel_sig: Any = getattr(self.dut, PSEL_TAP) if psel else None
        self.clk = 0
        self.cmds: list[ShimCmd] = []
        self.valid_clks: list[int] = []
        self.psel_clks: list[int] = []
        self._prev: tuple[int, int, int, int, int] | None = None
        self._task: Any = None
        self.life = MonitorLife("SHIM-CMD", lambda: self.clk)
        self.log = logging.getLogger("cocotb.sep_efuse_bank_watch")

    def start(self) -> SepShimCmdMonitor:
        if self._task is None:
            self._prev = None
            self._task = self.life.start(self._run())
        return self

    async def stop(self) -> None:
        self._task = None
        await self.life.stop()

    def mark(self) -> WatchMark:
        return WatchMark(self.clk, len(self.cmds), self.life.mark_epoch())

    def commands_since(
        self, mark: WatchMark, *, program: bool | None = None, address: int | None = None
    ) -> list[ShimCmd]:
        """Commands recorded after ``mark``; raises if no clock was sampled since."""
        self.life.check(mark.epoch)
        if self.clk <= mark.clk:
            raise BankWatchIdleError(
                f"SHIM-CMD FAIL: no sample after the mark (clk={self.clk} mark_clk={mark.clk})"
            )
        return select_commands(self.cmds[mark.index :], program=program, address=address)

    def programs_since(self, mark: WatchMark, address: int | None = None) -> list[ShimCmd]:
        return self.commands_since(mark, program=True, address=address)

    def reads_since(self, mark: WatchMark, address: int | None = None) -> list[ShimCmd]:
        return self.commands_since(mark, program=False, address=address)

    def pulses_between(self, start: WatchMark, end: WatchMark) -> PulseCount:
        """Counts over the clocks after ``start`` up to and including ``end``.

        Both marks must be from the open run, with at least one clock between them.
        """
        if self.psel_sig is None:
            raise ValueError("pulses_between needs a monitor built with psel=True")
        self.life.check(start.epoch)
        self.life.check(end.epoch)
        if end.clk <= start.clk:
            raise BankWatchIdleError(
                f"SHIM-CMD FAIL: no sample between the marks (start={start.clk} end={end.clk})"
            )

        def _n(clks: list[int]) -> int:
            return bisect_right(clks, end.clk) - bisect_right(clks, start.clk)

        return PulseCount(end.clk - start.clk, _n(self.valid_clks), _n(self.psel_clks))

    def _sample(self) -> tuple[int, int, int, int, int]:
        vals = {k: decode_bits(_binstr(s.value), CMD_TAPS[k]) for k, s in self.sigs.items()}
        return vals["valid"], vals["command"], vals["address"], vals["data"], vals["length"]

    async def _run(self) -> None:
        clk = self.dut.clk_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            self.clk += 1
            # Only valid must be known on every clock; the payload is decoded when valid is 1.
            valid = decode_bits(_binstr(self.sigs["valid"].value), CMD_TAPS["valid"])
            if valid:
                self.valid_clks.append(self.clk)
            if self.psel_sig is not None and decode_bits(_binstr(self.psel_sig.value), PSEL_TAP):
                self.psel_clks.append(self.clk)
            cur = self._sample() if valid else (0, 0, 0, 0, 0)
            if is_command_edge(self._prev, cur):
                self.cmds.append(ShimCmd(self.clk, *cur[1:]))
            self._prev = cur
