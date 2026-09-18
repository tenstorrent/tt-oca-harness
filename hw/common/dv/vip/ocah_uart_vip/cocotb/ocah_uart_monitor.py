# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART passive sampling (native backend).

``OcahUartLineMonitor``
    Wire-level frame reassembler over ONE serial line. It resynchronizes on
    every start edge, samples the start, data, parity, and stop bits at bit
    centres, and never drives the signal. Side-neutral (bare name): a UART
    line is a symmetric point-to-point wire, and the sampler reconstructs
    whatever traffic appears on it, VIP-driven or DUT-driven.
    ``OcahUartConsole`` uses one instance as its receive path.

    Every frame becomes an ``OcahUartFrame`` with its classification: a low
    stop bit is a framing error; a framing error whose data and parity bits
    are all low is a break, after which the sampler waits for the line to
    return high; a parity bit that disagrees with the data is a parity error;
    an unresolvable (X or Z) data bit is a framing error. A low pulse that
    has ended by the centre of the start bit is a glitch and yields no frame.
    The frame carries the time of its start edge and of the first rising edge
    after it, so a checker can measure the wire's bit period.

``OcahUartMonitor``
    Passive TX+RX tap with callbacks, built from two line monitors. Each
    observed frame goes into a bounded history and to the registered byte and
    frame callbacks.

Callbacks run inside a cocotb task; an exception inside a callback is logged
and counted (``callback_errors``) and never aborts sampling. All values
exposed by the API are plain Python ``int``, ``bytes``, or ``OcahUartFrame``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal

import cocotb
from cocotb.queue import Queue
from cocotb.triggers import Event, FallingEdge, First, RisingEdge, Timer
from cocotb.utils import get_sim_time

from .ocah_uart_types import (
    DEFAULT_BAUD,
    OcahUartFrame,
    OcahUartParity,
    bit_period_ns,
    check_format,
    parity_bit,
)

__all__ = ["OcahUartLineMonitor", "OcahUartMonitor"]

_HISTORY_MAX = 4096
TimeUnit = Literal["step", "fs", "ps", "ns", "us", "ms", "sec"]
FrameCallback = Callable[[OcahUartFrame], None]
ByteCallback = Callable[[int], None]


class OcahUartLineMonitor:
    """Passive frame reassembler over one serial line (never drives).

    Parameters
    ----------
    signal :
        Cocotb signal handle to sample.
    name :
        Instance label used in log messages and frame records.
    baud :
        Baud rate; the bit period is ``round(1e9 / baud)`` ns.
    bits :
        Data bits per frame (5..9), LSB first.
    parity :
        ``OcahUartParity`` member or its name.
    stop_bits :
        Stop length in bit periods; the stop level is judged at the centre of
        the first stop bit.
    max_history :
        Frames ``get_frames()`` holds; the oldest are dropped first.
    autostart :
        Sample from construction. With ``False`` the caller starts sampling
        with ``start()``.
    """

    def __init__(
        self,
        signal: Any,
        *,
        name: str = "OcahUartLineMonitor",
        baud: int = DEFAULT_BAUD,
        bits: int = 8,
        parity: OcahUartParity | str = OcahUartParity.NONE,
        stop_bits: float = 1,
        max_history: int = _HISTORY_MAX,
        autostart: bool = True,
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

        self._queue: Queue[OcahUartFrame] = Queue()
        self._sync = Event()
        self._frames: list[OcahUartFrame] = []
        self._callbacks: list[FrameCallback] = []
        self.initial_level: int | None = None
        self._frame_open = False
        self._first_rise_ns: int | None = None
        self._run_task: Any = None
        self._rise_task: Any = None

        self._stats: dict[str, int] = {
            "bytes_sampled": 0,
            "framing_errors": 0,
            "parity_errors": 0,
            "breaks": 0,
            "glitches": 0,
            "callback_errors": 0,
        }
        if autostart:
            self.start()

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
        """Reassign any of the frame parameters; each lands on the next start edge."""
        if baud is not None:
            self.baud = baud
        if parity is not None:
            self.parity = parity
        if bits is not None:
            self.bits = bits
        if stop_bits is not None:
            self.stop_bits = stop_bits

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._run_task is not None

    def start(self) -> None:
        """Start sampling; a running sampler is left alone."""
        if self._run_task is not None:
            return
        self._run_task = cocotb.start_soon(self._run())
        self._rise_task = cocotb.start_soon(self._watch_rise())

    def stop(self) -> None:
        """Stop sampling. Buffered frames and the history survive; a frame in flight is dropped."""
        for task in (self._run_task, self._rise_task):
            if task is not None:
                task.cancel()
        self._run_task = None
        self._rise_task = None
        self._frame_open = False

    # ------------------------------------------------------------------
    # Receive queue
    # ------------------------------------------------------------------

    async def read_frame(self) -> OcahUartFrame:
        """The next reconstructed frame, awaiting until one arrives."""
        return await self._queue.get()

    async def read_frames(self, count: int) -> list[OcahUartFrame]:
        """Exactly ``count`` frames, awaiting until they arrive."""
        return [await self._queue.get() for _ in range(count)]

    def read_frames_nowait(self, count: int = -1) -> list[OcahUartFrame]:
        """Up to ``count`` buffered frames (all buffered if -1)."""
        if count < 0:
            count = self._queue.qsize()
        count = min(count, self._queue.qsize())
        return [self._queue.get_nowait() for _ in range(count)]

    async def read(self, count: int = -1) -> bytes:
        """``count`` received data values as bytes, awaiting until they arrive.

        With ``count=-1``, await at least one frame and return everything
        buffered. A value above 255 (9-bit frames) is truncated to its low byte.
        """
        if count < 0:
            while self._queue.empty():
                self._sync.clear()
                await self._sync.wait()
            return self.read_nowait(-1)
        return bytes(frame.data & 0xFF for frame in await self.read_frames(count))

    def read_nowait(self, count: int = -1) -> bytes:
        """Up to ``count`` buffered data values as bytes (all buffered if -1)."""
        return bytes(frame.data & 0xFF for frame in self.read_frames_nowait(count))

    def count(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def clear(self) -> None:
        """Drop buffered frames; the history is kept."""
        while not self._queue.empty():
            self._queue.get_nowait()

    async def wait(self, timeout: int = 0, timeout_unit: TimeUnit = "ns") -> None:
        """Wait until at least one frame is buffered (or ``timeout`` elapses)."""
        if not self.empty():
            return
        self._sync.clear()
        if timeout:
            await First(self._sync.wait(), Timer(timeout, timeout_unit))
        else:
            await self._sync.wait()

    # ------------------------------------------------------------------
    # History, callbacks, statistics
    # ------------------------------------------------------------------

    def add_frame_callback(self, fn: FrameCallback) -> None:
        """Register ``fn(frame)`` for every reconstructed frame."""
        self._callbacks.append(fn)

    def get_frames(self) -> list[OcahUartFrame]:
        """Copy of the frame history, oldest first."""
        return list(self._frames)

    def clear_history(self) -> None:
        self._frames.clear()

    def get_statistics(self) -> dict[str, Any]:
        return dict(self._stats)

    def reset_statistics(self) -> None:
        for key in self._stats:
            self._stats[key] = 0

    # ------------------------------------------------------------------
    # Sampling loop
    # ------------------------------------------------------------------

    def _sample(self) -> int | None:
        """The line level as 0/1, or ``None`` when unresolvable (X/Z)."""
        try:
            return int(self._signal.value) & 1
        except ValueError:
            return None

    async def _watch_rise(self) -> None:
        signal = self._signal
        while True:
            await RisingEdge(signal)
            if self._frame_open and self._first_rise_ns is None:
                self._first_rise_ns = _now_ns()

    async def _run(self) -> None:
        signal = self._signal
        if self.initial_level is None:
            self.initial_level = self._sample()
        while True:
            await FallingEdge(signal)
            start_ns = _now_ns()
            self._frame_open = True
            self._first_rise_ns = None
            bits, parity, stop_bits = self._bits, self._parity, self._stop_bits
            bit_ns = self.bit_ns

            await Timer(max(1, bit_ns // 2), "ns")
            if self._sample() != 0:
                self._frame_open = False
                self._stats["glitches"] += 1
                self.log.debug("%s: glitch at %d ns", self.name, start_ns)
                continue

            unresolved = False
            data = 0
            for k in range(bits):
                await Timer(bit_ns, "ns")
                bit = self._sample()
                if bit is None:
                    unresolved = True
                    bit = 0
                data |= bit << k

            parity_error = False
            pbit: int | None = None
            if parity is not OcahUartParity.NONE:
                await Timer(bit_ns, "ns")
                pbit = self._sample()
                parity_error = pbit != parity_bit(data, bits, parity)

            await Timer(bit_ns, "ns")
            stop = self._sample()
            framing_error = stop != 1 or unresolved
            is_break = stop == 0 and data == 0 and not unresolved and (pbit in (None, 0))
            end_ns = _now_ns()
            if is_break:
                await RisingEdge(signal)
                end_ns = _now_ns()
            first_rise = self._first_rise_ns
            self._frame_open = False

            frame = OcahUartFrame(
                data=data,
                bits=bits,
                parity=parity,
                stop_bits=stop_bits,
                framing_error=framing_error,
                parity_error=parity_error,
                is_break=is_break,
                start_ns=start_ns,
                end_ns=end_ns,
                first_rise_ns=first_rise,
                line=self.name,
            )
            self._deliver(frame)

    def _deliver(self, frame: OcahUartFrame) -> None:
        self._stats["bytes_sampled"] += 1
        if frame.is_break:
            self._stats["breaks"] += 1
            self.log.warning(
                "%s: break from %d ns to %d ns", self.name, frame.start_ns, frame.end_ns
            )
        elif frame.framing_error:
            self._stats["framing_errors"] += 1
            self.log.warning("%s: framing error on 0x%02X", self.name, frame.data)
        if frame.parity_error:
            self._stats["parity_errors"] += 1
            self.log.warning("%s: parity error on 0x%02X", self.name, frame.data)
        self.log.debug("%s: RX 0x%02X", self.name, frame.data)
        self._frames.append(frame)
        if len(self._frames) > self._max_history:
            del self._frames[0]
        self._queue.put_nowait(frame)
        self._sync.set()
        self._stats["callback_errors"] += _fire_callbacks(self.log, self._callbacks, frame)


def _fire_callbacks(log: logging.Logger, callbacks: list[Any], *args: Any) -> int:
    """Invoke each callback; a checker verdict propagates, any other exception is logged and counted."""
    errors = 0
    for fn in callbacks:
        try:
            fn(*args)
        except AssertionError:
            raise
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log.error("exception in callback %s: %s", fn, exc)
    return errors


class OcahUartMonitor:
    """Passive UART tap over both lines of a link.

    Parameters
    ----------
    txd, rxd :
        Cocotb signal handles of the two lines; the names follow the console
        host: ``txd`` is the line the host drives, ``rxd`` the line it reads.
    clock :
        Accepted for call-site symmetry with ``OcahUartConsole``; the taps
        time frames from the baud rate.
    name :
        Instance label used in log messages.
    baud, bits, parity, stop_bits :
        Frame format of both lines; must match the DUT.
    max_history :
        Frames held per direction.
    """

    def __init__(
        self,
        txd: Any,
        rxd: Any,
        clock: Any = None,
        *,
        name: str = "OcahUartMonitor",
        baud: int = DEFAULT_BAUD,
        bits: int = 8,
        parity: OcahUartParity | str = OcahUartParity.NONE,
        stop_bits: float = 1,
        max_history: int = _HISTORY_MAX,
    ) -> None:
        self.name = name
        self._clock = clock
        self.log = logging.getLogger(name)
        fmt: dict[str, Any] = {
            "baud": baud,
            "bits": bits,
            "parity": parity,
            "stop_bits": stop_bits,
            "max_history": max_history,
            "autostart": False,
        }
        self._tx_tap = OcahUartLineMonitor(txd, name=f"{name}.tx", **fmt)
        self._rx_tap = OcahUartLineMonitor(rxd, name=f"{name}.rx", **fmt)

        self._tx_callbacks: list[ByteCallback] = []
        self._rx_callbacks: list[ByteCallback] = []
        self._tx_frame_callbacks: list[FrameCallback] = []
        self._rx_frame_callbacks: list[FrameCallback] = []
        self._tx_history: list[OcahUartFrame] = []
        self._rx_history: list[OcahUartFrame] = []
        self._max_history = int(max_history)

        self._running = False
        self._tx_task: Any = None
        self._rx_task: Any = None

        self._stats: dict[str, int] = {
            "tx_bytes_observed": 0,
            "rx_bytes_observed": 0,
            "tx_frame_errors": 0,
            "rx_frame_errors": 0,
            "callback_errors": 0,
        }

    @property
    def baud(self) -> int:
        return self._tx_tap.baud

    def configure(
        self,
        *,
        baud: int | None = None,
        bits: int | None = None,
        parity: OcahUartParity | str | None = None,
        stop_bits: float | None = None,
    ) -> None:
        """Reassign the frame format of both taps."""
        for tap in (self._tx_tap, self._rx_tap):
            tap.configure(baud=baud, bits=bits, parity=parity, stop_bits=stop_bits)

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def add_tx_callback(self, fn: ByteCallback) -> None:
        """Register ``fn(value: int)`` for every frame observed on TXD."""
        self._tx_callbacks.append(fn)

    def add_rx_callback(self, fn: ByteCallback) -> None:
        """Register ``fn(value: int)`` for every frame observed on RXD."""
        self._rx_callbacks.append(fn)

    def add_tx_frame_callback(self, fn: FrameCallback) -> None:
        """Register ``fn(frame)`` for every frame observed on TXD."""
        self._tx_frame_callbacks.append(fn)

    def add_rx_frame_callback(self, fn: FrameCallback) -> None:
        """Register ``fn(frame)`` for every frame observed on RXD."""
        self._rx_frame_callbacks.append(fn)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start passive monitoring. Safe to call more than once."""
        if self._running:
            return
        self._running = True
        self._tx_tap.start()
        self._rx_tap.start()
        self._tx_task = cocotb.start_soon(
            self._drain_loop(
                self._tx_tap,
                self._tx_history,
                self._tx_callbacks,
                self._tx_frame_callbacks,
                "tx",
            )
        )
        self._rx_task = cocotb.start_soon(
            self._drain_loop(
                self._rx_tap,
                self._rx_history,
                self._rx_callbacks,
                self._rx_frame_callbacks,
                "rx",
            )
        )
        self.log.info("%s: passive monitoring started (baud=%d)", self.name, self.baud)

    async def stop(self) -> None:
        """Stop monitoring. Frames already delivered stay in the history."""
        if not self._running:
            return
        self._running = False
        for task in (self._tx_task, self._rx_task):
            if task is not None:
                task.cancel()
        self._tx_task = None
        self._rx_task = None
        self._tx_tap.stop()
        self._rx_tap.stop()
        self.log.info("%s: passive monitoring stopped", self.name)

    async def _drain_loop(
        self,
        tap: OcahUartLineMonitor,
        history: list[OcahUartFrame],
        byte_callbacks: list[ByteCallback],
        frame_callbacks: list[FrameCallback],
        direction: str,
    ) -> None:
        while self._running:
            frame = await tap.read_frame()
            history.append(frame)
            if len(history) > self._max_history:
                del history[0]
            self._stats[f"{direction}_bytes_observed"] += 1
            self._stats[f"{direction}_frame_errors"] += int(not frame.clean)
            self.log.debug("%s: [%s] 0x%02X", self.name, direction.upper(), frame.data)
            self._stats["callback_errors"] += _fire_callbacks(self.log, byte_callbacks, frame.data)
            self._stats["callback_errors"] += _fire_callbacks(self.log, frame_callbacks, frame)

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_tx_bytes(self) -> list[int]:
        """Observed TXD data values, oldest first."""
        return [frame.data for frame in self._tx_history]

    def get_rx_bytes(self) -> list[int]:
        """Observed RXD data values, oldest first."""
        return [frame.data for frame in self._rx_history]

    def get_tx_frames(self) -> list[OcahUartFrame]:
        """Observed TXD frames, oldest first."""
        return list(self._tx_history)

    def get_rx_frames(self) -> list[OcahUartFrame]:
        """Observed RXD frames, oldest first."""
        return list(self._rx_history)

    def clear_history(self) -> None:
        """Discard every frame in both histories."""
        self._tx_history.clear()
        self._rx_history.clear()

    def get_statistics(self) -> dict[str, Any]:
        """Cumulative observation counters."""
        return dict(self._stats)


def _now_ns() -> int:
    return round(float(get_sim_time("ns")))
