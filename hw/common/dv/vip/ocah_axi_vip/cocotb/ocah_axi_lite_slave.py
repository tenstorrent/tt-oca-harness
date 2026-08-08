# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""OCAH-stable AXI4-Lite memory-backed subordinate wrapper."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from cocotbext.axi import AxiLiteBus

from .ocah_axi_fault import OcahFaultAxiLiteRam as _OcahFaultAxiLiteRamBackend

__all__ = ["OcahAxiLiteSlave", "OcahAxiLiteRam", "OcahFaultAxiLiteRam"]


class OcahAxiLiteSlave:
    """AXI4-Lite memory-backed responder with deterministic fault controls."""

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        *,
        name: str = "OcahAxiLiteSlave",
        reset_active_level: bool = False,
        size: int = 2**20,
        mem=None,
        prefix: str | None = None,
        data_width: int = 32,
        strb_width: int = 0,
        **kwargs: Any,
    ) -> None:
        del strb_width
        self.name = name
        self.size = size
        self.data_width = data_width
        self.log = logging.getLogger(name)
        axil_bus = AxiLiteBus.from_prefix(bus, prefix) if prefix else self._coerce_bus(bus)
        self._ram = _OcahFaultAxiLiteRamBackend(
            axil_bus,
            clock,
            reset,
            reset_active_level=reset_active_level,
            size=size,
            mem=mem,
            name=name,
            **kwargs,
        )
        self.log.info("%s: AXI-Lite RAM responder ready (%d bytes)", self.name, self.size)

    @classmethod
    def from_prefix(
        cls,
        dut,
        prefix: str,
        clock,
        reset=None,
        *,
        name: str = "OcahAxiLiteSlave",
        reset_active_level: bool = False,
        size: int = 2**20,
        mem=None,
        data_width: int = 32,
        strb_width: int = 0,
        **kwargs: Any,
    ) -> "OcahAxiLiteSlave":
        """Construct from flattened AXI4-Lite signals using ``AxiLiteBus``."""
        return cls(
            dut,
            clock,
            reset,
            name=name,
            reset_active_level=reset_active_level,
            size=size,
            mem=mem,
            prefix=prefix,
            data_width=data_width,
            strb_width=strb_width,
            **kwargs,
        )

    @staticmethod
    def _coerce_bus(bus):
        if isinstance(bus, AxiLiteBus):
            return bus
        return AxiLiteBus.from_entity(bus)

    @property
    def backend(self):
        """Return the underlying cocotbext-backed RAM for advanced debug only."""
        return self._ram

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


OcahAxiLiteRam = OcahAxiLiteSlave
OcahFaultAxiLiteRam = OcahAxiLiteSlave
