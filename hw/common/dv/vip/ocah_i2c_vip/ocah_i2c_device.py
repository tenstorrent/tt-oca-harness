# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
OcahI2cDevice — OCAH-stable passive I2C device emulator.

Emulates a simple I2C device that responds to a configurable 7-bit address.
Callers register a handler callback that is invoked on every completed
transaction; the callback can return data for read phases.

This class is the base device emulator.  For an EEPROM-style memory device,
see ``OcahI2cMemory``.

Public API
----------
OcahI2cDevice(scl, sda, clock, *, name, addr, speed)
    .set_address(addr)
    .register_handler(cb)
    await .start()
    await .stop()
    .get_write_data()  -> list[bytes]
    .clear_history()
    .get_statistics()  -> dict

Handler callback signature
--------------------------
``cb(addr: int, rw: str, data: bytes) -> bytes``

  - ``addr``   : 7-bit I2C address this device was addressed at.
  - ``rw``     : ``"write"`` or ``"read"``.
  - ``data``   : bytes received in a write phase; empty bytes for a read.
  - Return     : bytes to supply for a read phase; ignored for writes.

The callback is synchronous.  For async behaviour, register a cocotb task
via the normal ``cocotb.start_soon`` mechanism and return a pre-staged
response from the synchronous callback.

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

__all__ = ["OcahI2cDevice"]

# Lazy import of the cocotbext-i2c device class.
_I2cSlave = None

if _COCOTBEXT_I2C_AVAILABLE:
    try:
        from cocotbext.i2c import I2cSlave  # type: ignore[import]
        _I2cSlave = I2cSlave
    except ImportError:
        # Some cocotbext-i2c versions call it I2cDevice.
        try:
            from cocotbext.i2c import I2cDevice as I2cSlave  # type: ignore[import]
            _I2cSlave = I2cSlave
        except ImportError:
            _I2cSlave = None


def _fire_callbacks(callbacks: list, *args) -> Optional[bytes]:
    """Invoke callbacks; return the first non-None result."""
    result = None
    for fn in callbacks:
        try:
            ret = fn(*args)
            if ret is not None and result is None:
                result = ret
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).error(
                "Exception in OcahI2cDevice handler %s: %s", fn, exc
            )
    return result


class OcahI2cDevice:
    """
    OCAH-stable I2C device emulator (7-bit addressing).

    Listens on the I2C bus at a configurable 7-bit address.  Each completed
    transaction is dispatched to registered handler callbacks.

    Parameters
    ----------
    scl :
        Cocotb signal handle for the I2C SCL line.
    sda :
        Cocotb signal handle for the I2C SDA line.
    clock :
        Cocotb clock handle.
    name :
        Instance label used in log messages.
    addr :
        7-bit I2C address to respond to (0x00–0x7F).
    speed :
        I2C bus speed in Hz.  Must match the master.
    """

    def __init__(
        self,
        scl,
        sda,
        clock,
        *,
        name: str = "OcahI2cDevice",
        addr: int = 0x50,
        speed: int = 100_000,
    ):
        if not _COCOTBEXT_I2C_AVAILABLE or _I2cSlave is None:
            raise OcahI2cImportError()

        self.name    = name
        self._clock  = clock
        self._speed  = speed
        self.log     = logging.getLogger(name)

        if not 0 <= addr <= 0x7F:
            raise ValueError(
                f"{name}: 7-bit I2C address must be 0x00–0x7F, got 0x{addr:02X}"
            )
        self._addr = addr

        # cocotbext-i2c slave/device.
        self._slave = _I2cSlave(scl, sda, addr=addr, speed=speed)

        self._handlers: List[Callable] = []
        self._write_history: List[bytes] = []

        self._running  = False
        self._poll_task: Optional[Any] = None

        self._stats: Dict[str, int] = {
            "write_transactions": 0,
            "read_transactions":  0,
        }

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_address(self, addr: int) -> None:
        """Change the device I2C address.

        Must be called before :meth:`start`.  Reconfiguring a running device
        is not supported.

        Parameters
        ----------
        addr :
            New 7-bit address (0x00–0x7F).
        """
        if self._running:
            raise RuntimeError(
                f"{self.name}: cannot change address while device is running"
            )
        if not 0 <= addr <= 0x7F:
            raise ValueError(
                f"{self.name}: 7-bit I2C address must be 0x00–0x7F, got 0x{addr:02X}"
            )
        self._addr = addr
        self._slave.address = addr
        self.log.info("%s: I2C device address set to 0x%02X", self.name, addr)

    def register_handler(self, cb: Callable) -> None:
        """Register a transaction handler callback.

        Signature: ``cb(addr: int, rw: str, data: bytes) -> bytes``

        Multiple callbacks can be registered; they are called in registration
        order.  The first non-``None`` return value is used as the read
        response.  Exceptions inside callbacks are caught and logged.

        Parameters
        ----------
        cb :
            Callable matching the signature above.
        """
        self._handlers.append(cb)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start listening on the I2C bus.  Safe to call multiple times."""
        if self._running:
            return
        self._running  = True
        self._poll_task = cocotb.start_soon(self._dispatch_loop())
        self.log.info(
            "%s: I2C device listening at addr=0x%02X (speed=%d Hz)",
            self.name, self._addr, self._speed,
        )

    async def stop(self) -> None:
        """Stop listening on the I2C bus."""
        if not self._running:
            return
        self._running = False
        if self._poll_task is not None:
            self._poll_task.kill()
            self._poll_task = None
        self.log.info("%s: I2C device stopped", self.name)

    # ------------------------------------------------------------------
    # Internal dispatch loop
    # ------------------------------------------------------------------

    async def _dispatch_loop(self) -> None:
        """Wait for incoming transactions and dispatch callbacks."""
        while self._running:
            try:
                # cocotbext-i2c I2cSlave exposes an async recv() coroutine.
                transaction = await self._slave.recv()
            except Exception as exc:  # noqa: BLE001
                self.log.error("%s: slave recv error: %s", self.name, exc)
                await Timer(1, units="us")
                continue

            # Determine direction from the transaction object.
            # cocotbext-i2c sets ``transaction.rw`` to True for read, False
            # for write.  We normalise to the strings "read" / "write".
            if hasattr(transaction, "rw"):
                rw = "read" if transaction.rw else "write"
            else:
                rw = "write"  # default assumption

            data_in = bytes(transaction.data) if hasattr(transaction, "data") else b""

            self.log.debug(
                "%s: transaction rw=%s addr=0x%02X len=%d",
                self.name, rw, self._addr, len(data_in),
            )

            if rw == "write":
                self._write_history.append(data_in)
                self._stats["write_transactions"] += 1
                _fire_callbacks(self._handlers, self._addr, "write", data_in)
            else:
                self._stats["read_transactions"] += 1
                response = _fire_callbacks(
                    self._handlers, self._addr, "read", data_in
                ) or b"\x00"
                # Provide read data back to the slave so it can clock it out.
                if hasattr(self._slave, "send"):
                    await self._slave.send(bytes(response))

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_write_data(self) -> List[bytes]:
        """Return a copy of received write payloads (oldest first)."""
        return list(self._write_history)

    def clear_history(self) -> None:
        """Discard all retained transaction records."""
        self._write_history.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Return cumulative transaction counters."""
        return dict(self._stats)
