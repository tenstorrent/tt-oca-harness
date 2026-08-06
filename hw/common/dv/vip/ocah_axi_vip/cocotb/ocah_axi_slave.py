# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""OCAH-stable AXI4 memory-backed subordinate wrapper."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from cocotbext.axi import AxiBus

from .ocah_axi_fault import OcahFaultAxiRamBackend

__all__ = [
    "OcahAxiSlave",
    "OcahAxiRam",
    "OcahFaultAxiRam",
    "OcahAxiSlaveImportError",
]


class OcahAxiSlaveImportError(ImportError):
    """Backward-compatible import error type retained for callers."""


class OcahAxiSlave:
    """OCAH-stable AXI4 memory-backed slave/responder.

    The responder is backed by ``cocotbext-axi`` and includes optional one-shot
    response injection plus bounded READY backpressure controls. The normal
    backdoor memory APIs continue to use only plain Python ints and bytes.
    """

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        *,
        name: str = "OcahAxiSlave",
        reset_active_level: bool = False,
        size: int = 2**20,
        mem=None,
        prefix: str | None = None,
        id_width: int = 0,
        addr_width: int = 0,
        data_width: int = 0,
        strb_width: int = 0,
        start: bool = True,
        **kwargs: Any,
    ) -> None:
        del id_width, addr_width, data_width, strb_width, start
        self.name = name
        self.size = size
        self.log = logging.getLogger(name)
        axi_bus = AxiBus.from_prefix(bus, prefix) if prefix else self._coerce_bus(bus)
        self._ram = OcahFaultAxiRamBackend(
            axi_bus,
            clock,
            reset,
            reset_active_level=reset_active_level,
            size=size,
            mem=mem,
            name=name,
            **kwargs,
        )
        self.log.info("%s: AXI RAM responder ready (%d bytes)", self.name, self.size)

    @classmethod
    def from_prefix(
        cls,
        dut,
        prefix: str,
        clock,
        reset=None,
        *,
        name: str = "OcahAxiSlave",
        reset_active_level: bool = False,
        size: int = 2**20,
        mem=None,
        id_width: int = 0,
        addr_width: int = 0,
        data_width: int = 0,
        strb_width: int = 0,
        **kwargs: Any,
    ) -> "OcahAxiSlave":
        """Construct from flattened AXI signals using ``AxiBus.from_prefix``."""
        return cls(
            dut,
            clock,
            reset,
            name=name,
            reset_active_level=reset_active_level,
            size=size,
            mem=mem,
            prefix=prefix,
            id_width=id_width,
            addr_width=addr_width,
            data_width=data_width,
            strb_width=strb_width,
            **kwargs,
        )

    @staticmethod
    def _coerce_bus(bus):
        if isinstance(bus, AxiBus):
            return bus
        return AxiBus.from_entity(bus)

    @property
    def backend(self):
        """Return the underlying cocotbext-backed RAM for advanced debug only."""
        return self._ram

    def start(self) -> None:
        """Compatibility no-op; cocotbext responders start at construction."""

    def read(self, addr: int, length: int) -> bytes:
        """Backdoor-read ``length`` bytes starting at ``addr``."""
        return bytes(self._ram.read(int(addr), int(length)))

    def write(self, addr: int, data: bytes | bytearray | list[int]) -> None:
        """Backdoor-write bytes starting at ``addr``."""
        self._ram.write(int(addr), bytes(data))

    def read_int(self, addr: int, size: int, *, byteorder: str = "little") -> int:
        """Backdoor-read an integer of ``size`` bytes."""
        return int.from_bytes(self.read(addr, size), byteorder)

    def write_int(self, addr: int, value: int, size: int, *, byteorder: str = "little") -> None:
        """Backdoor-write ``value`` as an integer of ``size`` bytes."""
        self.write(addr, int(value).to_bytes(size, byteorder))

    def read32(self, addr: int) -> int:
        """Little-endian 32-bit backdoor read."""
        return self.read_int(addr, 4)

    def write32(self, addr: int, value: int) -> None:
        """Little-endian 32-bit backdoor write."""
        self.write_int(addr, value, 4)

    def read64(self, addr: int) -> int:
        """Little-endian 64-bit backdoor read."""
        return self.read_int(addr, 8)

    def write64(self, addr: int, value: int) -> None:
        """Little-endian 64-bit backdoor write."""
        self.write_int(addr, value, 8)

    def hexdump(self, addr: int = 0, length: int = 256, **kwargs: Any) -> str:
        """Return a simple hexadecimal dump of the backdoor memory."""
        width = int(kwargs.get("width", 16))
        data = self.read(addr, length)
        lines = []
        for off in range(0, len(data), width):
            chunk = data[off:off + width]
            lines.append(f"{addr + off:08x}: " + " ".join(f"{byte:02x}" for byte in chunk))
        return "\n".join(lines)

    def inject_error(self, addr: int, resp: int, *, read: bool = True, write: bool = True) -> None:
        """Program a one-shot non-OKAY response at ``addr``."""
        self._ram.inject_error(addr, resp, read=read, write=write)

    def clear_errors(self) -> None:
        """Clear all programmed one-shot response errors."""
        self._ram.clear_errors()

    def enable_backpressure(self, *, channels: Iterable[str], stall_cycles: int) -> None:
        """Apply bounded READY stalls on selected channels."""
        self._ram.enable_backpressure(channels=channels, stall_cycles=stall_cycles)

    def disable_backpressure(self) -> None:
        """Clear all READY stall generators."""
        self._ram.disable_backpressure()

    def get_statistics(self) -> dict[str, int]:
        """Return wrapper-level static statistics."""
        return {
            "size": self.size,
            "write_error_count": len(self._ram.write_errors),
            "read_error_count": len(self._ram.read_errors),
        }


OcahAxiRam = OcahAxiSlave
OcahFaultAxiRam = OcahAxiSlave
