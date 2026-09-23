# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Test-facing flash operations over one SPI controller engine.

``OcahSpiMasterSequence`` is the surface a test or DUT sequence drives the
master VIP through: the baseline command set as plain-value operations, one
``raw_command`` for out-of-scope probes, and a record of every response the
controller received so the checker can pair it with what the device sent
(``check_host_responses``). Operation names and argument order match
``OcahSpiMasterBfm``.

The sequence has no SV-UVM twin: the package ships the cocotb realization only.
"""

from __future__ import annotations

from .ocah_spi_flash_checker import OcahSpiFlashChecker
from .ocah_spi_master_bfm import OcahSpiMasterBfm
from .ocah_spi_types import OcahSpiOpcode

__all__ = ["OcahSpiMasterSequence"]


class OcahSpiMasterSequence:
    """Checked flash operations over one controller engine."""

    def __init__(self, bfm: OcahSpiMasterBfm, checker: OcahSpiFlashChecker | None = None) -> None:
        self.bfm = bfm
        self.checker = checker
        self._responses: dict[int, list[bytes]] = {}

    # ------------------------------------------------------------------
    # Baseline command set
    # ------------------------------------------------------------------

    async def jedec_id(self) -> int:
        """READ JEDEC ID as one integer; the three bytes are recorded for the host check."""
        value = await self.bfm.jedec_id()
        self._record(OcahSpiOpcode.JEDEC_ID, value.to_bytes(3, "big"))
        return value

    async def read_status1(self) -> int:
        value = await self.bfm.read_status1()
        self._record(OcahSpiOpcode.READ_SR1, bytes([value]))
        return value

    async def read_status2(self) -> int:
        value = await self.bfm.read_status2()
        self._record(OcahSpiOpcode.READ_SR2, bytes([value]))
        return value

    async def write_enable(self) -> None:
        await self.bfm.write_enable()

    async def write_disable(self) -> None:
        await self.bfm.write_disable()

    async def page_program(self, addr: int, data: bytes) -> None:
        await self.bfm.page_program(addr, data)

    async def sector_erase(self, addr: int) -> None:
        await self.bfm.sector_erase(addr)

    async def read(self, addr: int, length: int) -> bytes:
        data = await self.bfm.read(addr, length)
        self._record(OcahSpiOpcode.READ, data)
        return data

    async def fast_read(self, addr: int, length: int) -> bytes:
        data = await self.bfm.fast_read(addr, length)
        self._record(OcahSpiOpcode.FAST_READ, data)
        return data

    async def raw_command(
        self,
        opcode: int,
        *,
        addr: int | None = None,
        dummy_bytes: int = 0,
        tx: bytes = b"",
        rx_len: int = 0,
    ) -> bytes:
        """One frame of any opcode; the response is kept under that opcode."""
        data = await self.bfm.transfer(
            opcode, addr=addr, dummy_bytes=dummy_bytes, tx=tx, rx_len=rx_len
        )
        if rx_len:
            self._record(int(opcode), data)
        return data

    # ------------------------------------------------------------------
    # Host-side observations
    # ------------------------------------------------------------------

    def responses(self, opcode: int) -> list[bytes]:
        """Every response the controller received for ``opcode``, in order."""
        return list(self._responses.get(int(opcode), []))

    def check_host_responses(self) -> None:
        """Pair every recorded response with the device's record through the checker."""
        if self.checker is None:
            raise ValueError("check_host_responses() needs a checker")
        for opcode, observed in self._responses.items():
            self.checker.check_host_responses(opcode, observed)

    def _record(self, opcode: int, data: bytes) -> None:
        self._responses.setdefault(int(opcode), []).append(bytes(data))
