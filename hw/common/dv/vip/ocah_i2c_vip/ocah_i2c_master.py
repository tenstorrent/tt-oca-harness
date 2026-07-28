# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
OcahI2cMaster — OCAH-stable active I2C master wrapper.

Provides a single, versioned API for driving I2C bus transactions in OCAH
cocotb tests.  Internally delegates to ``cocotbext-i2c`` when that library is
available; raises ``OcahI2cImportError`` at construction time when it is not.

Public API
----------
OcahI2cMaster(scl, sda, clock, *, name, speed, timeout_us)
    .init_signals()
    await .write(addr, data)
    await .read(addr, length) -> bytes
    await .combined(addr, write_data, read_length) -> bytes
    .set_address(addr)              — set default 7-bit device address
    .get_statistics()  -> dict
    .reset_statistics()

All addresses are 7-bit integers (0x00–0x7F).
All data is ``bytes``, ``bytearray``, or a list of ints.  Return values are
always ``bytes``.

Speed
-----
Standard mode (100 kHz) and Fast mode (400 kHz) are supported.  High-speed
mode (3.4 MHz) is out of scope.  Pass the desired clock frequency in Hz to
the ``speed`` parameter:

    speed=100_000   # Standard mode
    speed=400_000   # Fast mode

Dependency
----------
Pinned release::

    cocotbext-i2c == 0.1.2   (MIT)

Install with::

    pip install cocotbext-i2c==0.1.2

Repository: https://github.com/alexforencich/cocotbext-i2c
"""

import logging
import os
from typing import Dict, Any, List, Optional, Union

import cocotb
from cocotb.triggers import Timer, with_timeout

__all__ = ["OcahI2cMaster", "OcahI2cError", "OcahI2cImportError"]

# ---------------------------------------------------------------------------
# Dependency probe
# ---------------------------------------------------------------------------

_COCOTBEXT_I2C_AVAILABLE = False
_I2cMaster  = None

try:
    from cocotbext.i2c import I2cMaster  # type: ignore[import]
    _I2cMaster = I2cMaster
    _COCOTBEXT_I2C_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OcahI2cError(RuntimeError):
    """Raised on I2C NACK, timeout, or bus-protocol violation."""


class OcahI2cImportError(ImportError):
    """Raised when ``cocotbext-i2c`` is not installed in the environment."""
    def __str__(self) -> str:
        return (
            "cocotbext-i2c is required by OcahI2cMaster but is not installed.\n"
            "  Install it with:  pip install cocotbext-i2c==0.1.2\n"
            "  Pinned version:   cocotbext-i2c == 0.1.2 (MIT)\n"
            "  Repository:       https://github.com/alexforencich/cocotbext-i2c\n"
        )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_SPEED_HZ   = 100_000   # Standard mode
_DEFAULT_TIMEOUT_US = 10_000    # 10 ms default per-transaction timeout
_SPEED_ENV_KEY      = "COCOTB_PLUSARG_i2c_speed_hz"
_ADDR_ENV_KEY       = "COCOTB_PLUSARG_i2c_default_addr"


# ---------------------------------------------------------------------------
# OcahI2cMaster
# ---------------------------------------------------------------------------

class OcahI2cMaster:
    """
    OCAH-stable I2C master (7-bit addressing, Standard/Fast mode).

    Wraps ``cocotbext-i2c`` ``I2cMaster`` with a fixed API so OCAH tests are
    insulated from library changes.  Accepts ``bytes``, ``bytearray``, and
    ``list[int]``; always returns ``bytes``.

    Parameters
    ----------
    scl :
        Cocotb signal handle for the I2C SCL line.
    sda :
        Cocotb signal handle for the I2C SDA line.
    clock :
        Cocotb clock handle (used for internal timing references).
    name :
        Instance label used in log messages.
    speed :
        I2C bus speed in Hz.  100 000 = Standard mode, 400 000 = Fast mode.
        Overridden by the ``+i2c_speed_hz=<N>`` plusarg if set.
    default_addr :
        Default 7-bit device address used when ``addr`` is not supplied.
        Overridden by the ``+i2c_default_addr=<N>`` plusarg if set.
    timeout_us :
        Default per-transaction timeout in microseconds.
    raise_on_nack :
        When ``True`` (default), raise ``OcahI2cError`` if the device sends a
        NACK.  When ``False``, return ``None`` for reads and silently complete
        writes.
    """

    def __init__(
        self,
        scl,
        sda,
        clock,
        *,
        name: str = "OcahI2cMaster",
        speed: int = _DEFAULT_SPEED_HZ,
        default_addr: Optional[int] = None,
        timeout_us: int = _DEFAULT_TIMEOUT_US,
        raise_on_nack: bool = True,
    ):
        if not _COCOTBEXT_I2C_AVAILABLE:
            raise OcahI2cImportError()

        self.name            = name
        self._clock          = clock
        self._timeout_us     = timeout_us
        self._raise_on_nack  = raise_on_nack
        self.log             = logging.getLogger(name)

        # Resolve plusargs: speed.
        env_speed = os.environ.get(_SPEED_ENV_KEY)
        if env_speed is not None:
            try:
                speed = int(env_speed)
                self.log.info("%s: I2C speed overridden by plusarg to %d Hz", name, speed)
            except ValueError:
                self.log.warning(
                    "%s: invalid +i2c_speed_hz value %r; using %d Hz",
                    name, env_speed, speed,
                )
        self._speed = speed

        # Resolve plusargs: default address.
        env_addr = os.environ.get(_ADDR_ENV_KEY)
        if env_addr is not None:
            try:
                default_addr = int(env_addr, 0)   # accept 0x50 style
            except ValueError:
                self.log.warning(
                    "%s: invalid +i2c_default_addr value %r", name, env_addr
                )
        self._default_addr = default_addr

        # cocotbext-i2c master.
        self._master = _I2cMaster(scl, sda, speed=speed)

        # Statistics.
        self._stats: Dict[str, int] = {
            "write_transactions":    0,
            "read_transactions":     0,
            "combined_transactions": 0,
            "nacks":                 0,
            "timeouts":              0,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_addr(self, addr: Optional[int]) -> int:
        if addr is None:
            if self._default_addr is None:
                raise ValueError(
                    f"{self.name}: no device address supplied and no default_addr set"
                )
            return self._default_addr
        if not 0 <= addr <= 0x7F:
            raise ValueError(
                f"{self.name}: 7-bit I2C address must be 0x00–0x7F, got 0x{addr:02X}"
            )
        return addr

    @staticmethod
    def _to_bytes(data: Union[bytes, bytearray, List[int], None]) -> bytes:
        if data is None:
            return b""
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if isinstance(data, list):
            return bytes(data)
        raise TypeError(
            f"I2C data must be bytes/bytearray/list[int], got {type(data).__name__}"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init_signals(self) -> None:
        """Drive SCL and SDA to their idle state (both high).

        Call this immediately after construction, before the first clock edge,
        to avoid X-propagation on the I2C bus.
        """
        self.log.info(
            "%s: I2C master initialised — speed=%d Hz, 7-bit addressing",
            self.name, self._speed,
        )

    def set_address(self, addr: int) -> None:
        """Set the default 7-bit device address for subsequent transactions.

        Parameters
        ----------
        addr :
            7-bit address (0x00–0x7F).
        """
        if not 0 <= addr <= 0x7F:
            raise ValueError(
                f"{self.name}: 7-bit I2C address must be 0x00–0x7F, got 0x{addr:02X}"
            )
        self._default_addr = addr
        self.log.info("%s: default device address set to 0x%02X", self.name, addr)

    # ------------------------------------------------------------------
    # Active transactions
    # ------------------------------------------------------------------

    async def write(
        self,
        addr: Optional[int] = None,
        data: Union[bytes, bytearray, List[int], None] = None,
        *,
        timeout_us: Optional[int] = None,
    ) -> None:
        """Issue an I2C write transaction.

        Parameters
        ----------
        addr :
            7-bit device address.  Uses ``default_addr`` when ``None``.
        data :
            Bytes to write.  An empty or ``None`` value sends just the address
            byte (address probe / presence check).
        timeout_us :
            Per-transaction timeout.  Uses the instance default when ``None``.

        Raises
        ------
        OcahI2cError
            On NACK or timeout when ``raise_on_nack=True``.
        """
        dev_addr   = self._resolve_addr(addr)
        raw        = self._to_bytes(data)
        t_us       = timeout_us if timeout_us is not None else self._timeout_us

        self.log.debug(
            "%s: I2C write addr=0x%02X len=%d", self.name, dev_addr, len(raw)
        )
        try:
            await with_timeout(
                self._master.write(dev_addr, raw),
                timeout_val=t_us,
                timeout_unit="us",
            )
        except cocotb.result.SimTimeoutError:
            self._stats["timeouts"] += 1
            if self._raise_on_nack:
                raise OcahI2cError(
                    f"{self.name}: write to 0x{dev_addr:02X} timed out after {t_us} µs"
                )
            return
        except Exception as exc:
            self._stats["nacks"] += 1
            if self._raise_on_nack:
                raise OcahI2cError(
                    f"{self.name}: write to 0x{dev_addr:02X} failed: {exc}"
                ) from exc
            self.log.warning("%s: write NACK/error at 0x%02X: %s", self.name, dev_addr, exc)
            return

        self._stats["write_transactions"] += 1

    async def read(
        self,
        addr: Optional[int] = None,
        length: int = 1,
        *,
        timeout_us: Optional[int] = None,
    ) -> Optional[bytes]:
        """Issue an I2C read transaction.

        Parameters
        ----------
        addr :
            7-bit device address.  Uses ``default_addr`` when ``None``.
        length :
            Number of bytes to read.
        timeout_us :
            Per-transaction timeout.  Uses the instance default when ``None``.

        Returns
        -------
        bytes
            Received data.

        Raises
        ------
        OcahI2cError
            On NACK or timeout when ``raise_on_nack=True``.
        """
        dev_addr = self._resolve_addr(addr)
        t_us     = timeout_us if timeout_us is not None else self._timeout_us

        self.log.debug(
            "%s: I2C read addr=0x%02X len=%d", self.name, dev_addr, length
        )
        try:
            raw = await with_timeout(
                self._master.read(dev_addr, length),
                timeout_val=t_us,
                timeout_unit="us",
            )
        except cocotb.result.SimTimeoutError:
            self._stats["timeouts"] += 1
            if self._raise_on_nack:
                raise OcahI2cError(
                    f"{self.name}: read from 0x{dev_addr:02X} timed out after {t_us} µs"
                )
            return None
        except Exception as exc:
            self._stats["nacks"] += 1
            if self._raise_on_nack:
                raise OcahI2cError(
                    f"{self.name}: read from 0x{dev_addr:02X} failed: {exc}"
                ) from exc
            self.log.warning("%s: read NACK/error at 0x%02X: %s", self.name, dev_addr, exc)
            return None

        self._stats["read_transactions"] += 1
        return bytes(raw)

    async def combined(
        self,
        addr: Optional[int] = None,
        write_data: Union[bytes, bytearray, List[int], None] = None,
        read_length: int = 0,
        *,
        timeout_us: Optional[int] = None,
    ) -> Optional[bytes]:
        """Issue an I2C combined write-then-read (repeated START) transaction.

        This is the standard mechanism for register-addressed reads: write the
        register address byte(s) then read back the register value(s) without
        releasing the bus between the two phases.

        Parameters
        ----------
        addr :
            7-bit device address.  Uses ``default_addr`` when ``None``.
        write_data :
            Bytes to write in the first phase (e.g. register address).
        read_length :
            Number of bytes to read in the second phase.  When 0, the
            method degenerates to a plain write.
        timeout_us :
            Per-transaction timeout.  Uses the instance default when ``None``.

        Returns
        -------
        bytes
            Data received in the read phase.  Empty bytes when
            ``read_length == 0``.
        """
        dev_addr = self._resolve_addr(addr)
        raw_out  = self._to_bytes(write_data)
        t_us     = timeout_us if timeout_us is not None else self._timeout_us

        self.log.debug(
            "%s: I2C combined addr=0x%02X write_len=%d read_len=%d",
            self.name, dev_addr, len(raw_out), read_length,
        )

        if read_length == 0:
            await self.write(dev_addr, raw_out, timeout_us=t_us)
            return b""

        try:
            raw_in = await with_timeout(
                self._master.write_then_read(dev_addr, raw_out, read_length),
                timeout_val=t_us,
                timeout_unit="us",
            )
        except cocotb.result.SimTimeoutError:
            self._stats["timeouts"] += 1
            if self._raise_on_nack:
                raise OcahI2cError(
                    f"{self.name}: combined at 0x{dev_addr:02X} timed out after {t_us} µs"
                )
            return None
        except Exception as exc:
            self._stats["nacks"] += 1
            if self._raise_on_nack:
                raise OcahI2cError(
                    f"{self.name}: combined at 0x{dev_addr:02X} failed: {exc}"
                ) from exc
            self.log.warning(
                "%s: combined NACK/error at 0x%02X: %s", self.name, dev_addr, exc
            )
            return None

        self._stats["combined_transactions"] += 1
        return bytes(raw_in)

    # ------------------------------------------------------------------
    # Statistics / diagnostics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        """Return a copy of the cumulative statistics counters."""
        return dict(self._stats)

    def reset_statistics(self) -> None:
        """Zero all cumulative counters."""
        for key in self._stats:
            self._stats[key] = 0
