# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Live follower of the firmware console for a CPU leaf, and its record ledger.

The firmware writes console characters to the outbound responder
(``tb/sep_outbound_mbx.sv``), which tb_top brings out on ``fw_char_o`` /
``fw_char_valid_o``. :class:`SepFwConsole` assembles the characters into lines
on every rising edge of ``clk_i`` (read-only phase; it drives nothing) and
acts on four line shapes, printed by ``fw/tests/common/sep_console_rec.h``:

``M G <leg>`` / ``M C <leg>``
    A graded or a control leg starts. With ``graded_test`` set, the follower
    opens that test's graded window (``env/sep_fcov_gate``) for ``M G`` and
    closes it for ``M C``, on the next clock edge, where a write is legal. The
    firmware spins after each marker line, so no bus access of the leg falls
    between the line and the gate write. Each registered mark hook is called
    in the read-only phase of the clock that ends the marker line, so a tap or
    bit watcher marks before the leg starts.
``CHK-<NAME> PASS|FAIL k=v ...`` / ``CTL-<NAME> ...`` / ``OBS-<NAME> LOG ...``
    A check, control or observation record of the firmware. The key=value
    tokens are parsed; a ``0x`` value becomes an int.
``REQ <what> k=v ...``
    A request to the host. A handler registered with :meth:`on_request` runs
    as a new coroutine, so it can drive inputs and wait.
any other line
    Kept in :attr:`lines` with its clock index.

The firmware CHK lines are graded evidence. :meth:`relay_chk` logs each one on
the test logger, so the evidence gate of ``sep_base_test`` counts it, and
fails the leaf on a ``FAIL`` line. :meth:`require_counts` fails the leaf when
a named check printed fewer lines than the contract requires, or when a
blocked check printed a ``CHK`` line instead of its ``OBS`` line.

Usage::

    con = SepFwConsole(self, graded_test="sep_pic_reg_rand_test").start()
    con.on_mark(lambda leg, kind: bits.mark())
    ...boot_firmware(...)...
    con.relay_chk()
    con.require_counts({"CHK-RESET": 6, "CHK-RW": 1}, blocked=("CHK-GW-EL",))
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge

from env.sep_fcov_gate import close_graded_window, open_graded_window

_REC = re.compile(r"^((?:CHK|CTL|OBS)-[A-Z0-9_-]+)\s+(PASS|FAIL|LOG)\b(.*)$")


def parse_kv(text: str) -> dict:
    """``k=v`` tokens of ``text``; ``0x`` values become ints, others stay strings."""
    out: dict = {}
    for tok in text.split():
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        if v.lower().startswith("0x"):
            try:
                out[k] = int(v, 16)
                continue
            except ValueError:
                pass
        out[k] = v
    return out


@dataclass
class ConsoleRec:
    """One record line: name (``CHK-RESET``), verdict, key=value fields, text."""

    clk: int
    name: str
    verdict: str
    kv: dict = field(default_factory=dict)
    text: str = ""


class SepFwConsole:
    """Line follower of the firmware console of one CPU leaf."""

    def __init__(self, test, *, graded_test: str | None = None, dut=None) -> None:
        self.test = test
        self.log = test.logger
        self.dut: Any = dut if dut is not None else cocotb.top
        self.graded_test = graded_test
        self.lines: list[tuple[int, str]] = []
        self.recs: list[ConsoleRec] = []
        self.legs: list[tuple[int, str, str]] = []  # (clk, kind G|C, leg)
        self.clk = 0
        self._mark_hooks: list[Callable[[str, str], object]] = []
        self._req: dict[str, Callable[[dict], Coroutine[Any, Any, None]]] = {}
        self._task: Any = None
        self._buf: list[str] = []

    # ---- set-up ----
    def on_mark(self, hook: Callable[[str, str], object]) -> None:
        """Call ``hook(leg, kind)`` in the read-only phase that ends a marker line."""
        self._mark_hooks.append(hook)

    def on_request(self, what: str, handler: Callable[[dict], Coroutine[Any, Any, None]]) -> None:
        """Run ``handler(kv)`` as a coroutine for each ``REQ <what> ...`` line."""
        self._req[what] = handler

    def start(self) -> "SepFwConsole":
        if self._task is None:
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.kill()
            self._task = None
        if self.graded_test is not None:
            close_graded_window(self.log)

    # ---- queries ----
    def records(self, name: str) -> list[ConsoleRec]:
        return [r for r in self.recs if r.name == name]

    def text_lines(self, prefix: str = "") -> list[str]:
        return [t for _, t in self.lines if t.startswith(prefix)]

    async def wait_line(self, prefix: str, bound: int, *, after: int = 0) -> str:
        """Wait up to ``bound`` clocks for a line that starts with ``prefix``,
        among the lines at index ``after`` or later. Returns it (read-only phase)."""
        start = self.clk
        while True:
            for _, t in self.lines[after:]:
                if t.startswith(prefix):
                    return t
            if self.clk - start >= bound:
                raise AssertionError(f"FW-CONSOLE FAIL: no '{prefix}' line within {bound} clocks")
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()

    # ---- grading ----
    def relay_chk(self) -> int:
        """Log every firmware CHK line on the test logger; fail on a FAIL line.

        Returns the number of CHK lines relayed.
        """
        n = 0
        for r in self.recs:
            if not r.name.startswith("CHK-"):
                continue
            if r.verdict != "PASS":
                raise AssertionError(f"{r.name} FAIL (firmware): {r.text}")
            self.log.info("%s (firmware)", r.text)
            n += 1
        return n

    def require_counts(self, expected: dict[str, int], *, blocked: tuple[str, ...] = ()) -> None:
        """Fail unless each ``expected`` check printed at least that many PASS
        lines, and no ``blocked`` check printed a CHK line."""
        problems = []
        for name, want in expected.items():
            got = sum(1 for r in self.records(name) if r.verdict == "PASS")
            if got < want:
                problems.append(f"{name}: {got} PASS lines, expected {want}")
        for name in blocked:
            if self.records(name):
                problems.append(f"{name}: a blocked check printed a CHK line")
        summary = " ".join(
            f"{n}={sum(1 for r in self.records(n) if r.verdict == 'PASS')}/{w}"
            for n, w in expected.items()
        )
        if problems:
            raise AssertionError("FW-CHK-COUNT FAIL: " + "; ".join(problems))
        self.log.info("FW-CHK-COUNT LOG %s", summary)

    # ---- follower ----
    async def _run(self) -> None:
        dut = self.dut
        gate: bool | None = None
        while True:
            await RisingEdge(dut.clk_i)
            if gate is not None and self.graded_test is not None:
                if gate:
                    open_graded_window(self.graded_test, self.log)
                else:
                    close_graded_window(self.log)
            gate = None
            await ReadOnly()
            self.clk += 1
            v = dut.fw_char_valid_o.value
            if not (v.is_resolvable and int(v)):
                continue
            ch = chr(int(dut.fw_char_o.value) & 0xFF)
            if ch != "\n":
                self._buf.append(ch)
                continue
            text = "".join(self._buf).rstrip("\r")
            self._buf = []
            self.lines.append((self.clk, text))
            if text.startswith("M ") and len(text.split()) >= 3:
                _, kind, leg = text.split(None, 2)
                self.legs.append((self.clk, kind, leg))
                for hook in self._mark_hooks:
                    hook(leg, kind)
                gate = kind == "G"
                continue
            m = _REC.match(text)
            if m:
                self.recs.append(
                    ConsoleRec(self.clk, m.group(1), m.group(2), parse_kv(m.group(3)), text)
                )
                continue
            if text.startswith("REQ "):
                parts = text.split(None, 2)
                what = parts[1] if len(parts) > 1 else ""
                handler = self._req.get(what)
                if handler is None:
                    raise AssertionError(f"FW-CONSOLE FAIL: no handler for '{text}'")
                cocotb.start_soon(handler(parse_kv(parts[2] if len(parts) > 2 else "")))


__all__ = ["ConsoleRec", "SepFwConsole", "parse_kv"]
