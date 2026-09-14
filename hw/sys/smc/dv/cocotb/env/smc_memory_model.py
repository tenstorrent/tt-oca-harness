# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OSS SMC testcase memory model.

This model is testbench-local. It does not backdoor into DUT
hierarchy and does not replace the SMC SRAM/ROM RTL. Tests use it as a
deterministic golden/reference store for data they drive through public AXI or
protocol VIP paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

SMC_SPM_MEMORY_BASE = 0xC006_0000
SMC_SPM_MEMORY_SIZE = 0x0010_0000

# SMC firmware loaders reset the CPU to 0xC004_0000; this named region models
# the front-port boot/SPM aperture explicitly.
SMC_FRONT_PORT_SPM_BASE = 0xC004_0000
SMC_FRONT_PORT_SPM_SIZE = 0x0012_0000


@dataclass
class SmcMemoryRegion:
    """Sparse byte-addressable memory region."""

    name: str
    base: int
    size: int
    default: int = 0
    _bytes: dict[int, int] = field(default_factory=dict)

    @property
    def end(self) -> int:
        return self.base + self.size

    def contains(self, addr: int, length: int = 1) -> bool:
        return self.base <= addr and addr + length <= self.end

    def _offset(self, addr: int, length: int = 1) -> int:
        if not self.contains(addr, length):
            raise ValueError(
                f"{self.name}: address range 0x{addr:x}..0x{addr + length - 1:x} "
                f"is outside 0x{self.base:x}..0x{self.end - 1:x}"
            )
        return addr - self.base

    def clear(self) -> None:
        self._bytes.clear()

    def write(self, addr: int, data: bytes | bytearray | Iterable[int]) -> None:
        payload = bytes(data)
        offset = self._offset(addr, len(payload))
        for index, value in enumerate(payload):
            self._bytes[offset + index] = value

    def read(self, addr: int, length: int) -> bytes:
        offset = self._offset(addr, length)
        return bytes(self._bytes.get(offset + index, self.default) for index in range(length))

    def write_int(self, addr: int, value: int, length: int = 4, byteorder: str = "little") -> None:
        self.write(addr, int(value).to_bytes(length, byteorder))

    def read_int(self, addr: int, length: int = 4, byteorder: str = "little") -> int:
        return int.from_bytes(self.read(addr, length), byteorder)

    def load_file(self, path: str | Path, addr: int | None = None) -> int:
        data = Path(path).read_bytes()
        self.write(self.base if addr is None else addr, data)
        return len(data)

    def load_hex_words(
        self,
        path: str | Path,
        addr: int | None = None,
        word_bytes: int = 8,
        byteorder: str = "little",
    ) -> int:
        """Load a simple readmemh-style word file.

        Blank lines and // comments are ignored. Each non-empty line is parsed
        as one hexadecimal word and packed into the modeled memory using the
        requested byte order.
        """
        write_addr = self.base if addr is None else addr
        count = 0
        with Path(path).open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.split("//", 1)[0].strip()
                if not line:
                    continue
                value = int(line.replace("_", ""), 16)
                self.write_int(write_addr + count * word_bytes, value, word_bytes, byteorder)
                count += 1
        return count

    def expect(self, addr: int, expected: bytes | bytearray | Iterable[int]) -> None:
        expected_bytes = bytes(expected)
        actual = self.read(addr, len(expected_bytes))
        assert actual == expected_bytes, (
            f"{self.name}: memory mismatch at 0x{addr:x}: "
            f"got {actual.hex()}, expected {expected_bytes.hex()}"
        )


class SmcMemoryModel:
    """Named OSS SMC testcase memory model."""

    def __init__(self) -> None:
        self.regions: dict[str, SmcMemoryRegion] = {}
        self.add_region("spm_memory", SMC_SPM_MEMORY_BASE, SMC_SPM_MEMORY_SIZE)
        self.add_region("front_port_spm", SMC_FRONT_PORT_SPM_BASE, SMC_FRONT_PORT_SPM_SIZE)

    def add_region(self, name: str, base: int, size: int, default: int = 0) -> SmcMemoryRegion:
        if name in self.regions:
            raise ValueError(f"duplicate memory region {name}")
        region = SmcMemoryRegion(name=name, base=base, size=size, default=default & 0xFF)
        self.regions[name] = region
        return region

    def region(self, name: str) -> SmcMemoryRegion:
        return self.regions[name]

    def resolve(self, addr: int, length: int = 1, region: str | None = None) -> SmcMemoryRegion:
        if region is not None:
            selected = self.region(region)
            selected._offset(addr, length)
            return selected
        matches = [item for item in self.regions.values() if item.contains(addr, length)]
        if not matches:
            raise ValueError(f"no SMC memory region covers 0x{addr:x}+0x{length:x}")
        if len(matches) > 1:
            names = ", ".join(item.name for item in matches)
            raise ValueError(
                f"address 0x{addr:x}+0x{length:x} matches multiple regions: {names}; "
                "pass region=... to disambiguate"
            )
        return matches[0]

    def find_region(
        self, addr: int, length: int = 1, region: str | None = None
    ) -> SmcMemoryRegion | None:
        """Return the covering region, or None if the address is unmodeled."""
        try:
            return self.resolve(addr, length, region)
        except ValueError:
            return None

    def clear(self, region: str | None = None) -> None:
        if region is not None:
            self.region(region).clear()
            return
        for item in self.regions.values():
            item.clear()

    def write(
        self, addr: int, data: bytes | bytearray | Iterable[int], region: str | None = None
    ) -> None:
        payload = bytes(data)
        self.resolve(addr, len(payload), region).write(addr, payload)

    def read(self, addr: int, length: int, region: str | None = None) -> bytes:
        return self.resolve(addr, length, region).read(addr, length)

    def write_int(
        self,
        addr: int,
        value: int,
        length: int = 4,
        byteorder: str = "little",
        region: str | None = None,
    ) -> None:
        self.resolve(addr, length, region).write_int(addr, value, length, byteorder)

    def read_int(
        self, addr: int, length: int = 4, byteorder: str = "little", region: str | None = None
    ) -> int:
        return self.resolve(addr, length, region).read_int(addr, length, byteorder)

    def load_file(self, path: str | Path, addr: int, region: str | None = None) -> int:
        size = Path(path).stat().st_size
        return self.resolve(addr, size, region).load_file(path, addr)

    def load_hex_words(
        self,
        path: str | Path,
        addr: int,
        word_bytes: int = 8,
        byteorder: str = "little",
        region: str | None = None,
    ) -> int:
        selected = self.resolve(addr, 1, region)
        return selected.load_hex_words(path, addr, word_bytes, byteorder)

    def expect(
        self, addr: int, expected: bytes | bytearray | Iterable[int], region: str | None = None
    ) -> None:
        expected_bytes = bytes(expected)
        self.resolve(addr, len(expected_bytes), region).expect(addr, expected_bytes)

    def expect_int(
        self,
        addr: int,
        expected: int,
        length: int = 4,
        byteorder: str = "little",
        region: str | None = None,
    ) -> None:
        actual = self.read_int(addr, length, byteorder, region)
        assert actual == expected, (
            f"SMC memory mismatch at 0x{addr:x}: "
            f"got 0x{actual:0{length * 2}x}, expected 0x{expected:0{length * 2}x}"
        )
