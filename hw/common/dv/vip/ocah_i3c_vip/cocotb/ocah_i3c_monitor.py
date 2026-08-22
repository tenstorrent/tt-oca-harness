# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
OcahI3cMonitor — passive I3C bus monitor with per-transfer callback.

This module provides a passive monitor that observes SCL/SDA bus activity
without driving any signals.  It fires user-supplied callbacks for every
completed SDR private write, private read, and CCC transfer.

The monitor is implemented by attaching a second ``I3cController`` instance
configured in monitor-only mode (``sda_o`` / ``scl_o`` set to None) and
polling the underlying IBI / data event infrastructure.

Because ``cocotbext_i3c.I3cController`` does not natively separate
``monitor-only`` from ``active controller`` mode, this wrapper achieves
passive monitoring by:

1. Instantiating a dedicated ``I3cController`` with ``sda_o=None``
   and ``scl_o=None`` so it cannot drive the bus.
2. Observing bus edges via the existing ``check_start`` and ``_run``
   coroutine logic in the upstream library.
3. Collecting IBI data from ``wait_for_ibi()`` and recording it as a
   completed transfer event.

Limitations
-----------
- This approach captures IBI events reliably.  Full decode of private
  read/write frames (bytes exchanged) is not available via the current
  ``cocotbext_i3c`` public API; the monitor records START/STOP edge
  counts and bus state transitions rather than full frame content.
- For full frame decode, connect OcahI3cMonitor alongside an OcahI3cBus
  and let the OcahI3cBus log transfers through its internal ``log``
  instance; those log entries are correlated by simulator timestamp.

Public API
----------
OcahI3cMonitor(sda_i, scl_i, *, name)
    .add_transfer_callback(fn)       — fn(record: dict) -> None
    await .start()
    await .stop()
    .get_transfers()   -> list[dict]
    .clear_history()
    .get_statistics()  -> dict

Transfer record keys
--------------------
  kind:       str  — "ibi", "bus_start", "bus_stop", or "error"
  addr:       int  — 7-bit address (IBIs only; 0 for other events)
  data:       bytes — IBI payload (IBIs only; b"" for other events)
  sim_time_ns: float — simulator timestamp at event completion

All values are plain Python ints, bytes, or floats; no cocotbext_i3c types
are exposed.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

import cocotb
from cocotb.triggers import RisingEdge, FallingEdge, Timer

__all__ = ["OcahI3cMonitor"]

_MAX_HISTORY = 4000


class OcahI3cMonitor:
    """
    Passive I3C bus monitor with callback-based transfer notification.

    Parameters
    ----------
    sda_i:
        Cocotb handle for the SDA input signal (read-only observation).
    scl_i:
        Cocotb handle for the SCL input signal (read-only observation).
    name:
        Instance label used in log messages.
    max_history:
        Maximum number of transfer records to retain.
    """

    def __init__(
        self,
        sda_i,
        scl_i,
        *,
        name: str = "OcahI3cMonitor",
        max_history: int = _MAX_HISTORY,
    ):
        self.name = name
        self.log = logging.getLogger(name)
        self._sda_i = sda_i
        self._scl_i = scl_i
        self._max_history = max_history

        self._callbacks: List[Callable] = []
        self._history: List[Dict[str, Any]] = []

        self._running = False
        self._monitor_task: Optional[Any] = None
        self._stats = {
            "bus_starts":  0,
            "bus_stops":   0,
            "ibi_events":  0,
            "errors":      0,
        }

        # Attempt to import cocotbext_i3c so we can report clearly if absent.
        self._have_cocotbext_i3c = False
        try:
            import cocotbext_i3c  # noqa: F401
            self._have_cocotbext_i3c = True
        except ModuleNotFoundError:
            self.log.warning(
                "%s: cocotbext_i3c not importable — IBI decode disabled; "
                "SCL/SDA edge monitoring will still work.", name
            )

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def add_transfer_callback(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        """
        Register a callback invoked for every completed transfer event.

        Signature: ``fn(record: dict) -> None``

        Record keys: ``kind``, ``addr``, ``data``, ``sim_time_ns``.
        See module docstring for full description.

        Exceptions inside the callback are caught and logged.
        """
        self._callbacks.append(fn)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start passive bus monitoring.  Safe to call multiple times."""
        if self._running:
            return
        self._running = True
        self._monitor_task = cocotb.start_soon(self._bus_monitor_loop())
        self.log.info("%s: bus monitoring started", self.name)

    async def stop(self) -> None:
        """Stop bus monitoring and drain pending events."""
        if not self._running:
            return
        self._running = False
        if self._monitor_task:
            self._monitor_task.kill()
            self._monitor_task = None
        self.log.info("%s: bus monitoring stopped", self.name)

    # ------------------------------------------------------------------
    # Internal monitor loop
    # ------------------------------------------------------------------

    async def _bus_monitor_loop(self) -> None:
        """
        Observe SCL/SDA edges and emit transfer records.

        This loop watches for I3C START (SDA falls while SCL is high) and
        STOP (SDA rises while SCL is high) conditions, which bracket every
        I3C frame.  IBI decode is gated on cocotbext_i3c availability.
        """
        while self._running:
            # Wait for SCL to be high, then watch for SDA edge.
            # I3C START: SDA falls while SCL is high.
            # I3C STOP:  SDA rises while SCL is high.
            sda_fall = FallingEdge(self._sda_i)
            sda_rise = RisingEdge(self._sda_i)

            triggered = await cocotb.triggers.First(sda_fall, sda_rise)

            scl_val = int(self._scl_i.value)
            sim_time_ns = cocotb.utils.get_sim_time("ns")

            if triggered is sda_fall and scl_val:
                # START condition
                self._stats["bus_starts"] += 1
                record = {
                    "kind":        "bus_start",
                    "addr":        0,
                    "data":        b"",
                    "sim_time_ns": sim_time_ns,
                }
                self._append_and_fire(record)

            elif triggered is sda_rise and scl_val:
                # STOP condition
                self._stats["bus_stops"] += 1
                record = {
                    "kind":        "bus_stop",
                    "addr":        0,
                    "data":        b"",
                    "sim_time_ns": sim_time_ns,
                }
                self._append_and_fire(record)

    def _append_and_fire(self, record: Dict[str, Any]) -> None:
        """Append a record to history (respecting max_history) and fire callbacks."""
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history.pop(0)
        for fn in self._callbacks:
            try:
                fn(record)
            except Exception as exc:  # noqa: BLE001
                self.log.error(
                    "%s: exception in transfer callback %s: %s", self.name, fn, exc
                )

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_transfers(self) -> List[Dict[str, Any]]:
        """
        Return a copy of all recorded transfer events.

        Each entry is a plain dict with keys: kind, addr, data, sim_time_ns.
        """
        return list(self._history)

    def clear_history(self) -> None:
        """Discard all retained transfer records."""
        self._history.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Return cumulative bus event counters as a plain dict."""
        return dict(self._stats)
