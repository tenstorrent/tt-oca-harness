# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4-Lite slave sequence API: the test-facing surface of the responder.

`OcahAxiLiteSlaveSequence` wraps one `OcahAxiLiteSlaveDriver` and provides
the backdoor memory access, deterministic fault injection, and bounded
backpressure controls tests consume. Tests configure and inspect the
responder through this class (or the agent's ``sequence``), never through the
raw driver; missing operations get added here first.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .ocah_axi_lite_slave_driver import OcahAxiLiteSlaveDriver

__all__ = ["OcahAxiLiteSlaveSequence"]


class OcahAxiLiteSlaveSequence:
    """Backdoor and fault-control operations over one AXI4-Lite responder driver."""

    def __init__(self, driver: OcahAxiLiteSlaveDriver, *, name: str | None = None) -> None:
        self.driver = driver
        self.name = name if name is not None else driver.log.name
        self.size = driver.size

    @property
    def log(self):
        return self.driver.log

    @property
    def backend(self):
        """Return the underlying cocotbext-backed RAM for advanced debug only."""
        return self.driver

    def start(self) -> None:
        """No-op: cocotbext responders start at construction."""

    def read(self, addr: int, length: int) -> bytes:
        """Backdoor-read ``length`` bytes starting at ``addr``."""
        return bytes(self.driver.read(int(addr), int(length)))

    def write(self, addr: int, data: bytes | bytearray | list[int]) -> None:
        """Backdoor-write bytes starting at ``addr``."""
        self.driver.write(int(addr), bytes(data))

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
            chunk = data[off : off + width]
            lines.append(f"{addr + off:08x}: " + " ".join(f"{byte:02x}" for byte in chunk))
        return "\n".join(lines)

    def inject_error(
        self, addr: int, resp: int, *, read: bool = True, write: bool = True, rdata: int = 0
    ) -> None:
        """Program a one-shot non-OKAY response at ``addr``; the errored read beat answers ``rdata``."""
        self.driver.inject_error(addr, resp, read=read, write=write, rdata=rdata)

    def clear_errors(self) -> None:
        """Clear all programmed one-shot response errors."""
        self.driver.clear_errors()

    def enable_backpressure(self, *, channels: Iterable[str], stall_cycles: int) -> None:
        """Apply bounded READY stalls on selected channels."""
        self.driver.enable_backpressure(channels=channels, stall_cycles=stall_cycles)

    def disable_backpressure(self) -> None:
        """Clear all READY stall generators."""
        self.driver.disable_backpressure()

    def arm_w_before_aw(self) -> None:
        """Arm a one-shot W-before-AW order: the next write's first W beat is accepted while its AW waits."""
        self.driver.arm_w_before_aw()

    def get_statistics(self) -> dict[str, int]:
        """Return wrapper-level static statistics."""
        return {
            "size": self.size,
            "write_error_count": len(self.driver.write_errors),
            "read_error_count": len(self.driver.read_errors),
        }
