# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
OcahUartMasterDriver — active host-side UART line driver (native backend).

Drives 8-N-1 serial frames (configurable bits/stop bits, LSB first,
idle-high) onto a single cocotb signal handle at a configurable baud rate.
This is the master side of the console link: the VIP host initiates traffic
into the DUT's RX pad.  ``OcahUartConsole`` builds on this class; tests
normally use the console API rather than this driver directly.

Transmission is queue-based: ``write()`` / ``write_nowait()`` enqueue bytes
and a background pump task drives them frame by frame, so callers may
overlap stimulus with DUT-side polling.  ``await wait()`` blocks until the
queue is drained and the line has returned to idle.

Timing is derived from the baud rate (``round(1e9 / baud)`` ns per bit) and
re-read at every frame boundary, so ``baud``/``bits``/``stop_bits`` may be
reassigned between frames without a restart.

Public API
----------
OcahUartMasterDriver(signal, *, name, baud, bits, stop_bits)
    await .write(data: bytes)      — enqueue bytes for transmission
    .write_nowait(data: bytes)
    await .wait()                  — until queue empty and line idle
    .count() / .empty() / .idle() / .clear()
    .baud / .bits / .stop_bits     — properties, reassignable between frames
    .get_statistics() -> dict
    .reset_statistics()
"""

import logging
from typing import Any, Dict

import cocotb
from cocotb.handle import Immediate
from cocotb.queue import Queue
from cocotb.triggers import Event, Timer

__all__ = ["OcahUartMasterDriver"]

_DEFAULT_BAUD = 115200


class OcahUartMasterDriver:
    """Active 8-N-1 UART line driver over one cocotb signal handle.

    Parameters
    ----------
    signal :
        Cocotb signal handle the driver transmits on.  Driven to idle
        (logic-1) immediately at construction.
    name :
        Instance label used in log messages.
    baud :
        Baud rate (bit period is ``round(1e9 / baud)`` ns).
    bits :
        Data bits per frame (LSB first).
    stop_bits :
        Stop-bit length in bit periods (1, 1.5, or 2).
    """

    def __init__(
        self,
        signal,
        *,
        name: str = "OcahUartMasterDriver",
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
        self._idle_evt = Event()
        self._idle_evt.set()
        self._active = False

        self._stats: Dict[str, int] = {"bytes_driven": 0}

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
    # Transmit queue
    # ------------------------------------------------------------------

    async def write(self, data) -> None:
        """Enqueue ``data`` (any iterable of byte values) for transmission."""
        for b in data:
            await self._queue.put(int(b))
            self._idle_evt.clear()

    def write_nowait(self, data) -> None:
        """Non-async variant of :meth:`write`."""
        for b in data:
            self._queue.put_nowait(int(b))
        self._idle_evt.clear()

    def count(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def idle(self) -> bool:
        return self.empty() and not self._active

    def clear(self) -> None:
        """Drop queued bytes.  A frame already on the wire completes."""
        while not self._queue.empty():
            self._queue.get_nowait()

    async def wait(self) -> None:
        """Wait until every queued byte has been driven and the line is idle."""
        await self._idle_evt.wait()

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        return dict(self._stats)

    def reset_statistics(self) -> None:
        for key in self._stats:
            self._stats[key] = 0

    # ------------------------------------------------------------------
    # Frame pump
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        signal = self._signal
        while True:
            if self._queue.empty():
                self._active = False
                self._idle_evt.set()
            b = await self._queue.get()
            self._active = True

            # Snapshot timing per frame so reconfiguration lands cleanly
            # on the next frame boundary.
            bits = self._bits
            bit_ns = max(1, round(1e9 / self._baud))
            stop_ns = max(1, round(bit_ns * self._stop_bits))

            self.log.debug("%s: TX byte 0x%02X", self.name, b)

            signal.value = 0  # start bit
            await Timer(bit_ns, "ns")
            for k in range(bits):  # data bits, LSB first
                signal.value = (b >> k) & 1
                await Timer(bit_ns, "ns")
            signal.value = 1  # stop bit(s)
            await Timer(stop_ns, "ns")

            self._stats["bytes_driven"] += 1
