# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
UART passive sampling (native backend).

Two components live here:

``OcahUartLineMonitor``
    Wire-level 8-N-1 byte reassembler over ONE serial line.  It samples
    start/data/stop bits at bit centres, resynchronising on every start-bit
    edge, and never drives the signal.  Side-neutral (bare name): a UART
    line is a symmetric point-to-point wire, and the sampler reconstructs
    whatever traffic appears on it — VIP-driven or DUT-driven — so a
    master/slave side token would be false labeling.  ``OcahUartConsole``
    uses one instance as its receive path.

``OcahUartMonitor``
    Passive TX+RX byte tap with callbacks, built from two line monitors.
    Each observed byte is retained in bounded history and dispatched to
    registered callbacks.

Public API
----------
OcahUartLineMonitor(signal, *, name, baud, bits, stop_bits)
    await .read(count=-1) -> bytes  — await ``count`` bytes (all buffered if -1)
    .read_nowait(count=-1) -> bytes
    await .wait(timeout=0, timeout_unit="ns")
    .count() / .empty() / .clear()
    .baud / .bits / .stop_bits      — properties, reassignable between frames
    .get_statistics() -> dict

OcahUartMonitor(txd, rxd, clock, *, name, baud, max_history)
    .add_tx_callback(fn)   — fn(byte: int) -> None
    .add_rx_callback(fn)   — fn(byte: int) -> None
    await .start()
    await .stop()
    .get_tx_bytes() -> list[int]
    .get_rx_bytes() -> list[int]
    .clear_history()
    .get_statistics() -> dict

Callbacks are fired inside a ``cocotb`` coroutine task.  Exceptions inside
callbacks are caught and logged so they do not abort the monitor task.
All values exposed by the API are plain Python ``int``.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

import cocotb
from cocotb.queue import Queue
from cocotb.triggers import Event, FallingEdge, First, Timer

__all__ = ["OcahUartLineMonitor", "OcahUartMonitor"]

_HISTORY_MAX = 4096
_DEFAULT_BAUD = 115200


class OcahUartLineMonitor:
    """Passive 8-N-1 byte reassembler over one serial line (never drives).

    Parameters
    ----------
    signal :
        Cocotb signal handle to sample.  Sampling starts at construction.
    name :
        Instance label used in log messages.
    baud :
        Baud rate (bit period is ``round(1e9 / baud)`` ns).  The sampler
        resynchronises on every start-bit edge, so the sub-nanosecond
        rounding error does not accumulate across frames.
    bits :
        Data bits per frame (LSB first).
    stop_bits :
        Stop-bit length in bit periods.  The stop level is checked at the
        centre of the first stop bit; a low stop bit counts as a framing
        error (logged, byte still delivered).
    """

    def __init__(
        self,
        signal,
        *,
        name: str = "OcahUartLineMonitor",
        baud: int = _DEFAULT_BAUD,
        bits: int = 8,
        stop_bits: float = 1,
    ):
        self.name = name
        self.log = logging.getLogger(name)
        self._signal = signal
        self._baud = int(baud)
        self._bits = int(bits)
        self._stop_bits = float(stop_bits)

        self._queue: Queue = Queue()
        self._sync = Event()

        self._stats: Dict[str, int] = {
            "bytes_sampled": 0,
            "framing_errors": 0,
            "glitches": 0,
        }

        self._run_task = cocotb.start_soon(self._run())

    # ------------------------------------------------------------------
    # Configuration properties
    # ------------------------------------------------------------------

    @property
    def baud(self) -> int:
        return self._baud

    @baud.setter
    def baud(self, value: int) -> None:
        if value <= 0:
            raise ValueError(f"{self.name}: baud must be positive, got {value}")
        self._baud = int(value)

    @property
    def bits(self) -> int:
        return self._bits

    @bits.setter
    def bits(self, value: int) -> None:
        self._bits = int(value)

    @property
    def stop_bits(self) -> float:
        return self._stop_bits

    @stop_bits.setter
    def stop_bits(self, value: float) -> None:
        self._stop_bits = float(value)

    # ------------------------------------------------------------------
    # Receive queue
    # ------------------------------------------------------------------

    async def read(self, count: int = -1) -> bytes:
        """Return ``count`` received bytes, awaiting until they arrive.

        With ``count=-1``, await at least one byte and return everything
        buffered.
        """
        if count < 0:
            while self._queue.empty():
                self._sync.clear()
                await self._sync.wait()
            return self.read_nowait(-1)
        data = bytearray()
        for _ in range(count):
            data.append(await self._queue.get())
        return bytes(data)

    def read_nowait(self, count: int = -1) -> bytes:
        """Return up to ``count`` buffered bytes (all buffered if -1)."""
        if count < 0:
            count = self._queue.qsize()
        count = min(count, self._queue.qsize())
        data = bytearray()
        for _ in range(count):
            data.append(self._queue.get_nowait())
        return bytes(data)

    def count(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def clear(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()

    async def wait(self, timeout: int = 0, timeout_unit: str = "ns") -> None:
        """Wait until at least one byte is buffered (or ``timeout`` elapses)."""
        if not self.empty():
            return
        self._sync.clear()
        if timeout:
            await First(self._sync.wait(), Timer(timeout, timeout_unit))
        else:
            await self._sync.wait()

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        return dict(self._stats)

    def reset_statistics(self) -> None:
        for key in self._stats:
            self._stats[key] = 0

    # ------------------------------------------------------------------
    # Sampling loop
    # ------------------------------------------------------------------

    def _sample(self) -> Optional[int]:
        """Return the line level as 0/1, or ``None`` when unresolvable (X/Z)."""
        try:
            return int(self._signal.value) & 1
        except ValueError:
            return None

    async def _run(self) -> None:
        signal = self._signal
        while True:
            await FallingEdge(signal)

            # Snapshot timing per frame; resync happens on the next edge.
            bits = self._bits
            bit_ns = max(1, round(1e9 / self._baud))

            await Timer(max(1, bit_ns // 2), "ns")  # centre of start bit
            if self._sample() != 0:
                self._stats["glitches"] += 1
                continue

            framing_error = False
            b = 0
            for k in range(bits):  # data-bit centres
                await Timer(bit_ns, "ns")
                bit = self._sample()
                if bit is None:
                    framing_error = True
                    bit = 0
                b |= bit << k

            await Timer(bit_ns, "ns")  # centre of stop bit
            if self._sample() != 1:
                framing_error = True

            if framing_error:
                self._stats["framing_errors"] += 1
                self.log.warning("%s: framing error around byte 0x%02X", self.name, b)

            self.log.debug("%s: RX byte 0x%02X", self.name, b)
            self._stats["bytes_sampled"] += 1
            self._queue.put_nowait(b)
            self._sync.set()


def _fire_callbacks(callbacks: list, *args) -> None:
    """Invoke each callback; log but do not re-raise exceptions."""
    for fn in callbacks:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).error(
                "Exception in OcahUartMonitor callback %s: %s", fn, exc
            )


class OcahUartMonitor:
    """
    Passive UART byte monitor.

    Taps both TXD and RXD lines simultaneously.  Each byte is added to the
    respective history list and all registered callbacks are fired.

    Parameters
    ----------
    txd :
        Cocotb signal handle for the UART TX line being monitored.
    rxd :
        Cocotb signal handle for the UART RX line being monitored.
    clock :
        Cocotb clock handle (informational; used for internal tick timing).
    name :
        Instance label used in log messages.
    baud :
        Baud rate to configure the passive line monitors.  Must match DUT
        baud.
    max_history :
        Maximum number of bytes to retain per direction.
    """

    def __init__(
        self,
        txd,
        rxd,
        clock,
        *,
        name: str = "OcahUartMonitor",
        baud: int = _DEFAULT_BAUD,
        max_history: int = _HISTORY_MAX,
    ):
        self.name = name
        self._clock = clock
        self._baud = baud
        self._max_history = max_history
        self.log = logging.getLogger(name)

        # Separate passive line monitors for TX and RX.
        self._tx_tap = OcahUartLineMonitor(txd, name=f"{name}.tx", baud=baud)
        self._rx_tap = OcahUartLineMonitor(rxd, name=f"{name}.rx", baud=baud)

        self._tx_callbacks: List[Callable] = []
        self._rx_callbacks: List[Callable] = []

        self._tx_history: List[int] = []
        self._rx_history: List[int] = []

        self._running = False
        self._tx_task: Optional[Any] = None
        self._rx_task: Optional[Any] = None

        self._stats: Dict[str, int] = {
            "tx_bytes_observed": 0,
            "rx_bytes_observed": 0,
        }

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def add_tx_callback(self, fn: Callable) -> None:
        """Register a callback for bytes observed on TXD.

        Signature: ``fn(byte: int) -> None``
        """
        self._tx_callbacks.append(fn)

    def add_rx_callback(self, fn: Callable) -> None:
        """Register a callback for bytes observed on RXD.

        Signature: ``fn(byte: int) -> None``
        """
        self._rx_callbacks.append(fn)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start passive monitoring.  Safe to call multiple times."""
        if self._running:
            return
        self._running = True
        self._tx_task = cocotb.start_soon(
            self._drain_loop(
                self._tx_tap,
                self._tx_history,
                self._tx_callbacks,
                "TX",
                "tx_bytes_observed",
            )
        )
        self._rx_task = cocotb.start_soon(
            self._drain_loop(
                self._rx_tap,
                self._rx_history,
                self._rx_callbacks,
                "RX",
                "rx_bytes_observed",
            )
        )
        self.log.info("%s: passive monitoring started (baud=%d)", self.name, self._baud)

    async def stop(self) -> None:
        """Stop monitoring.  In-flight bytes already buffered are retained."""
        if not self._running:
            return
        self._running = False
        for task in (self._tx_task, self._rx_task):
            if task is not None:
                task.cancel()
        self._tx_task = None
        self._rx_task = None
        self.log.info("%s: passive monitoring stopped", self.name)

    # ------------------------------------------------------------------
    # Internal drain loop
    # ------------------------------------------------------------------

    async def _drain_loop(
        self,
        tap: OcahUartLineMonitor,
        history: List[int],
        callbacks: List[Callable],
        direction: str,
        stat_key: str,
    ) -> None:
        """Continuously read from ``tap`` and dispatch callbacks."""
        while self._running:
            data = await tap.read(1)

            for b in data:
                byte_val = int(b)
                history.append(byte_val)
                if len(history) > self._max_history:
                    history.pop(0)
                self._stats[stat_key] += 1
                self.log.debug("%s: [%s] byte 0x%02X", self.name, direction, byte_val)
                _fire_callbacks(callbacks, byte_val)

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_tx_bytes(self) -> List[int]:
        """Return a copy of observed TX byte history (oldest first)."""
        return list(self._tx_history)

    def get_rx_bytes(self) -> List[int]:
        """Return a copy of observed RX byte history (oldest first)."""
        return list(self._rx_history)

    def clear_history(self) -> None:
        """Discard all retained byte records."""
        self._tx_history.clear()
        self._rx_history.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Return cumulative observation counters."""
        return dict(self._stats)
