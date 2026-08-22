# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
OcahEntropyMonitor — passive AXI-Stream entropy monitor for SEP TRNG DV.

This module passively observes the AXI-Stream entropy path
(``ext_trng_axis_req_i`` / ``ext_trng_axis_rsp_o``) and the sideband IRQ and
alarm signals.  It counts handshakes, records transferred words, and tracks
IRQ / alarm assertion events without driving any signals.

Signal mapping
--------------
The monitor accepts either:
  a) A ``dut`` handle with the standard naming convention (same as
     ``OcahEntropySource``).
  b) A ``signals`` dict with keys ``tvalid``, ``tdata``, ``tstrb``,
     ``tready``, ``irq``, ``alarm`` mapping to cocotb signal handles.

Callback interface
------------------
Register Python callables to be notified of events:

  ``add_data_callback(fn)``   — fn(word: int) called on each accepted word.
  ``add_irq_callback(fn)``    — fn(level: int) called on every IRQ edge.
  ``add_alarm_callback(fn)``  — fn(level: int) called on every alarm edge.

Callbacks are called synchronously from the monitor loop; exceptions are
caught and logged so one failing callback does not break the monitor.

History
-------
``get_words()`` returns every accepted 32-bit word in transfer order.
``get_irq_events()`` / ``get_alarm_events()`` return a list of dicts::

    {"sim_time": <float ns>, "level": <0 or 1>}

for every edge observed on the respective sideband signal.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

import cocotb
from cocotb.triggers import RisingEdge

__all__ = ["OcahEntropyMonitor"]

_HISTORY_MAX: int = 4096  # maximum number of retained records per category


class OcahEntropyMonitor:
    """
    Passive observer for the SEP AXI-Stream entropy path and sideband signals.

    Parameters
    ----------
    clock:
        Cocotb handle for the reference clock.
    signals:
        Dict with keys ``tvalid``, ``tdata``, ``tstrb``, ``tready``,
        ``irq``, ``alarm`` mapping to cocotb signal handles.
    dut:
        Cocotb DUT handle for standard-name signal resolution.
        One of ``signals`` or ``dut`` must be provided.
    stream_idx:
        Stream lane index when using ``dut``-based resolution.  Default 0.
    name:
        Instance label used in log messages.
    max_history:
        Maximum number of entries to retain in each history list.
    """

    def __init__(
        self,
        clock,
        *,
        signals: Optional[Dict[str, Any]] = None,
        dut=None,
        stream_idx: int = 0,
        name: str = "OcahEntropyMonitor",
        max_history: int = _HISTORY_MAX,
    ):
        self.name = name
        self.log = logging.getLogger(name)
        self._clock = clock
        self._max_history = max_history

        # ---- Resolve signal handles ----------------------------------------
        if signals is not None:
            required = {"tvalid", "tdata", "tstrb", "tready", "irq", "alarm"}
            missing = required - signals.keys()
            if missing:
                raise ValueError(
                    f"{name}: 'signals' dict is missing keys: {missing}"
                )
            self._sig_tvalid = signals["tvalid"]
            self._sig_tdata  = signals["tdata"]
            self._sig_tstrb  = signals["tstrb"]  # observed but not checked here
            self._sig_tready = signals["tready"]
            self._sig_irq    = signals["irq"]
            self._sig_alarm  = signals["alarm"]
        elif dut is not None:
            self._sig_tvalid = dut.ext_trng_axis_req_i_tvalid[stream_idx]
            self._sig_tdata  = dut.ext_trng_axis_req_i_tdata[stream_idx]
            self._sig_tstrb  = dut.ext_trng_axis_req_i_tstrb[stream_idx]
            self._sig_tready = dut.ext_trng_axis_rsp_o_tready[stream_idx]
            self._sig_irq    = dut.ext_trng_irq_i
            self._sig_alarm  = dut.ext_trng_alarm_i
        else:
            raise ValueError(f"{name}: supply either 'signals' or 'dut'.")

        # ---- History lists --------------------------------------------------
        self._words: List[int] = []
        self._irq_events: List[Dict[str, Any]] = []
        self._alarm_events: List[Dict[str, Any]] = []

        # ---- Callbacks ------------------------------------------------------
        self._data_callbacks: List[Callable] = []
        self._irq_callbacks:  List[Callable] = []
        self._alarm_callbacks: List[Callable] = []

        # ---- Internal state -------------------------------------------------
        self._running = False
        self._stream_task: Optional[Any] = None
        self._sideband_task: Optional[Any] = None

        # Shadow previous sideband levels to detect edges
        self._prev_irq: Optional[int] = None
        self._prev_alarm: Optional[int] = None

        # Cumulative counters
        self._handshake_count: int = 0
        self._irq_assert_count: int = 0
        self._alarm_assert_count: int = 0

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def add_data_callback(self, fn: Callable) -> None:
        """Register a callback: fn(word: int) called on each accepted entropy word."""
        self._data_callbacks.append(fn)

    def add_irq_callback(self, fn: Callable) -> None:
        """Register a callback: fn(level: int) called on IRQ signal edges."""
        self._irq_callbacks.append(fn)

    def add_alarm_callback(self, fn: Callable) -> None:
        """Register a callback: fn(level: int) called on alarm signal edges."""
        self._alarm_callbacks.append(fn)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start passive monitoring.  Safe to call multiple times."""
        if self._running:
            return
        self._running = True
        self._stream_task   = cocotb.start_soon(self._stream_loop())
        self._sideband_task = cocotb.start_soon(self._sideband_loop())
        self.log.info("%s: monitoring started", self.name)

    async def stop(self) -> None:
        """Stop monitoring."""
        if not self._running:
            return
        self._running = False
        if self._stream_task is not None:
            self._stream_task.kill()
            self._stream_task = None
        if self._sideband_task is not None:
            self._sideband_task.kill()
            self._sideband_task = None
        self.log.info(
            "%s: monitoring stopped — %d handshakes, %d IRQs, %d alarms",
            self.name,
            self._handshake_count,
            self._irq_assert_count,
            self._alarm_assert_count,
        )

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_words(self) -> List[int]:
        """Return a copy of every entropy word accepted by the DUT, in order."""
        return list(self._words)

    def get_irq_events(self) -> List[Dict[str, Any]]:
        """Return a copy of every IRQ edge event.

        Each entry: ``{"sim_time": float (ns), "level": 0 or 1}``.
        """
        return list(self._irq_events)

    def get_alarm_events(self) -> List[Dict[str, Any]]:
        """Return a copy of every alarm edge event.

        Each entry: ``{"sim_time": float (ns), "level": 0 or 1}``.
        """
        return list(self._alarm_events)

    def get_statistics(self) -> Dict[str, int]:
        """Return a snapshot of monitor counters.

        Returns
        -------
        dict
            ``handshakes``         — completed AXI-Stream transfers.
            ``irq_assertions``     — number of rising IRQ edges seen.
            ``alarm_assertions``   — number of rising alarm edges seen.
            ``words_recorded``     — entries in the word history list.
            ``irq_events_recorded``    — entries in the IRQ event list.
            ``alarm_events_recorded``  — entries in the alarm event list.
        """
        return {
            "handshakes":              self._handshake_count,
            "irq_assertions":          self._irq_assert_count,
            "alarm_assertions":        self._alarm_assert_count,
            "words_recorded":          len(self._words),
            "irq_events_recorded":     len(self._irq_events),
            "alarm_events_recorded":   len(self._alarm_events),
        }

    def clear_history(self) -> None:
        """Discard all retained records.  Counters are not reset."""
        self._words.clear()
        self._irq_events.clear()
        self._alarm_events.clear()

    def reset_statistics(self) -> None:
        """Zero all cumulative counters and clear history."""
        self._handshake_count = 0
        self._irq_assert_count = 0
        self._alarm_assert_count = 0
        self.clear_history()

    # ------------------------------------------------------------------
    # Internal monitoring loops
    # ------------------------------------------------------------------

    async def _stream_loop(self) -> None:
        """Sample the AXI-Stream signals on every rising clock edge."""
        while self._running:
            await RisingEdge(self._clock)
            try:
                tvalid = int(self._sig_tvalid.value)
                tready = int(self._sig_tready.value)
                if tvalid and tready:
                    word = int(self._sig_tdata.value) & 0xFFFF_FFFF
                    self._handshake_count += 1
                    self._append_limited(self._words, word)
                    self.log.debug(
                        "%s: handshake #%d — word=0x%08X",
                        self.name, self._handshake_count, word,
                    )
                    _fire_callbacks(self._data_callbacks, word)
            except Exception as exc:  # noqa: BLE001
                self.log.error(
                    "%s: exception in stream_loop: %s", self.name, exc
                )

    async def _sideband_loop(self) -> None:
        """Monitor IRQ and alarm on every rising clock edge."""
        while self._running:
            await RisingEdge(self._clock)
            try:
                sim_ns = float(cocotb.utils.get_sim_time(units="ns"))
                irq   = int(self._sig_irq.value)
                alarm = int(self._sig_alarm.value)

                if irq != self._prev_irq:
                    event = {"sim_time": sim_ns, "level": irq}
                    self._append_limited(self._irq_events, event)
                    if irq == 1:
                        self._irq_assert_count += 1
                        self.log.info("%s: IRQ asserted at %.1f ns", self.name, sim_ns)
                    else:
                        self.log.debug("%s: IRQ deasserted at %.1f ns", self.name, sim_ns)
                    _fire_callbacks(self._irq_callbacks, irq)
                    self._prev_irq = irq

                if alarm != self._prev_alarm:
                    event = {"sim_time": sim_ns, "level": alarm}
                    self._append_limited(self._alarm_events, event)
                    if alarm == 1:
                        self._alarm_assert_count += 1
                        self.log.warning(
                            "%s: ALARM asserted at %.1f ns", self.name, sim_ns
                        )
                    else:
                        self.log.debug(
                            "%s: alarm deasserted at %.1f ns", self.name, sim_ns
                        )
                    _fire_callbacks(self._alarm_callbacks, alarm)
                    self._prev_alarm = alarm

            except Exception as exc:  # noqa: BLE001
                self.log.error(
                    "%s: exception in sideband_loop: %s", self.name, exc
                )

    def _append_limited(self, lst: list, item: Any) -> None:
        """Append ``item`` to ``lst``, evicting the oldest entry at capacity."""
        lst.append(item)
        if len(lst) > self._max_history:
            lst.pop(0)


# ---------------------------------------------------------------------------
# Internal callback helper
# ---------------------------------------------------------------------------

def _fire_callbacks(callbacks: list, *args) -> None:
    """Call each registered callback; log but do not re-raise exceptions."""
    for fn in callbacks:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).error(
                "Exception in entropy monitor callback %s: %s", fn, exc
            )
