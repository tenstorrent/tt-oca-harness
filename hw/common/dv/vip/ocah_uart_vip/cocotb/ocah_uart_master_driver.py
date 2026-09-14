# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Active host-side UART line driver (native backend).

``OcahUartMasterDriver`` drives serial frames (5..9 data bits LSB first,
optional parity, 1, 1.5, or 2 stop bits, idle-high) onto one cocotb signal
handle at a configurable baud rate. It is the master side of the console link:
the VIP host initiates traffic into the DUT's RX pad. ``OcahUartConsole``
builds on it; tests normally use the console API.

Transmission is queue-based: ``write()`` and ``write_nowait()`` enqueue bytes
and a background pump drives them frame by frame, so a caller may overlap
stimulus with DUT-side polling. ``await wait()`` blocks until the queue is
drained and the line has returned to idle.

Fault injection shares the queue, so a fault lands at a deterministic place in
the byte stream: ``inject_framing_error()`` drives a frame whose stop bit is
low, ``inject_parity_error()`` a frame whose parity bit is inverted,
``send_break()`` holds the line low for a whole number of bit periods, and
``send_glitch()`` drives a low pulse shorter than half a bit. After a fault
the line idles high for one bit period so the next start edge is visible.

Timing is ``round(1e9 / baud)`` ns per bit, snapshotted at every frame
boundary, so ``baud``, ``bits``, ``parity``, and ``stop_bits`` may be
reassigned between frames without a restart. Every driven frame is kept in a
bounded history (``get_frames()``) with its start time.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.handle import Immediate
from cocotb.queue import Queue
from cocotb.triggers import Event, Timer
from cocotb.utils import get_sim_time

from .ocah_uart_types import (
    DEFAULT_BAUD,
    OcahUartFrame,
    OcahUartParity,
    bit_period_ns,
    check_format,
    parity_bit,
)

__all__ = ["OcahUartMasterDriver"]

_HISTORY_MAX = 4096


@dataclass(frozen=True)
class _TxOp:
    """One queued line operation."""

    kind: str
    data: int = 0
    stop_level: int = 1
    invert_parity: bool = False
    periods: float = 0.0
    width_ns: int = 0


class OcahUartMasterDriver:
    """Active UART line driver over one cocotb signal handle.

    Parameters
    ----------
    signal :
        Cocotb signal handle the driver transmits on. Driven to idle
        (logic-1) at construction.
    name :
        Instance label used in log messages and frame records.
    baud :
        Baud rate; the bit period is ``round(1e9 / baud)`` ns.
    bits :
        Data bits per frame (5..9), LSB first.
    parity :
        ``OcahUartParity`` member or its name.
    stop_bits :
        Stop length in bit periods (1, 1.5, or 2).
    max_history :
        Frames ``get_frames()`` holds; the oldest are dropped first.
    """

    def __init__(
        self,
        signal: Any,
        *,
        name: str = "OcahUartMasterDriver",
        baud: int = DEFAULT_BAUD,
        bits: int = 8,
        parity: OcahUartParity | str = OcahUartParity.NONE,
        stop_bits: float = 1,
        max_history: int = _HISTORY_MAX,
    ) -> None:
        self.name = name
        self.log = logging.getLogger(name)
        self._signal = signal
        self._parity = OcahUartParity.coerce(parity)
        check_format(int(bits), self._parity, float(stop_bits))
        self._baud = int(baud)
        bit_period_ns(self._baud)
        self._bits = int(bits)
        self._stop_bits = float(stop_bits)
        self._max_history = int(max_history)

        self._queue: Queue[_TxOp] = Queue()
        self._idle_evt = Event()
        self._idle_evt.set()
        self._active = False
        self._frames: list[OcahUartFrame] = []

        self._stats: dict[str, int] = {
            "bytes_driven": 0,
            "framing_faults": 0,
            "parity_faults": 0,
            "breaks": 0,
            "glitches": 0,
        }

        # Idle-high before the first frame so the DUT RX pad never sees X.
        self._signal.set(Immediate(1))
        self._run_task = cocotb.start_soon(self._run())

    # ------------------------------------------------------------------
    # Configuration properties
    # ------------------------------------------------------------------

    @property
    def baud(self) -> int:
        return self._baud

    @baud.setter
    def baud(self, value: int) -> None:
        bit_period_ns(int(value))
        self._baud = int(value)

    @property
    def bit_ns(self) -> int:
        """Bit period of the configured baud rate in nanoseconds."""
        return bit_period_ns(self._baud)

    @property
    def bits(self) -> int:
        return self._bits

    @bits.setter
    def bits(self, value: int) -> None:
        check_format(int(value), self._parity, self._stop_bits)
        self._bits = int(value)

    @property
    def parity(self) -> OcahUartParity:
        return self._parity

    @parity.setter
    def parity(self, value: OcahUartParity | str) -> None:
        self._parity = OcahUartParity.coerce(value)

    @property
    def stop_bits(self) -> float:
        return self._stop_bits

    @stop_bits.setter
    def stop_bits(self, value: float) -> None:
        check_format(self._bits, self._parity, float(value))
        self._stop_bits = float(value)

    def configure(
        self,
        *,
        baud: int | None = None,
        bits: int | None = None,
        parity: OcahUartParity | str | None = None,
        stop_bits: float | None = None,
    ) -> None:
        """Reassign any of the frame parameters; each lands on the next frame boundary."""
        if baud is not None:
            self.baud = baud
        if parity is not None:
            self.parity = parity
        if bits is not None:
            self.bits = bits
        if stop_bits is not None:
            self.stop_bits = stop_bits

    # ------------------------------------------------------------------
    # Transmit queue
    # ------------------------------------------------------------------

    async def write(self, data: Iterable[int]) -> None:
        """Enqueue ``data`` (any iterable of frame values) for transmission."""
        for value in data:
            await self._queue.put(_TxOp("frame", data=self._checked(int(value))))
            self._idle_evt.clear()

    def write_nowait(self, data: Iterable[int]) -> None:
        """Non-async variant of :meth:`write`."""
        for value in data:
            self._queue.put_nowait(_TxOp("frame", data=self._checked(int(value))))
        self._idle_evt.clear()

    async def inject_framing_error(self, data: int) -> None:
        """Enqueue a frame of ``data`` whose stop bit is driven low."""
        await self._enqueue(_TxOp("frame", data=self._checked(int(data)), stop_level=0))

    async def inject_parity_error(self, data: int) -> None:
        """Enqueue a frame of ``data`` whose parity bit is inverted; needs a parity format."""
        if self._parity is OcahUartParity.NONE:
            raise ValueError(f"{self.name}: a parity fault needs a parity format")
        await self._enqueue(_TxOp("frame", data=self._checked(int(data)), invert_parity=True))

    async def send_break(self, periods: float | None = None) -> None:
        """Hold the line low for ``periods`` bit periods, then idle one period.

        The default covers one full frame plus one period, so a sampler of the
        same format classifies exactly one break.
        """
        if periods is None:
            periods = 2 + self._bits + (0 if self._parity is OcahUartParity.NONE else 1)
        if periods <= 0:
            raise ValueError(f"{self.name}: break length must be positive, got {periods}")
        await self._enqueue(_TxOp("break", periods=float(periods)))

    async def send_glitch(self, width_ns: int) -> None:
        """Drive a low pulse of ``width_ns``, shorter than half a bit, then idle one period."""
        half = self.bit_ns // 2
        if not 0 < int(width_ns) < half:
            raise ValueError(
                f"{self.name}: a glitch must be within 1..{half - 1} ns, got {width_ns}"
            )
        await self._enqueue(_TxOp("glitch", width_ns=int(width_ns)))

    def count(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def idle(self) -> bool:
        return self.empty() and not self._active

    def clear(self) -> None:
        """Drop queued operations. An operation already on the wire completes."""
        while not self._queue.empty():
            self._queue.get_nowait()

    async def wait(self) -> None:
        """Wait until every queued operation has been driven and the line is idle."""
        await self._idle_evt.wait()

    # ------------------------------------------------------------------
    # History and statistics
    # ------------------------------------------------------------------

    def get_frames(self) -> list[OcahUartFrame]:
        """Copy of the driven-frame history, oldest first (breaks included, glitches not)."""
        return list(self._frames)

    def clear_history(self) -> None:
        self._frames.clear()

    def get_statistics(self) -> dict[str, Any]:
        return dict(self._stats)

    def reset_statistics(self) -> None:
        for key in self._stats:
            self._stats[key] = 0

    # ------------------------------------------------------------------
    # Frame pump
    # ------------------------------------------------------------------

    def _checked(self, value: int) -> int:
        limit = 1 << self._bits
        if not 0 <= value < limit:
            raise ValueError(f"{self.name}: frame value {value} exceeds {self._bits} bits")
        return value

    async def _enqueue(self, op: _TxOp) -> None:
        await self._queue.put(op)
        self._idle_evt.clear()

    def _record(self, frame: OcahUartFrame) -> None:
        self._frames.append(frame)
        if len(self._frames) > self._max_history:
            del self._frames[0]

    async def _run(self) -> None:
        while True:
            if self._queue.empty():
                self._active = False
                self._idle_evt.set()
            op = await self._queue.get()
            self._active = True
            bit_ns = self.bit_ns
            if op.kind == "frame":
                await self._drive_frame(op, bit_ns)
            elif op.kind == "break":
                await self._drive_break(op, bit_ns)
            else:
                await self._drive_glitch(op, bit_ns)

    async def _drive_frame(self, op: _TxOp, bit_ns: int) -> None:
        signal = self._signal
        bits, parity, stop_bits = self._bits, self._parity, self._stop_bits
        stop_ns = max(1, round(bit_ns * stop_bits))
        start_ns = _now_ns()
        self.log.debug("%s: TX 0x%02X stop=%d", self.name, op.data, op.stop_level)

        signal.value = 0
        await Timer(bit_ns, "ns")
        for k in range(bits):
            signal.value = (op.data >> k) & 1
            await Timer(bit_ns, "ns")
        pbit = parity_bit(op.data, bits, parity)
        if pbit is not None:
            signal.value = pbit ^ int(op.invert_parity)
            await Timer(bit_ns, "ns")
        signal.value = op.stop_level
        await Timer(stop_ns, "ns")
        end_ns = _now_ns()
        if op.stop_level == 0:
            signal.value = 1
            await Timer(bit_ns, "ns")

        self._stats["bytes_driven"] += 1
        self._stats["framing_faults"] += int(op.stop_level == 0)
        self._stats["parity_faults"] += int(op.invert_parity)
        self._record(
            OcahUartFrame(
                data=op.data,
                bits=bits,
                parity=parity,
                stop_bits=stop_bits,
                framing_error=op.stop_level == 0,
                parity_error=op.invert_parity,
                start_ns=start_ns,
                end_ns=end_ns,
                line=self.name,
            )
        )

    async def _drive_break(self, op: _TxOp, bit_ns: int) -> None:
        start_ns = _now_ns()
        self.log.debug("%s: BREAK %.1f periods", self.name, op.periods)
        self._signal.value = 0
        await Timer(max(1, round(bit_ns * op.periods)), "ns")
        self._signal.value = 1
        end_ns = _now_ns()
        await Timer(bit_ns, "ns")
        self._stats["breaks"] += 1
        self._record(
            OcahUartFrame(
                data=0,
                bits=self._bits,
                parity=self._parity,
                stop_bits=self._stop_bits,
                framing_error=True,
                is_break=True,
                start_ns=start_ns,
                end_ns=end_ns,
                line=self.name,
            )
        )

    async def _drive_glitch(self, op: _TxOp, bit_ns: int) -> None:
        self.log.debug("%s: GLITCH %d ns", self.name, op.width_ns)
        self._signal.value = 0
        await Timer(op.width_ns, "ns")
        self._signal.value = 1
        await Timer(bit_ns, "ns")
        self._stats["glitches"] += 1


def _now_ns() -> int:
    return round(float(get_sim_time("ns")))
