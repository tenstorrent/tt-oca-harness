# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4 slave sequence API: the test-facing surface of the responder.

`OcahAxiSlaveSequence` wraps one `OcahAxiSlaveDriver` and provides the
backdoor memory access, deterministic fault injection, bounded backpressure,
write order, response USER, response delay and outstanding-occupancy
controls tests consume. Tests configure and inspect the responder through
this class (or the agent's ``sequence``), never through the raw driver;
missing operations get added here first.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .ocah_axi_slave_driver import OcahAxiSlaveDriver

__all__ = ["OcahAxiSlaveSequence"]


class OcahAxiSlaveSequence:
    """Backdoor and fault-control operations over one AXI4 responder driver."""

    def __init__(self, driver: OcahAxiSlaveDriver, *, name: str | None = None) -> None:
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

    def inject_id_corruption(
        self, *, mask: int = 0x1, read: bool = True, write: bool = True
    ) -> None:
        """Arm one-shot response-ID corruption (BID/RID XOR ``mask``)."""
        self.driver.inject_id_corruption(mask=mask, read=read, write=write)

    def clear_errors(self) -> None:
        """Clear all programmed one-shot response errors and ID corruption."""
        self.driver.clear_errors()

    def enable_backpressure(self, *, channels: Iterable[str], stall_cycles: int) -> None:
        """Apply bounded READY stalls on selected channels."""
        self.driver.enable_backpressure(channels=channels, stall_cycles=stall_cycles)

    def disable_backpressure(self) -> None:
        """Clear all READY stall generators."""
        self.driver.disable_backpressure()

    @property
    def max_outstanding(self) -> int | None:
        """Outstanding depth per direction, or ``None`` for one request served at a time."""
        return self.driver.max_outstanding

    def set_response_delay(
        self, delays: int | Iterable[int], *, read: bool = True, write: bool = True
    ) -> None:
        """Delay each B or R response by the next value of ``delays`` cycles."""
        self.driver.set_response_delay(delays, read=read, write=write)

    def clear_response_delay(self) -> None:
        """Send every response as soon as it is ready."""
        self.driver.clear_response_delay()

    def outstanding_peak(self) -> dict[str, int]:
        """Most write and read transactions outstanding at once (``max_outstanding`` set)."""
        return self.driver.outstanding_peak()

    def arm_w_before_aw(self) -> None:
        """Arm a one-shot W-before-AW order: the next write's first W beat is accepted while its AW waits."""
        self.driver.arm_w_before_aw()

    def randomize_resp_user(self, seed: int) -> None:
        """Answer every later B and R beat with BUSER and RUSER drawn per beat from ``seed``."""
        self.driver.randomize_resp_user(seed)

    def get_statistics(self) -> dict[str, int]:
        """Return wrapper-level static statistics."""
        return {
            "size": self.size,
            "write_error_count": len(self.driver.write_errors),
            "read_error_count": len(self.driver.read_errors),
        }
