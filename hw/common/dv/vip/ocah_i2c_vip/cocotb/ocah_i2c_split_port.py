# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Split-port open-drain I2C adapters for OCAH cocotb TBs.

Some OCAH testbenches (notably SMC OSS) expose I2C pads as:

* ``sda`` / ``scl`` — resolved bus levels (cocotb reads)
* ``sda_o`` / ``scl_o`` (often named ``*_ext_low``) — TB drive inputs where
  ``1`` pulls the line low and ``0`` releases it

``cocotbext-i2c`` uses the opposite drive polarity on ``sda_o`` / ``scl_o``
(``0`` = pull low, ``1`` = release). These helpers invert polarity and
implement per-bus wired-AND so multiple cocotbext entities (master / slave /
monitor) can share one split-port bus without racing independent drive writes.

Public API
----------
OcahI2cSplitPortMaster(sda, sda_o, scl, scl_o, *, speed, name)
OcahI2cSplitPortMemory(sda, sda_o, scl, scl_o, *, addr, size, name)
OcahI2cSplitPortMonitor(sda, sda_o, scl, scl_o, *, name)
"""

from __future__ import annotations

import logging
from typing import List

from cocotb.triggers import Event

from .ocah_i2c_master import OcahI2cImportError, _COCOTBEXT_I2C_AVAILABLE

__all__ = [
    "OcahI2cSplitPortMaster",
    "OcahI2cSplitPortMemory",
    "OcahI2cSplitPortMonitor",
    "OcahI2cSplitPortError",
]

try:
    from cocotbext.i2c import I2cMaster as _I2cMaster
    from cocotbext.i2c import I2cMemory as _I2cMemory
    from cocotbext.i2c.i2c_device import I2cDevice as _I2cDevice
except ImportError:  # pragma: no cover
    _I2cMaster = object  # type: ignore[misc, assignment]
    _I2cMemory = object  # type: ignore[misc, assignment]
    _I2cDevice = object  # type: ignore[misc, assignment]


class OcahI2cSplitPortError(RuntimeError):
    """Raised when split-port I2C VIP wiring or usage is invalid."""


# Per-bus wired-AND vote sets keyed by id(drive_handle). Multiple cocotbext
# entities on the same ext_low net OR their pull-low requests together.
_SDA_LOW_DRIVERS: dict[int, set[int]] = {}
_SCL_LOW_DRIVERS: dict[int, set[int]] = {}


def _release_ext_low_idle(entity) -> None:
    """Force split-port drive nets to released after cocotbext parent init.

    ``cocotbext-i2c`` writes ``sda_o/scl_o.setimmediatevalue(1)`` (= released
    in its convention). On OCAH ``ext_low`` pads that means pull-low, so both
    lines would be held low from time zero without this correction.
    """
    if getattr(entity, "sda_o", None) is not None:
        entity.sda_o.setimmediatevalue(0)
    if getattr(entity, "scl_o", None) is not None:
        entity.scl_o.setimmediatevalue(0)


class _OcahI2cSplitPortMixin:
    """Invert polarity + per-bus wired-AND for split-port ``ext_low`` inputs."""

    def _set_sda(self, val):  # type: ignore[override]
        sda_o = getattr(self, "sda_o", None)
        if sda_o is None:
            self.sda.value = val
            return
        bus_key = id(sda_o)
        drivers = _SDA_LOW_DRIVERS.setdefault(bus_key, set())
        if bool(val):
            drivers.discard(id(self))
        else:
            drivers.add(id(self))
        sda_o.value = 1 if drivers else 0

    def _set_scl(self, val):  # type: ignore[override]
        scl_o = getattr(self, "scl_o", None)
        if scl_o is None:
            self.scl.value = val
            return
        bus_key = id(scl_o)
        drivers = _SCL_LOW_DRIVERS.setdefault(bus_key, set())
        if bool(val):
            drivers.discard(id(self))
        else:
            drivers.add(id(self))
        scl_o.value = 1 if drivers else 0


if _COCOTBEXT_I2C_AVAILABLE:

    class OcahI2cSplitPortMemory(_OcahI2cSplitPortMixin, _I2cMemory):
        """EEPROM-style I2C slave for split-port open-drain TBs."""

        def __init__(
            self,
            sda,
            sda_o,
            scl,
            scl_o,
            *,
            addr: int = 0x50,
            size: int = 256,
            name: str = "OcahI2cSplitPortMemory",
        ) -> None:
            if not _COCOTBEXT_I2C_AVAILABLE:
                raise OcahI2cImportError()
            super().__init__(
                sda=sda,
                sda_o=sda_o,
                scl=scl,
                scl_o=scl_o,
                addr=addr,
                size=size,
            )
            _release_ext_low_idle(self)
            self.log = logging.getLogger(name)
            self.log.info("%s bound: addr=0x%02X size=%d", name, addr, size)

        def preload(self, data: bytes) -> None:
            length = min(len(data), len(self.mem))
            for i in range(length):
                self.mem[i] = data[i]
            self.log.info("preload: %d bytes", length)

        def read_mem(self, offset: int, length: int) -> bytes:
            return bytes(self.mem[offset : offset + length])

        def write_mem(self, offset: int, data: bytes) -> None:
            for i, b in enumerate(data):
                self.mem[offset + i] = b

    class OcahI2cSplitPortMonitor(_OcahI2cSplitPortMixin, _I2cDevice):
        """Passive I2C observer on a split-port bus (never ACKs)."""

        _MONITOR_ADDR = 0x7F

        def __init__(
            self,
            sda,
            sda_o,
            scl,
            scl_o,
            *,
            name: str = "OcahI2cSplitPortMonitor",
        ) -> None:
            if not _COCOTBEXT_I2C_AVAILABLE:
                raise OcahI2cImportError()
            super().__init__(sda=sda, sda_o=sda_o, scl=scl, scl_o=scl_o)
            self.addr = self._MONITOR_ADDR
            _release_ext_low_idle(self)
            self.log = logging.getLogger(name)
            self.started = Event()
            self.stopped = Event()
            self.transactions: List[dict] = []

        def handle_start(self) -> None:
            self.log.info("bus START observed")
            if not self.started.is_set():
                self.started.set()

        async def handle_write(self, data):
            self.log.info("bus write byte 0x%02X", data)
            self.transactions.append({"rw": "W", "data": int(data)})

        async def handle_read(self):
            self.log.info("bus read request (returning 0xFF)")
            self.transactions.append({"rw": "R"})
            return 0xFF

        def handle_stop(self) -> None:
            self.log.info("bus STOP observed")
            self.stopped.set()

    class OcahI2cSplitPortMaster(_OcahI2cSplitPortMixin, _I2cMaster):
        """Active I2C master for split-port open-drain TBs."""

        def __init__(
            self,
            sda,
            sda_o,
            scl,
            scl_o,
            *,
            speed: int = 100_000,
            name: str = "OcahI2cSplitPortMaster",
        ) -> None:
            if not _COCOTBEXT_I2C_AVAILABLE:
                raise OcahI2cImportError()
            super().__init__(
                sda=sda,
                sda_o=sda_o,
                scl=scl,
                scl_o=scl_o,
                speed=speed,
            )
            _release_ext_low_idle(self)
            self.log = logging.getLogger(name)
            self.log.info("%s bound: speed=%d Hz", name, speed)

else:  # pragma: no cover

    class OcahI2cSplitPortMemory:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise OcahI2cImportError()

    class OcahI2cSplitPortMonitor:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise OcahI2cImportError()

    class OcahI2cSplitPortMaster:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise OcahI2cImportError()
