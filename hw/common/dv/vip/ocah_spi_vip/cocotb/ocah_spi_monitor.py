# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
OcahSpiMonitor — passive SPI bus monitor and controller wire checker.

Observes SPI transactions without driving any signals.  Decodes the command
byte, address bytes, and data bytes from the MOSI/DQ line, grades the
controller's pins against the SPI mode, and fires callbacks when a complete
transaction (CS_N low → high) is observed.

Supported transaction fields
-----------------------------
Each completed transaction is reported as a plain dict::

    {
        "opcode":    int,          # 8-bit command byte
        "addr":      int,          # decoded address (0 if no address)
        "has_addr":  bool,         # True if command carries an address
        "data_mosi": bytes,        # complete payload bytes on MOSI/DQ0 after the address (PAGE PROGRAM)
        "data_miso": bytes,        # complete response bytes on MISO/DQ0 after the command, address, and dummy phases
        "data_miso_xz": tuple,     # indices of data_miso bytes with a bit sampled as X/Z
        "bit_count": int,          # total bits observed in this transaction
        "input_bits": int,         # command, address and dummy bits of a single-
                                   # lane command with a response phase;
                                   # bit_count otherwise
        "input_clocks": int,       # clocks of the command, address and dummy
                                   # phases of a command with a response
                                   # (any lane width); bit_count otherwise
        "opcode_complete": bool,   # True when at least 8 bits were observed
        "cpol":      int,          # SPI mode the frame was graded in
        "cpha":      int,
        "wire_errors": tuple,      # wire-check violations of this frame
        "beats":     tuple,        # with the four-lane taps: one
                                   # (lanes out, output enables, lanes in)
                                   # per sample edge, None for X/Z
        "miso_idle": int or None,  # response lane level when chip-select fell, None for X/Z
        "miso_raw":  tuple,        # response lane level at each sample edge, None for X/Z
        "start_ns":  float or None,
        "end_ns":    float or None,
    }

``data_miso`` is empty for a command that carries no response phase, and
``data_mosi`` is empty for a command that carries no payload phase, so a byte
the line held during the command phase is never reported as data.  Known
command codes are decoded to symbolic names for logging; unknown codes are
logged as ``UNKNOWN(0xNN)`` and carry neither data field.  A frame shorter
than 8 bits has ``opcode_complete`` False; its ``opcode`` holds the observed
bits left-aligned.

Wire checks
-----------
The monitor samples MOSI and MISO on the sample edge of the SPI mode the test
gives it (``cpol``/``cpha``, or ``set_mode`` before the frames it applies to):
the rising SCK edge when CPOL equals CPHA, the falling edge otherwise.  The
other SCK edge is the shift edge.  It grades the controller's pins:

====================  =====================================================
``idle_at_cs_fall``   SCK is at the CPOL level when chip-select falls
``idle_at_cs_rise``   SCK is at the CPOL level when chip-select rises
``mosi_edge``         while chip-select is low, MOSI does not change on a
                      sample edge, nor after a sample edge and before the
                      next shift edge of the running clock (one that comes
                      within 1.5 half periods of the sample edge); a change
                      from a shift edge up to the next sample edge, before
                      the first SCK edge, or after the last edge is legal
``sck_while_idle``    while chip-select is high, SCK moves only to the CPOL
                      level
``xz``                at every settled time step while chip-select is low,
                      chip-select, SCK and MOSI (with the four-lane taps,
                      every lane whose output enable is on, and the output
                      enables) resolve to 0 or 1; one X/Z episode is one
                      violation
``oe_idle``           with ``sd_oe``: no data lane output enable rises, or is
                      on at an SCK edge, while chip-select is high
``oe_lanes``          with ``sd_oe``: at each sample edge the data lane output
                      enables are none, lane 0, lanes 1:0 or lanes 3:0
``oe_data``           with ``sd_out`` and ``sd_oe``: at every sample edge of a
                      controller-output clock (command byte, address, the
                      payload of a command without a response, and any bit
                      after an exact command) the lanes that carry the data
                      have their output enables on; a bit sampled with its
                      output enable off did not reach the pad
``oe_ctrl``           with ``cs_oe``/``sck_oe``: both are on at each sample
                      edge (a sample edge needs a driven chip-select low and
                      a driven clock edge; an undriven pad does not carry
                      them)
====================  =====================================================

With the four-lane taps the MOSI checks apply to every lane whose output
enable is on before and after a change. ``beats`` keeps the raw lanes of each
sample edge; ``lanes_to_bytes`` (``ocah_spi_types``) decodes a dual or quad
phase from it.

The monitor grades a time step once all of its changes have settled, so the
order in which a simulator applies changes of one time step does not matter.
While chip-select is not low (reset included), an X/Z on chip-select, SCK or
an output enable is not graded.

Each violation is logged and kept in the frame's ``wire_errors`` and in
``get_wire_errors()``.  ``stop()`` raises ``OcahSpiMonitorError`` when a wire
check failed, a callback raised ``AssertionError``, or the monitor itself
raised; ``get_statistics()["callback_errors"]`` counts other callback
exceptions.

Usage
-----
::

    mon = OcahSpiMonitor(
        cs_n = dut.spi_cs_n,
        sclk = dut.spi_sclk,
        mosi = dut.spi_mosi,
        miso = dut.spi_miso,
        name = "spi_mon",
        addr_bytes = 3,
        cpol = 0,
        cpha = 0,
    )
    mon.add_transaction_callback(lambda txn: print(txn))
    await mon.start()
    # ... run traffic; mon.set_mode(cpol, cpha) before a mode change ...
    await mon.stop()          # raises on a wire-check violation
    txns = mon.get_transactions()
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import cocotb
from cocotb.triggers import Edge, First, ReadOnly, RisingEdge

from .ocah_spi_types import (
    LANE_OPCODES,
    OcahSpiOpcode,
    command_format,
    lanes_to_bytes,
    opcode_name,
)

__all__ = ["OcahSpiMonitor", "OcahSpiMonitorError"]


class OcahSpiMonitorError(AssertionError):
    """A wire check failed, a callback asserted, or the monitor raised while it ran."""


def _cancel_task(task: Any) -> None:
    """Stop a background task on cocotb 1.x (``kill``) and 2.x (``cancel``) alike."""
    cancel = getattr(task, "cancel", None)
    if cancel is not None:
        cancel()
    else:
        task.kill()


# Commands that carry an address phase
_ADDR_COMMANDS = frozenset(
    int(op)
    for op in (
        OcahSpiOpcode.READ,
        OcahSpiOpcode.FAST_READ,
        OcahSpiOpcode.PAGE_PROGRAM,
        OcahSpiOpcode.SECTOR_ERASE,
    )
)

# Commands that have a MISO data phase after the address/dummy
_MISO_COMMANDS = frozenset(
    int(op)
    for op in (
        OcahSpiOpcode.JEDEC_ID,
        OcahSpiOpcode.READ,
        OcahSpiOpcode.FAST_READ,
        OcahSpiOpcode.READ_SR1,
        OcahSpiOpcode.READ_SR2,
    )
)

# Commands that have a MOSI data phase after the address
_MOSI_COMMANDS = frozenset([int(OcahSpiOpcode.PAGE_PROGRAM)])


class OcahSpiMonitor:
    """
    Passive SPI bus monitor and controller wire checker.

    Observes CS_N, SCLK, and MOSI/MISO without driving anything.  Fires
    registered callbacks and maintains a transaction history.

    Parameters
    ----------
    cs_n : cocotb handle
        Active-low chip-select (DUT → flash direction).
    sclk : cocotb handle
        Serial clock (DUT → flash direction).
    mosi : cocotb handle, optional
        Master-out / slave-in data line (or DQ0 of the DQ bus).
    miso : cocotb handle, optional
        Master-in / slave-out data line (or DQ0 of the response bus).
    name : str
        Instance label for log messages.
    addr_bytes : int
        Number of address bytes expected after the command opcode.  Default 3.
    fast_read_dummies : int
        Number of dummy bytes consumed by FAST_READ (0x0B) before data phase.
        Default 1 (= 8 dummy bits).
    cpol, cpha : int
        SPI mode the controller is programmed to.  Default 0, 0 (Mode 0).
    sd_out, sd_oe, sd_in : cocotb handle, optional
        Four-lane taps: the controller's data lanes, their output enables
        (bit n enables lane n), and the lanes into the controller. With
        ``sd_out`` the frame record carries ``beats``, and ``mosi``/``miso``
        default to lane 0 out and lane 1 in. With ``sd_oe`` the output-enable
        checks run.
    cs_oe, sck_oe : cocotb handle, optional
        Output enables of chip select and clock; checked while chip select
        is low.
    max_history : int
        Maximum number of transactions retained in history.  Default 2000.
    verbose : bool
        Log individual bit transitions when True.  Default False.
    """

    def __init__(
        self,
        cs_n,
        sclk,
        *,
        mosi=None,
        miso=None,
        name: str = "OcahSpiMonitor",
        addr_bytes: int = 3,
        fast_read_dummies: int = 1,
        cpol: int = 0,
        cpha: int = 0,
        sd_out=None,
        sd_oe=None,
        sd_in=None,
        cs_oe=None,
        sck_oe=None,
        max_history: int = 2000,
        verbose: bool = False,
    ):
        self.name = name
        self.log = logging.getLogger(name)

        self._cs_n = cs_n
        self._sclk = sclk
        self._mosi = mosi
        self._miso = miso
        self._sd_out = sd_out
        self._sd_oe = sd_oe
        self._sd_in = sd_in
        self._cs_oe = cs_oe
        self._sck_oe = sck_oe

        self._addr_bytes = addr_bytes
        self._fast_read_dummies = fast_read_dummies
        self._cpol = cpol & 1
        self._cpha = cpha & 1
        self._max_history = max_history
        self._verbose = verbose

        self._sck_idle_seen: Optional[int] = None
        self._callbacks: List[Callable] = []
        self._history: List[Dict[str, Any]] = []
        self._wire_errors: List[str] = []
        self._error: Optional[BaseException] = None

        self._task: Optional[Any] = None
        self._running = False

        self._stats = {
            "transactions_seen": 0,
            "bytes_mosi": 0,
            "bytes_miso": 0,
            "callback_errors": 0,
        }

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def add_transaction_callback(self, fn: Callable) -> None:
        """Register a callback fired on each completed transaction.

        Signature: ``fn(txn: dict) -> None``

        The ``txn`` dict is a plain-int/bytes record; see module docstring
        for the field list.  An ``AssertionError`` from the callback makes
        ``stop()`` raise; any other exception is logged and counted.
        """
        self._callbacks.append(fn)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start passive monitoring.  Safe to call multiple times."""
        if self._running:
            return
        self._running = True
        self._task = cocotb.start_soon(self._monitor_loop())
        self.log.info("%s: started (mode=%d%d)", self.name, self._cpol, self._cpha)

    def set_mode(self, cpol: int, cpha: int) -> None:
        """SPI mode of the idle check and of every frame that starts after this call."""
        self._cpol = cpol & 1
        self._cpha = cpha & 1

    async def stop(self) -> None:
        """Stop monitoring; the history survives.

        Raises ``OcahSpiMonitorError`` when a wire check failed, a callback
        raised ``AssertionError``, or the monitor raised while it ran.
        """
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            _cancel_task(self._task)
            self._task = None
        self.log.info(
            "%s: stopped (transactions=%d wire_errors=%d)",
            self.name,
            self._stats["transactions_seen"],
            len(self._wire_errors),
        )
        error, self._error = self._error, None
        if error is not None:
            raise OcahSpiMonitorError(f"{self.name}: raised while running: {error!r}") from error
        if self._wire_errors:
            raise OcahSpiMonitorError(
                f"{self.name}: {len(self._wire_errors)} wire-check violation(s); "
                f"first: {self._wire_errors[0]}"
            )

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_transactions(self) -> List[Dict[str, Any]]:
        """Return a copy of the completed transaction history."""
        return list(self._history)

    def clear_history(self) -> None:
        """Discard all retained transaction records."""
        self._history.clear()

    def get_wire_errors(self) -> List[str]:
        """Every wire-check violation seen since ``start``, in order."""
        return list(self._wire_errors)

    def get_statistics(self) -> Dict[str, Any]:
        """Return cumulative monitor statistics."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Monitor loop
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Main async loop — grade the idle bus, then observe one transaction."""
        settled = False
        while self._running:
            try:
                await self._watch_idle(settled)
                if not self._running:
                    break
                await self._observe_transaction()
                # It returns in the read-only phase of the chip-select rise.
                settled = True
            except Exception as exc:  # noqa: BLE001
                self.log.error("%s: exception while observing: %s", self.name, exc)
                if self._error is None:
                    self._error = exc

    async def _watch_idle(self, settled: bool) -> None:
        """Return when chip-select falls; grade every SCK move while it is high.

        ``settled`` tells that the caller is already in the read-only phase of
        the chip-select rise. The data lane output enables are graded at the
        start of every idle period, then on every change.
        """
        if _level(self._cs_n) == 0:
            await RisingEdge(self._cs_n)
            settled = False
        triggers = [Edge(self._cs_n), Edge(self._sclk)]
        if self._sd_oe is not None:
            triggers.append(Edge(self._sd_oe))
        if not settled:
            await ReadOnly()
        oe_prev = _vector(self._sd_oe)
        if self._sd_oe is not None and _level(self._cs_n) == 1 and oe_prev:
            self._violate(
                [],
                "oe_idle",
                f"data lane output enable {_fmt_vec(oe_prev)} with chip-select high "
                f"at {_sim_time_ns()} ns",
            )
        self._sck_idle_seen = _level(self._sclk)
        while True:
            await First(*triggers)
            # Grade the time step once every change of it has settled.
            await ReadOnly()
            cs = _level(self._cs_n)
            if cs == 0:
                return
            if cs is None:
                # Before chip select resolves (reset) nothing is graded.
                continue
            if self._sd_oe is not None:
                oe = _vector(self._sd_oe)
                if oe is not None and oe_prev is not None and oe & ~oe_prev:
                    self._violate(
                        [],
                        "oe_idle",
                        f"data lane output enable rose to {_fmt_vec(oe)} with chip-select "
                        f"high at {_sim_time_ns()} ns",
                    )
                oe_prev = oe
            sck = _level(self._sclk)
            if sck is None:
                continue
            if (
                self._sd_oe is not None
                and self._sck_idle_seen is not None
                and sck != self._sck_idle_seen
                and (oe_prev or 0)
            ):
                self._violate(
                    [],
                    "oe_idle",
                    f"data lane output enable {_fmt_vec(oe_prev)} at an SCK edge with "
                    f"chip-select high at {_sim_time_ns()} ns",
                )
            self._sck_idle_seen = sck
            if sck != self._cpol:
                self._violate(
                    [],
                    "sck_while_idle",
                    f"SCK moved to {_fmt(sck)} with chip-select high at {_sim_time_ns()} ns "
                    f"(CPOL={self._cpol})",
                )

    async def _observe_transaction(self) -> None:
        """Observe one SPI transaction from CS_N low to CS_N high."""
        start_ns = _sim_time_ns()
        cpol, cpha = self._cpol, self._cpha
        sample_level = 1 if cpol == cpha else 0
        errors: List[str] = []
        mosi_bits: List[int] = []
        beats: List[Tuple[Optional[int], Optional[int], Optional[int]]] = []
        miso_raw: List[Optional[int]] = []
        miso_idle = self._miso_level()

        sck_prev = _level(self._sclk)
        if sck_prev != cpol:
            self._violate(
                errors,
                "idle_at_cs_fall",
                f"SCK={_fmt(sck_prev)} at chip-select fall at {start_ns} ns (CPOL={cpol})",
            )
        out_prev = self._driven_lanes()
        xz_prev = self._grade_xz(errors, start_ns, None)
        mosi_change_ns: Optional[float] = None
        last_edge_ns: Optional[float] = None
        last_edge_sample = False
        half_ns: Optional[float] = None  # time between the two latest SCK edges
        # A MOSI change after a sample edge fails when the next shift edge
        # follows on the running clock: (change time, sample time, half period).
        pending: Optional[Tuple[float, float, Optional[float]]] = None

        triggers = [Edge(self._sclk), Edge(self._cs_n)]
        for handle in (self._mosi, self._sd_out, self._sd_oe):
            if handle is not None:
                triggers.append(Edge(handle))

        while True:
            await First(*triggers)
            await ReadOnly()
            now = _sim_time_ns() or 0.0
            cs = _level(self._cs_n)
            if cs != 0:
                if cs is None:
                    self._violate(errors, "xz", f"chip-select is X/Z at {now} ns")
                break
            xz_prev = self._grade_xz(errors, now, xz_prev)

            sck = _level(self._sclk)
            if sck != sck_prev:
                sck_prev = sck
                if sck is None:
                    self._violate(errors, "xz", f"SCK is X/Z at {now} ns")
                    continue
                is_sample = sck == sample_level
                if is_sample:
                    if mosi_change_ns == now:
                        self._violate(
                            errors, "mosi_edge", f"MOSI changed at a sample edge at {now} ns"
                        )
                    self._sample_edge(errors, now, mosi_bits, beats)
                    miso_raw.append(self._miso_level())
                elif pending is not None:
                    changed, sampled, half = pending
                    if half is None or now - sampled <= 1.5 * half:
                        self._violate(
                            errors,
                            "mosi_edge",
                            f"MOSI changed at {changed} ns, after the sample edge at {sampled} ns "
                            f"and before the shift edge at {now} ns",
                        )
                    pending = None
                if last_edge_ns is not None:
                    half_ns = now - last_edge_ns
                last_edge_ns, last_edge_sample = now, is_sample

            out = self._driven_lanes()
            if out != out_prev:
                changed = _lanes_changed(out_prev, out)
                out_prev = out
                if changed:
                    mosi_change_ns = now
                    if last_edge_ns is None or not last_edge_sample:
                        pass
                    elif last_edge_ns == now:
                        self._violate(
                            errors, "mosi_edge", f"MOSI changed at a sample edge at {now} ns"
                        )
                    elif pending is None:
                        pending = (now, last_edge_ns, half_ns)

        sck = _level(self._sclk)
        if sck != cpol:
            self._violate(
                errors,
                "idle_at_cs_rise",
                f"SCK={_fmt(sck)} at chip-select rise at {_sim_time_ns()} ns (CPOL={cpol})",
            )
        end_ns = _sim_time_ns()

        txn = self._decode(mosi_bits, miso_raw, start_ns, end_ns, beats)
        if self._sd_oe is not None and self._sd_out is not None:
            self._grade_output_enables(errors, txn, beats)
        txn.update(
            cpol=cpol,
            cpha=cpha,
            wire_errors=tuple(errors),
            beats=tuple(beats),
            miso_idle=miso_idle,
            miso_raw=tuple(miso_raw),
        )
        self._history.append(txn)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        self._stats["transactions_seen"] += 1
        self._stats["bytes_mosi"] += len(txn["data_mosi"])
        self._stats["bytes_miso"] += len(txn["data_miso"])

        self.log.info(
            "%s: %s addr=0x%06X bits=%d mosi=%dB miso=%dB mode=%d%d wire_errors=%d",
            self.name,
            opcode_name(txn["opcode"]) if txn["opcode_complete"] else "PARTIAL",
            txn["addr"],
            txn["bit_count"],
            len(txn["data_mosi"]),
            len(txn["data_miso"]),
            cpol,
            cpha,
            len(errors),
        )

        try:
            self._stats["callback_errors"] += _fire_callbacks(self.log, self._callbacks, txn)
        except AssertionError as exc:
            self.log.error("%s: callback assertion: %s", self.name, exc)
            if self._error is None:
                self._error = exc

    def _driven_lanes(self) -> Optional[Tuple[int, int]]:
        """(lane values, lanes driven) the controller presents; ``None`` when X/Z."""
        if self._sd_out is not None:
            value = _vector(self._sd_out)
            oe = 0xF if self._sd_oe is None else _vector(self._sd_oe)
            if value is None or oe is None:
                return None
            return value & oe, oe
        if self._mosi is not None:
            bit = _level(self._mosi)
            return None if bit is None else (bit, 1)
        return (0, 0)

    def _sample_edge(self, errors, now, mosi_bits, beats) -> None:
        """Record one sample edge: the lane bits, the beat, and the output-enable checks."""
        mosi = self._mosi
        if mosi is None and self._sd_out is not None:
            value = _vector(self._sd_out)
            oe = _vector(self._sd_oe) if self._sd_oe is not None else 1
            lane0 = None if value is None or oe is None else value & 1
            mosi_bits.append(lane0 or 0)
        else:
            mosi_bits.append(0 if mosi is None else _level(mosi) or 0)
        if self._sd_out is None:
            return
        out, oe, inp = _vector(self._sd_out), _vector(self._sd_oe), _vector(self._sd_in)
        beats.append((out, oe, inp))
        if self._sd_oe is not None:
            if oe is None or oe not in _LEGAL_OE:
                self._violate(
                    errors, "oe_lanes", f"data lane output enable {_fmt_vec(oe)} at {now} ns"
                )
        for handle, what in ((self._cs_oe, "chip-select"), (self._sck_oe, "clock")):
            if handle is not None and _level(handle) != 1:
                self._violate(
                    errors,
                    "oe_ctrl",
                    f"{what} output enable is {_fmt(_level(handle))} with chip-select low "
                    f"at {now} ns",
                )

    def _grade_output_enables(self, errors: List[str], txn: Dict[str, Any], beats) -> None:
        """Every controller-output clock of the frame had its lanes' output enables on.

        The controller-output clocks are the command byte, the address, and
        the payload of a command without a response (any extra bit after an
        exact command included). Dummy and response clocks, and the clocks
        after the command byte of an unknown command, are not graded.
        """
        masks = _output_lane_masks(
            int(txn["opcode"]), bool(txn["opcode_complete"]), len(beats), self._addr_bytes
        )
        bad = [
            (i, mask, beats[i][1])
            for i, mask in enumerate(masks)
            if mask and (beats[i][1] is None or beats[i][1] & mask != mask)
        ]
        if bad:
            i, mask, oe = bad[0]
            self._violate(
                errors,
                "oe_data",
                f"{len(bad)} controller-output clock(s) of "
                f"{opcode_name(txn['opcode']) if txn['opcode_complete'] else 'PARTIAL'} "
                f"sampled with a lane output enable off; first: clock {i} output enables "
                f"{_fmt_vec(oe)}, lanes {_fmt_vec(mask)} carry data",
            )

    def _miso_level(self) -> Optional[int]:
        """The response lane into the controller (MISO, or lane 1 in); ``None`` when X/Z."""
        if self._miso is not None:
            return _level(self._miso)
        if self._sd_in is not None:
            lanes = _vector(self._sd_in)
            return None if lanes is None else (lanes >> 1) & 1
        return 0

    def _driven_xz(self) -> Optional[str]:
        """What the controller drives as X/Z at this step; ``None`` when every driven pin resolves."""
        if self._sd_out is not None:
            oe = 0xF if self._sd_oe is None else _vector(self._sd_oe)
            if oe is None:
                return "a data lane output enable is X/Z"
            if oe and _has_xz(self._sd_out, oe):
                return f"a driven data lane is X/Z (output enables {_fmt_vec(oe)})"
            return None
        if self._mosi is not None and _level(self._mosi) is None:
            return "MOSI is X/Z"
        return None

    def _grade_xz(self, errors: List[str], now, prev: Optional[str]) -> Optional[str]:
        """Grade the driven lanes at one settled step with chip-select low.

        One X/Z episode is one violation: it is recorded when the X/Z starts
        or changes, not again at each later step while it lasts.
        """
        what = self._driven_xz()
        if what is not None and what != prev:
            self._violate(errors, "xz", f"{what} with chip-select low at {now} ns")
        return what

    def _violate(self, errors: List[str], check: str, text: str) -> None:
        """Record one wire-check violation."""
        line = f"{check}: {text}"
        errors.append(line)
        self._wire_errors.append(line)
        self.log.error("%s: wire check %s", self.name, line)

    # ------------------------------------------------------------------
    # Decode bit stream
    # ------------------------------------------------------------------

    def _decode(
        self,
        mosi_bits: List[int],
        miso_raw: List[Optional[int]],
        start_ns,
        end_ns,
        beats: Optional[List[Tuple[Optional[int], Optional[int], Optional[int]]]] = None,
    ) -> Dict[str, Any]:
        """Convert raw bit lists into a structured transaction record.

        A dual or quad command (``LANE_OPCODES``) seen through the four-lane
        taps takes its address and data from the lanes of each phase, at the
        widths of its command format; ``data_mosi`` and ``data_miso`` then
        hold those bytes. The data fields hold complete bytes only; a byte
        left incomplete when chip-select rises is not reported as data
        (``bit_count`` gives its bits). ``data_miso_xz`` lists the
        ``data_miso`` bytes with a bit sampled as X/Z, which reads as 0.
        """
        miso_bits = [bit or 0 for bit in miso_raw]
        mosi_bytes = _bits_to_bytes(mosi_bits)
        mosi_whole = mosi_bytes[: len(mosi_bits) // 8]
        miso_whole = _bits_to_bytes(miso_bits)[: len(miso_bits) // 8]

        opcode = mosi_bytes[0] if mosi_bytes else 0
        has_addr = opcode in _ADDR_COMMANDS
        addr = 0

        if has_addr and len(mosi_bytes) > 1:
            for i in range(1, min(1 + self._addr_bytes, len(mosi_bytes))):
                addr = (addr << 8) | mosi_bytes[i]

        # The response phase starts after the opcode, the address bytes of an
        # addressed command, and the dummy bytes of a FAST READ.
        data_start = 1 + (self._addr_bytes if has_addr else 0)
        if opcode == OcahSpiOpcode.FAST_READ:
            data_start += self._fast_read_dummies

        complete = len(mosi_bits) >= 8
        input_bits = len(mosi_bits)
        if complete and opcode in _MISO_COMMANDS:
            input_bits = min(input_bits, 8 * data_start)
        fmt = command_format(opcode) if complete else None
        input_clocks = len(mosi_bits)
        if fmt is not None and fmt.response:
            input_clocks = min(input_clocks, fmt.input_clocks(self._addr_bytes))

        data_mosi = mosi_whole[data_start:] if opcode in _MOSI_COMMANDS else b""
        data_miso = miso_whole[data_start:] if opcode in _MISO_COMMANDS else b""
        data_miso_xz = tuple(
            i
            for i in range(len(data_miso))
            if None in miso_raw[8 * (data_start + i) : 8 * (data_start + i + 1)]
        )
        if complete and opcode in LANE_OPCODES and beats and fmt is not None:
            has_addr, addr, data_mosi, data_miso, data_miso_xz = self._decode_lanes(fmt, beats)

        return {
            "opcode": opcode,
            "addr": addr,
            "has_addr": has_addr,
            "data_mosi": data_mosi,
            "data_miso": data_miso,
            "data_miso_xz": data_miso_xz,
            "bit_count": len(mosi_bits),
            "input_bits": input_bits,
            "input_clocks": input_clocks,
            "opcode_complete": complete,
            "start_ns": start_ns,
            "end_ns": end_ns,
        }

    def _decode_lanes(self, fmt, beats) -> Tuple[bool, int, bytes, bytes, Tuple[int, ...]]:
        """Address, data and X/Z response bytes of a dual or quad command.

        A response byte is X/Z when the input lanes held an X/Z bit at one of
        its sample edges.
        """

        def phase(start: int, stop: Optional[int], field: int, lanes: int) -> bytes:
            shift = 1 if field == 2 and lanes == 1 else 0
            values = [((beat[field] or 0) >> shift) for beat in beats[start:stop]]
            return bytes(lanes_to_bytes(values, lanes)[0])

        addr_clocks = (8 * self._addr_bytes) // fmt.addr_lanes if fmt.addr_lanes else 0
        addr_bytes = phase(8, 8 + addr_clocks, 0, fmt.addr_lanes or 1) if addr_clocks else b""
        addr = int.from_bytes(addr_bytes, "big") if addr_bytes else 0
        if fmt.response:
            start = fmt.input_clocks(self._addr_bytes)
            data = phase(start, None, 2, fmt.data_lanes)
            per_byte = 8 // fmt.data_lanes
            xz = tuple(
                i
                for i in range(len(data))
                if any(
                    beat[2] is None
                    for beat in beats[start + i * per_byte : start + (i + 1) * per_byte]
                )
            )
            return bool(addr_clocks), addr, b"", data, xz
        return bool(addr_clocks), addr, phase(8 + addr_clocks, None, 0, fmt.data_lanes), b"", ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sim_time_ns() -> Optional[float]:
    """Simulation time in ns, ``None`` when the simulator exposes none."""
    try:
        return float(cocotb.utils.get_sim_time("ns"))
    except Exception:  # noqa: BLE001
        return None


def _level(sig) -> Optional[int]:
    """0 or 1 for a resolved single-bit handle, ``None`` for X/Z."""
    value = sig.value
    if not value.is_resolvable:
        return None
    return int(value) & 0x1


def _fmt(level: Optional[int]) -> str:
    return "X/Z" if level is None else str(level)


# Output-enable patterns of a data phase: none (receive or dummy), lane 0
# (single), lanes 1:0 (dual), lanes 3:0 (quad).
_LEGAL_OE = frozenset((0b0000, 0b0001, 0b0011, 0b1111))


def _output_lane_masks(opcode: int, complete: bool, clocks: int, addr_bytes: int) -> List[int]:
    """Lanes that carry controller data at each clock of a frame; 0 where none is graded."""
    if not complete:
        return [1] * clocks
    masks = [1] * 8
    fmt = command_format(opcode)
    if fmt is not None:
        if fmt.addr_lanes:
            masks += [(1 << fmt.addr_lanes) - 1] * ((8 * addr_bytes) // fmt.addr_lanes)
        if not fmt.response:
            masks += [(1 << fmt.data_lanes) - 1] * max(0, clocks - len(masks))
    elif opcode in (
        OcahSpiOpcode.WRITE_ENABLE,
        OcahSpiOpcode.WRITE_DISABLE,
        OcahSpiOpcode.SECTOR_ERASE,
    ):
        # Address and any extra bit: the device takes each one as input.
        masks += [1] * max(0, clocks - 8)
    masks += [0] * max(0, clocks - len(masks))
    return masks[:clocks]


def _vector(sig) -> Optional[int]:
    """Integer value of a vector handle, ``None`` when any bit is X/Z or there is no handle."""
    if sig is None:
        return None
    value = sig.value
    if not value.is_resolvable:
        return None
    return int(value)


def _fmt_vec(value: Optional[int]) -> str:
    return "X/Z" if value is None else f"0b{value:04b}"


def _has_xz(sig, mask: int) -> bool:
    """True when a bit of ``sig`` selected by ``mask`` is X/Z."""
    text = str(sig.value)
    width = len(text)
    return any((mask >> (width - 1 - i)) & 1 and ch.lower() in "xzuw-" for i, ch in enumerate(text))


def _lanes_changed(prev, cur) -> bool:
    """A lane that both samples drive changed value, or either sample is X/Z."""
    if prev is None or cur is None:
        return bool(prev != cur)
    (prev_value, prev_oe), (cur_value, cur_oe) = prev, cur
    return bool((prev_value ^ cur_value) & prev_oe & cur_oe)


def _bits_to_bytes(bits: List[int]) -> bytes:
    """Pack a list of 1/0 bits (MSB-first) into bytes, right-padding a partial byte with 0."""
    out: List[int] = []
    i = 0
    while i < len(bits):
        byte_val = 0
        for j in range(8):
            if i + j < len(bits):
                byte_val = (byte_val << 1) | (bits[i + j] & 0x1)
            else:
                byte_val <<= 1
        out.append(byte_val)
        i += 8
    return bytes(out)


def _fire_callbacks(log: logging.Logger, callbacks: list, *args) -> int:
    """Call each callback; a checker verdict propagates, any other exception is logged and counted."""
    errors = 0
    for fn in callbacks:
        try:
            fn(*args)
        except AssertionError:
            raise
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log.error("Exception in SpiMonitor callback %s: %s", fn, exc)
    return errors
