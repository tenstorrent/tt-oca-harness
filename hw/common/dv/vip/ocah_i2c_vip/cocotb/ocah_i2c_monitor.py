# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
OcahI2cMonitor — passive I2C bus monitor with per-transaction callbacks.

Attaches non-intrusively to the I2C bus (SCL + SDA).  Each completed
transaction — write or read — is dispatched to registered callbacks.  No
data is consumed or acknowledged; the monitor does not act as a bus device.

Public API
----------
OcahI2cMonitor(scl, sda, clock, *, name, speed)
    .add_write_callback(fn)   — fn(addr: int, data: bytes) -> None
    .add_read_callback(fn)    — fn(addr: int, length: int, data: bytes) -> None
    await .start()
    await .stop()
    .get_transactions()   -> list[dict]
    .clear_history()
    .get_statistics()     -> dict

Callback signatures
-------------------
Write callback: ``fn(addr: int, data: bytes) -> None``
  - ``addr``  : 7-bit device address.
  - ``data``  : payload bytes written (after the address phase).

Read callback: ``fn(addr: int, length: int, data: bytes) -> None``
  - ``addr``  : 7-bit device address.
  - ``length``: number of bytes requested.
  - ``data``  : data bytes read back (may be empty if not observable).

Callbacks are fired in a cocotb task.  Exceptions are caught and logged.

Dependency
----------
``cocotbext-i2c == 0.1.2`` — see ``ocah_i2c_master.py`` for install notes.
"""

import logging
from typing import Callable, Dict, List, Any, Optional

import cocotb
from cocotb.triggers import Timer

from .ocah_i2c_master import (
    _COCOTBEXT_I2C_AVAILABLE,
    OcahI2cImportError,
)

__all__ = ["OcahI2cMonitor"]

# Lazy import of the cocotbext-i2c monitor/bus class.
_I2cBus = None

if _COCOTBEXT_I2C_AVAILABLE:
    try:
        from cocotbext.i2c import I2cBus  # type: ignore[import]
        _I2cBus = I2cBus
    except ImportError:
        # Fallback: some versions may not provide I2cBus.
        _I2cBus = None

_HISTORY_MAX = 2000


def _fire_callbacks(callbacks: list, *args) -> None:
    """Invoke each callback; log but do not re-raise exceptions."""
    for fn in callbacks:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).error(
                "Exception in OcahI2cMonitor callback %s: %s", fn, exc
            )


class OcahI2cMonitor:
    """
    Passive I2C bus monitor.

    Observes I2C bus transactions without driving any bus signal.  Each
    completed transaction is recorded and dispatched to registered callbacks.

    Parameters
    ----------
    scl :
        Cocotb signal handle for the I2C SCL line.
    sda :
        Cocotb signal handle for the I2C SDA line.
    clock :
        Cocotb clock handle (informational).
    name :
        Instance label used in log messages.
    speed :
        I2C bus speed in Hz.  Should match the actual bus speed.
    max_history :
        Maximum number of transactions to retain in history.

    Note on ``cocotbext-i2c`` passive monitoring
    --------------------------------------------
    The ``alexforencich/cocotbext-i2c`` library does not expose a dedicated
    "monitor-only" API in version 0.1.2.  This class implements bit-banging
    observation directly on the SCL/SDA signals via cocotb edge triggers, which
    is compatible with both VCS and Verilator simulation backends.
    """

    def __init__(
        self,
        scl,
        sda,
        clock,
        *,
        name: str = "OcahI2cMonitor",
        speed: int = 100_000,
        max_history: int = _HISTORY_MAX,
    ):
        if not _COCOTBEXT_I2C_AVAILABLE:
            raise OcahI2cImportError()

        self.name        = name
        self._scl        = scl
        self._sda        = sda
        self._clock      = clock
        self._speed      = speed
        self._max_history = max_history
        self.log         = logging.getLogger(name)

        self._write_callbacks: List[Callable] = []
        self._read_callbacks:  List[Callable] = []

        self._history: List[Dict[str, Any]] = []

        self._running  = False
        self._mon_task: Optional[Any] = None

        self._stats: Dict[str, int] = {
            "write_transactions": 0,
            "read_transactions":  0,
        }

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def add_write_callback(self, fn: Callable) -> None:
        """Register a callback for observed write transactions.

        Signature: ``fn(addr: int, data: bytes) -> None``
        """
        self._write_callbacks.append(fn)

    def add_read_callback(self, fn: Callable) -> None:
        """Register a callback for observed read transactions.

        Signature: ``fn(addr: int, length: int, data: bytes) -> None``
        """
        self._read_callbacks.append(fn)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start passive bus monitoring.  Safe to call multiple times."""
        if self._running:
            return
        self._running  = True
        self._mon_task = cocotb.start_soon(self._monitor_loop())
        self.log.info(
            "%s: I2C passive monitoring started (speed=%d Hz)", self.name, self._speed
        )

    async def stop(self) -> None:
        """Stop monitoring.  Buffered transactions are retained."""
        if not self._running:
            return
        self._running = False
        if self._mon_task is not None:
            self._mon_task.kill()
            self._mon_task = None
        self.log.info("%s: I2C passive monitoring stopped", self.name)

    # ------------------------------------------------------------------
    # Internal monitor loop (bit-bang observation)
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Observe SCL/SDA transitions and reconstruct I2C transactions."""
        from cocotb.triggers import Edge, RisingEdge, FallingEdge  # noqa: PLC0415

        while self._running:
            # --- Wait for START condition: SDA falls while SCL is high ---
            # We poll for SCL=1 & SDA=1 first (idle), then watch for START.
            try:
                await self._wait_for_start()
            except Exception as exc:  # noqa: BLE001
                self.log.debug("%s: monitor idle wait: %s", self.name, exc)
                await Timer(1, units="us")
                continue

            # --- Receive address + RW bit ---
            try:
                addr_byte = await self._recv_byte()
            except Exception:  # noqa: BLE001
                continue

            device_addr = (addr_byte >> 1) & 0x7F
            rw          = addr_byte & 0x01   # 1 = read, 0 = write

            # --- ACK phase (skip; we are passive) ---
            # In a real ACK the device pulls SDA low; we just wait one bit.
            await self._skip_bit()

            payload = bytearray()
            length  = 0

            if rw == 0:
                # Write transaction: collect data bytes until STOP or NACK.
                while True:
                    if await self._detect_stop_or_start():
                        break
                    try:
                        b = await self._recv_byte()
                    except Exception:  # noqa: BLE001
                        break
                    payload.append(b)
                    await self._skip_bit()   # ACK bit

                rec = {
                    "rw":    "write",
                    "addr":  device_addr,
                    "data":  bytes(payload),
                }
                self._history.append(rec)
                if len(self._history) > self._max_history:
                    self._history.pop(0)
                self._stats["write_transactions"] += 1
                self.log.debug(
                    "%s: write addr=0x%02X len=%d", self.name, device_addr, len(payload)
                )
                _fire_callbacks(self._write_callbacks, device_addr, bytes(payload))

            else:
                # Read transaction: count data bytes until STOP.
                while True:
                    if await self._detect_stop_or_start():
                        break
                    try:
                        b = await self._recv_byte()
                    except Exception:  # noqa: BLE001
                        break
                    payload.append(b)
                    length += 1
                    await self._skip_bit()   # NACK/ACK bit

                rec = {
                    "rw":     "read",
                    "addr":   device_addr,
                    "length": length,
                    "data":   bytes(payload),
                }
                self._history.append(rec)
                if len(self._history) > self._max_history:
                    self._history.pop(0)
                self._stats["read_transactions"] += 1
                self.log.debug(
                    "%s: read addr=0x%02X len=%d", self.name, device_addr, length
                )
                _fire_callbacks(
                    self._read_callbacks, device_addr, length, bytes(payload)
                )

    # ------------------------------------------------------------------
    # Bit-bang helpers (passive, no bus driving)
    # ------------------------------------------------------------------

    async def _wait_for_start(self) -> None:
        """Block until a START condition is observed (SDA falls while SCL=1)."""
        from cocotb.triggers import FallingEdge  # noqa: PLC0415
        while True:
            await FallingEdge(self._sda)
            if int(self._scl.value) == 1:
                return   # START detected

    async def _detect_stop_or_start(self) -> bool:
        """Return True if a STOP or repeated START is imminent.

        A STOP is SDA rising while SCL is high.  We approximate detection
        by checking current bus state.
        """
        # If SCL and SDA are both high, we are in a STOP or idle state.
        try:
            scl_val = int(self._scl.value)
            sda_val = int(self._sda.value)
            return scl_val == 1 and sda_val == 1
        except Exception:  # noqa: BLE001
            return False

    async def _recv_byte(self) -> int:
        """Receive 8 bits by sampling SDA on each rising SCL edge."""
        from cocotb.triggers import RisingEdge  # noqa: PLC0415
        result = 0
        for _ in range(8):
            await RisingEdge(self._scl)
            bit = int(self._sda.value) & 1
            result = (result << 1) | bit
        return result

    async def _skip_bit(self) -> None:
        """Wait for one SCL clock edge (ACK/NACK bit; we do not drive SDA)."""
        from cocotb.triggers import RisingEdge  # noqa: PLC0415
        await RisingEdge(self._scl)

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_transactions(self) -> List[Dict[str, Any]]:
        """Return a copy of the completed transaction history (oldest first).

        Each entry is a dict with keys:
          ``rw``     : ``"write"`` or ``"read"``
          ``addr``   : 7-bit device address (int)
          ``data``   : payload bytes (bytes)
          ``length`` : bytes requested (read transactions only)
        """
        return list(self._history)

    def clear_history(self) -> None:
        """Discard all retained transaction records."""
        self._history.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Return cumulative transaction counters."""
        return dict(self._stats)
