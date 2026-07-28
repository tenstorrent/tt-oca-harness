# SPDX-License-Identifier: Apache-2.0
"""DTP compatibility names for shared OCAH fault-capable AXI responders."""

from __future__ import annotations

from collections.abc import Iterable

from ocah_axi_vip import OcahFaultAxiLiteRam


class DtpFaultAxiLiteRam(OcahFaultAxiLiteRam):
    """DTP-local alias kept for existing JTAG2AXI environment imports."""


class DtpFaultOcahAxiRam:
    """Adapter that exposes the DTP fault API through public OCAH RAM methods."""

    def __init__(self, ram) -> None:
        self.ram = ram

    def __getattr__(self, name):
        return getattr(self.ram, name)

    def read(self, addr: int, length: int) -> bytes:
        return self.ram.read(addr, length)

    def write(self, addr: int, data: bytes | bytearray | list[int]) -> None:
        self.ram.write(addr, data)

    def inject_error(self, addr: int, resp: int, *, read: bool = True, write: bool = True) -> None:
        self.ram.inject_error(addr, resp, read=read, write=write)

    def clear_errors(self) -> None:
        self.ram.clear_errors()

    def enable_backpressure(self, *, channels: Iterable[str], stall_cycles: int) -> None:
        self.ram.enable_backpressure(channels=channels, stall_cycles=stall_cycles)

    def disable_backpressure(self) -> None:
        self.ram.disable_backpressure()
