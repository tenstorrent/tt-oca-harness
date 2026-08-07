# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
OcahUartMonitor — passive UART RX/TX byte monitor with callbacks.

Attaches non-intrusively to both the TX and RX UART lines.  Each received
byte is dispatched to registered callbacks.  No byte is consumed from the
line; a passive ``cocotbext-uart`` ``UartSink`` operates in tap mode.

When ``cocotbext-uart`` is not installed the class raises
``OcahUartImportError`` at construction time (same pattern as
``OcahUartConsole``).

Public API
----------
OcahUartMonitor(txd, rxd, clock, *, name, baud)
    .add_tx_callback(fn)   — fn(byte: int) -> None
    .add_rx_callback(fn)   — fn(byte: int) -> None
    await .start()
    await .stop()
    .get_tx_bytes() -> list[int]
    .get_rx_bytes() -> list[int]
    .clear_history()
    .get_statistics() -> dict

Callback signatures
-------------------
TX callback: ``fn(byte: int) -> None``
RX callback: ``fn(byte: int) -> None``

Callbacks are fired inside a ``cocotb`` coroutine task.  Exceptions inside
callbacks are caught and logged so they do not abort the monitor task.

All values exposed by the API are plain Python ``int``.
"""

import logging
from typing import Callable, Dict, List, Any, Optional

import cocotb
from cocotb.triggers import Timer

from .ocah_uart_console import (
    _COCOTBEXT_UART_AVAILABLE,
    _UartSink,
    OcahUartImportError,
)

__all__ = ["OcahUartMonitor"]

_HISTORY_MAX = 4096


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
        Baud rate to configure the passive sinks.  Must match DUT baud.
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
        baud: int = 115200,
        max_history: int = _HISTORY_MAX,
    ):
        if not _COCOTBEXT_UART_AVAILABLE:
            raise OcahUartImportError()

        self.name   = name
        self._clock = clock
        self._baud  = baud
        self._max_history = max_history
        self.log    = logging.getLogger(name)

        # Separate passive sinks for TX and RX.
        self._tx_sink = _UartSink(txd, baud=baud)
        self._rx_sink = _UartSink(rxd, baud=baud)

        self._tx_callbacks: List[Callable] = []
        self._rx_callbacks: List[Callable] = []

        self._tx_history: List[int] = []
        self._rx_history: List[int] = []

        self._running  = False
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
        self._tx_task = cocotb.start_soon(self._drain_loop(
            self._tx_sink, self._tx_history, self._tx_callbacks, "TX",
            "tx_bytes_observed",
        ))
        self._rx_task = cocotb.start_soon(self._drain_loop(
            self._rx_sink, self._rx_history, self._rx_callbacks, "RX",
            "rx_bytes_observed",
        ))
        self.log.info("%s: passive monitoring started (baud=%d)", self.name, self._baud)

    async def stop(self) -> None:
        """Stop monitoring.  In-flight bytes already buffered are retained."""
        if not self._running:
            return
        self._running = False
        for task in (self._tx_task, self._rx_task):
            if task is not None:
                task.kill()
        self._tx_task = None
        self._rx_task = None
        self.log.info("%s: passive monitoring stopped", self.name)

    # ------------------------------------------------------------------
    # Internal drain loop
    # ------------------------------------------------------------------

    async def _drain_loop(
        self,
        sink,
        history: List[int],
        callbacks: List[Callable],
        direction: str,
        stat_key: str,
    ) -> None:
        """Continuously read from ``sink`` and dispatch callbacks."""
        while self._running:
            # cocotbext-uart UartSink.read() awaits until data is ready.
            try:
                data = await sink.read(1)
            except Exception as exc:  # noqa: BLE001
                self.log.error(
                    "%s: %s sink read error: %s", self.name, direction, exc
                )
                await Timer(1, units="us")
                continue

            for b in data:
                byte_val = int(b)
                history.append(byte_val)
                if len(history) > self._max_history:
                    history.pop(0)
                self._stats[stat_key] += 1
                self.log.debug(
                    "%s: [%s] byte 0x%02X", self.name, direction, byte_val
                )
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
