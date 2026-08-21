# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCAH-stable APB memory-backed subordinate wrapper."""

from __future__ import annotations

import logging
from typing import Any

from cocotbext.axi import ApbBus, ApbSlave
from cocotbext.axi.memory import Memory

RESP_SLVERR = 2


class _OcahApbMemoryTarget:
    """Async target object consumed by cocotbext ``ApbSlave``."""

    def __init__(self, size: int, mem=None) -> None:
        self.memory = Memory(size, mem)
        self.write_errors: set[int] = set()
        self.read_errors: set[int] = set()

    async def read(self, address: int, length: int) -> bytes:
        if int(address) in self.read_errors:
            self.read_errors.remove(int(address))
            raise RuntimeError(f"injected APB read error at 0x{int(address):x}")
        return bytes(self.memory.read(int(address), int(length)))

    async def write(self, address: int, data: bytes | bytearray) -> None:
        if int(address) in self.write_errors:
            self.write_errors.remove(int(address))
            raise RuntimeError(f"injected APB write error at 0x{int(address):x}")
        self.memory.write(int(address), bytes(data))


class OcahApbSlave:
    """APB memory-backed responder with deterministic PSLVERR injection."""

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        *,
        name: str = "OcahApbSlave",
        reset_active_level: bool = False,
        size: int = 2**20,
        mem=None,
        prefix: str | None = None,
        data_width: int = 32,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.size = size
        self.data_width = data_width
        self.log = logging.getLogger(name)
        apb_bus = ApbBus.from_prefix(bus, prefix) if prefix else self._coerce_bus(bus)
        self._target = _OcahApbMemoryTarget(size, mem)
        self._slave = ApbSlave(
            apb_bus,
            clock,
            reset,
            target=self._target,
            reset_active_level=reset_active_level,
            **kwargs,
        )
        self.log.info("%s: APB RAM responder ready (%d bytes)", self.name, self.size)

    @classmethod
    def from_prefix(
        cls,
        dut,
        prefix: str,
        clock,
        reset=None,
        *,
        name: str = "OcahApbSlave",
        reset_active_level: bool = False,
        size: int = 2**20,
        mem=None,
        data_width: int = 32,
        **kwargs: Any,
    ) -> "OcahApbSlave":
        """Construct from flattened APB signals using ``ApbBus``."""
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
            **kwargs,
        )

    @staticmethod
    def _coerce_bus(bus):
        if isinstance(bus, ApbBus):
            return bus
        return ApbBus.from_entity(bus)

    @property
    def backend(self):
        """Return the underlying cocotbext APB slave for advanced debug only."""
        return self._slave

    def read(self, addr: int, length: int) -> bytes:
        """Backdoor-read ``length`` bytes starting at ``addr``."""
        return bytes(self._target.memory.read(int(addr), int(length)))

    def write(self, addr: int, data: bytes | bytearray | list[int]) -> None:
        """Backdoor-write bytes starting at ``addr``."""
        self._target.memory.write(int(addr), bytes(data))

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

    def inject_error(self, addr: int, resp: int = RESP_SLVERR, *, read: bool = True, write: bool = True) -> None:
        """Program a one-shot PSLVERR at ``addr``."""
        if int(resp) != RESP_SLVERR:
            raise ValueError("APB supports only OKAY or PSLVERR; use RESP_SLVERR for errors")
        aligned = int(addr)
        if read:
            self._target.read_errors.add(aligned)
        if write:
            self._target.write_errors.add(aligned)
        self.log.info("Injecting APB PSLVERR addr=0x%08x read=%d write=%d", aligned, read, write)

    def clear_errors(self) -> None:
        """Clear all programmed one-shot PSLVERR injections."""
        self._target.read_errors.clear()
        self._target.write_errors.clear()

    def enable_backpressure(self, *, stall_cycles: int) -> None:
        """Apply bounded PREADY stalls through the cocotbext pause generator."""
        self._slave.set_pause_generator(self._pause_pattern(stall_cycles))

    def disable_backpressure(self) -> None:
        """Clear PREADY stall generation."""
        self._slave.clear_pause_generator()
        self._slave.pause = False

    @staticmethod
    def _pause_pattern(stall_cycles: int):
        while True:
            for _ in range(max(int(stall_cycles), 0)):
                yield True
            yield False

    def get_statistics(self) -> dict[str, int]:
        """Return wrapper-level static statistics."""
        return {
            "size": self.size,
            "read_error_count": len(self._target.read_errors),
            "write_error_count": len(self._target.write_errors),
        }


OcahApbRam = OcahApbSlave
