# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
OcahI2cMemory — OCAH I2C memory-style device (EEPROM emulation).

Emulates an I2C EEPROM-style device where the first byte(s) of every write
set an internal register/address pointer and subsequent bytes write to that
address.  Read transactions return bytes starting from the current pointer,
auto-incrementing after each byte.

Protocol assumed
----------------
- **Write**: START + DEV_ADDR(W) + ADDR_BYTE(s) + DATA_BYTE(s) + STOP
  - The first ``addr_bytes`` bytes of the payload set the memory pointer.
  - Remaining bytes are written to memory starting at that address.
- **Read** (combined): START + DEV_ADDR(W) + ADDR_BYTE(s) + RESTART +
  DEV_ADDR(R) + DATA + STOP
  - Returns ``length`` bytes starting at the current pointer.
- **Sequential read**: pointer auto-increments; wraps at ``mem_size``.

This is compatible with the AT24Cxx, M24xx, and similar single-supply I2C
EEPROM families.  Page-write boundaries are not enforced; callers that need
byte-granularity writes can write one byte at a time.

Public API
----------
OcahI2cMemory(scl, sda, clock, *, name, addr, mem_size, addr_bytes, speed)
    .preload(source)          — preload from file path or bytes
    .dump()                   -> bytes (full memory snapshot)
    .read_mem(offset, length) -> bytes (direct read bypassing I2C)
    .write_mem(offset, data)               (direct write bypassing I2C)
    await .start()
    await .stop()
    .get_statistics() -> dict

The ``preload`` and ``dump`` methods bypass the I2C bus; they act directly on
the internal memory array and are useful for test setup and post-test
inspection.

Dependency
----------
``cocotbext-i2c == 0.1.2`` — see ``ocah_i2c_master.py`` for install notes.
"""

import logging
import os
import struct
from typing import Dict, Any, List, Optional, Union

import cocotb
from cocotb.triggers import Timer

from .ocah_i2c_master import (
    _COCOTBEXT_I2C_AVAILABLE,
    OcahI2cImportError,
    OcahI2cError,
)
from .ocah_i2c_device import _I2cSlave

__all__ = ["OcahI2cMemory"]


class OcahI2cMemory:
    """
    I2C EEPROM-style memory device.

    Maintains an internal byte array of ``mem_size`` bytes.  Behaves as a
    standard I2C EEPROM: writes set the address pointer and store data; reads
    return data from the current pointer with auto-increment.

    Parameters
    ----------
    scl :
        Cocotb signal handle for SCL.
    sda :
        Cocotb signal handle for SDA.
    clock :
        Cocotb clock handle.
    name :
        Instance label used in log messages.
    addr :
        7-bit I2C address (0x00–0x7F).  Common EEPROM default: 0x50.
    mem_size :
        Memory capacity in bytes.  Default 256 bytes (AT24C02 equivalent).
    addr_bytes :
        Number of address bytes in each write preamble.  1 for ≤ 256-byte
        devices, 2 for larger devices.
    speed :
        I2C bus speed in Hz.
    """

    def __init__(
        self,
        scl,
        sda,
        clock,
        *,
        name: str = "OcahI2cMemory",
        addr: int = 0x50,
        mem_size: int = 256,
        addr_bytes: int = 1,
        speed: int = 100_000,
    ):
        if not _COCOTBEXT_I2C_AVAILABLE or _I2cSlave is None:
            raise OcahI2cImportError()

        self.name       = name
        self._clock     = clock
        self._speed     = speed
        self._mem_size  = mem_size
        self._addr_bytes = addr_bytes
        self.log        = logging.getLogger(name)

        if not 0 <= addr <= 0x7F:
            raise ValueError(
                f"{name}: 7-bit I2C address must be 0x00–0x7F, got 0x{addr:02X}"
            )
        self._i2c_addr = addr

        if addr_bytes not in (1, 2):
            raise ValueError(
                f"{name}: addr_bytes must be 1 or 2, got {addr_bytes}"
            )

        # Internal memory; initialised to 0xFF (erased EEPROM convention).
        self._mem   = bytearray(b"\xFF" * mem_size)
        self._ptr   = 0   # current address pointer (auto-increments on read)

        self._slave = _I2cSlave(scl, sda, addr=addr, speed=speed)

        self._running  = False
        self._poll_task: Optional[Any] = None

        self._stats: Dict[str, int] = {
            "write_transactions":  0,
            "read_transactions":   0,
            "bytes_written":       0,
            "bytes_read":          0,
            "address_out_of_range": 0,
        }

    # ------------------------------------------------------------------
    # Direct memory access (bypasses I2C bus)
    # ------------------------------------------------------------------

    def preload(self, source: Union[str, bytes, bytearray]) -> None:
        """Preload memory contents.

        Parameters
        ----------
        source :
            A file-system path (``str``) or a ``bytes``/``bytearray`` blob.
            When a path is given the file is read in binary mode and its
            contents are written to memory starting at offset 0.  Excess bytes
            beyond ``mem_size`` are silently truncated; if the source is
            shorter than ``mem_size`` the remainder stays at 0xFF.
        """
        if isinstance(source, str):
            if not os.path.exists(source):
                raise FileNotFoundError(
                    f"{self.name}: preload file not found: {source}"
                )
            with open(source, "rb") as fh:
                blob = fh.read(self._mem_size)
            self.log.info(
                "%s: preloaded %d bytes from %s", self.name, len(blob), source
            )
        elif isinstance(source, (bytes, bytearray)):
            blob = bytes(source)[: self._mem_size]
            self.log.info(
                "%s: preloaded %d bytes from blob", self.name, len(blob)
            )
        else:
            raise TypeError(
                f"{self.name}: preload source must be a file path str or bytes, "
                f"got {type(source).__name__}"
            )

        self._mem[: len(blob)] = blob

    def dump(self) -> bytes:
        """Return a snapshot of the full memory contents.

        Returns
        -------
        bytes
            All ``mem_size`` bytes of the internal memory array.
        """
        return bytes(self._mem)

    def read_mem(self, offset: int, length: int) -> bytes:
        """Read bytes from memory directly, bypassing the I2C bus.

        Parameters
        ----------
        offset :
            Starting byte offset (0-based).
        length :
            Number of bytes to read.
        """
        if offset < 0 or offset + length > self._mem_size:
            raise ValueError(
                f"{self.name}: read_mem out of range: offset={offset} "
                f"length={length} mem_size={self._mem_size}"
            )
        return bytes(self._mem[offset : offset + length])

    def write_mem(
        self,
        offset: int,
        data: Union[bytes, bytearray, List[int]],
    ) -> None:
        """Write bytes to memory directly, bypassing the I2C bus.

        Parameters
        ----------
        offset :
            Starting byte offset (0-based).
        data :
            Bytes to write.
        """
        if isinstance(data, list):
            data = bytes(data)
        data = bytes(data)
        if offset < 0 or offset + len(data) > self._mem_size:
            raise ValueError(
                f"{self.name}: write_mem out of range: offset={offset} "
                f"len={len(data)} mem_size={self._mem_size}"
            )
        self._mem[offset : offset + len(data)] = data

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start responding to I2C transactions on the bus."""
        if self._running:
            return
        self._running   = True
        self._poll_task = cocotb.start_soon(self._dispatch_loop())
        self.log.info(
            "%s: I2C memory device active at addr=0x%02X "
            "(mem_size=%d, addr_bytes=%d, speed=%d Hz)",
            self.name, self._i2c_addr, self._mem_size, self._addr_bytes, self._speed,
        )

    async def stop(self) -> None:
        """Stop responding to I2C transactions."""
        if not self._running:
            return
        self._running = False
        if self._poll_task is not None:
            self._poll_task.kill()
            self._poll_task = None
        self.log.info("%s: I2C memory device stopped", self.name)

    # ------------------------------------------------------------------
    # Internal dispatch loop
    # ------------------------------------------------------------------

    async def _dispatch_loop(self) -> None:
        """Wait for incoming transactions and respond as an EEPROM."""
        while self._running:
            try:
                transaction = await self._slave.recv()
            except Exception as exc:  # noqa: BLE001
                self.log.error("%s: slave recv error: %s", self.name, exc)
                await Timer(1, units="us")
                continue

            if hasattr(transaction, "rw"):
                rw = "read" if transaction.rw else "write"
            else:
                rw = "write"

            data_in = bytes(transaction.data) if hasattr(transaction, "data") else b""

            if rw == "write":
                self._handle_write(data_in)
            else:
                response = self._handle_read(
                    getattr(transaction, "length", 1)
                )
                if hasattr(self._slave, "send"):
                    await self._slave.send(response)

    def _handle_write(self, data: bytes) -> None:
        """Process a write transaction: extract address pointer + data."""
        n = self._addr_bytes
        if len(data) < n:
            self.log.warning(
                "%s: write too short to contain address (%d < %d bytes); ignored",
                self.name, len(data), n,
            )
            self._stats["address_out_of_range"] += 1
            return

        # Decode the address pointer (big-endian, 1 or 2 bytes).
        if n == 1:
            new_ptr = data[0]
        else:
            new_ptr = struct.unpack_from(">H", data, 0)[0]

        # Clamp to memory size.
        if new_ptr >= self._mem_size:
            self.log.warning(
                "%s: write address 0x%04X out of range (mem_size=%d)",
                self.name, new_ptr, self._mem_size,
            )
            self._stats["address_out_of_range"] += 1
            new_ptr = new_ptr % self._mem_size

        self._ptr = new_ptr
        write_data = data[n:]

        for b in write_data:
            self._mem[self._ptr] = b
            self._ptr = (self._ptr + 1) % self._mem_size

        self._stats["write_transactions"] += 1
        self._stats["bytes_written"]      += len(write_data)
        self.log.debug(
            "%s: write addr=0x%04X len=%d", self.name, new_ptr, len(write_data)
        )

    def _handle_read(self, length: int) -> bytes:
        """Process a read transaction: return bytes from current pointer."""
        result = bytearray()
        for _ in range(length):
            result.append(self._mem[self._ptr])
            self._ptr = (self._ptr + 1) % self._mem_size

        self._stats["read_transactions"] += 1
        self._stats["bytes_read"]        += length
        self.log.debug(
            "%s: read ptr=0x%04X len=%d", self.name, (self._ptr - length) % self._mem_size, length
        )
        return bytes(result)

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        """Return cumulative transaction and byte counters."""
        return dict(self._stats)
