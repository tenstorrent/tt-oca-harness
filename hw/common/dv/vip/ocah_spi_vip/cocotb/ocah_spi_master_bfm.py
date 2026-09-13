# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Single-SPI Mode-0 controller engine for benches that have no SPI host IP.

``OcahSpiMasterBfm`` drives chip-select, clock, and MOSI and samples MISO on
the rising clock edge, one frame per command: opcode, optional address,
optional dummy bytes, payload bytes, then ``rx_len`` response bytes with MOSI
held low. It is the master-side twin of the ``OcahSpiFlash`` device and the
engine behind ``OcahSpiMasterSequence``. Non-UVM benches may use it directly;
tests go through the sequence.

The engine has no SV-UVM twin: the package ships the cocotb realization only.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from cocotb.triggers import Timer

from .ocah_spi_types import OcahSpiOpcode

__all__ = ["OcahSpiMasterBfm"]

_DEFAULT_HALF_PERIOD_NS = 10
_TIME_UNIT: Final = "ns"


class OcahSpiMasterBfm:
    """Bit-banging SPI controller: one chip-select frame per ``transfer``."""

    def __init__(
        self,
        cs_n: Any,
        sclk: Any,
        mosi: Any,
        miso: Any,
        *,
        name: str = "OcahSpiMasterBfm",
        half_period_ns: int = _DEFAULT_HALF_PERIOD_NS,
        addr_bytes: int = 3,
    ) -> None:
        self.name = name
        self.log = logging.getLogger(name)
        self._cs_n = cs_n
        self._sclk = sclk
        self._mosi = mosi
        self._miso = miso
        self.half_period_ns = half_period_ns
        self.addr_bytes = addr_bytes
        self.frames = 0
        self.bytes_tx = 0
        self.bytes_rx = 0

    @classmethod
    def from_prefix(cls, dut: Any, prefix: str, **kwargs: Any) -> OcahSpiMasterBfm:
        """Bind ``<prefix>_cs_n``, ``<prefix>_sclk``, ``<prefix>_mosi``, ``<prefix>_miso``."""
        return cls(
            getattr(dut, f"{prefix}_cs_n"),
            getattr(dut, f"{prefix}_sclk"),
            getattr(dut, f"{prefix}_mosi"),
            getattr(dut, f"{prefix}_miso"),
            **kwargs,
        )

    def init_signals(self) -> None:
        """Idle the bus: chip-select high, clock and MOSI low."""
        self._cs_n.value = 1
        self._sclk.value = 0
        self._mosi.value = 0

    # ------------------------------------------------------------------
    # Frame-level operation
    # ------------------------------------------------------------------

    async def transfer(
        self,
        opcode: int,
        *,
        addr: int | None = None,
        dummy_bytes: int = 0,
        tx: bytes = b"",
        rx_len: int = 0,
    ) -> bytes:
        """One frame: opcode, address, dummies, payload out, then ``rx_len`` bytes in."""
        header = bytearray([int(opcode) & 0xFF])
        if addr is not None:
            header += int(addr).to_bytes(self.addr_bytes, "big")
        header += bytes(dummy_bytes)
        header += bytes(tx)
        self._cs_n.value = 0
        await Timer(self.half_period_ns, _TIME_UNIT)
        for value in header:
            await self._shift_byte(value)
        received = bytearray()
        for _ in range(rx_len):
            received.append(await self._shift_byte(0))
        await Timer(self.half_period_ns, _TIME_UNIT)
        self._cs_n.value = 1
        await Timer(self.half_period_ns, _TIME_UNIT)
        self.frames += 1
        self.bytes_tx += len(header)
        self.bytes_rx += rx_len
        self.log.debug(
            "%s: frame opcode=0x%02x header=%d B rx=%d B", self.name, opcode, len(header), rx_len
        )
        return bytes(received)

    # ------------------------------------------------------------------
    # Baseline command set
    # ------------------------------------------------------------------

    async def jedec_id(self) -> int:
        """READ JEDEC ID; the three identifier bytes as one integer."""
        data = await self.transfer(OcahSpiOpcode.JEDEC_ID, rx_len=3)
        return int.from_bytes(data, "big")

    async def read_status1(self) -> int:
        data = await self.transfer(OcahSpiOpcode.READ_SR1, rx_len=1)
        return data[0]

    async def read_status2(self) -> int:
        data = await self.transfer(OcahSpiOpcode.READ_SR2, rx_len=1)
        return data[0]

    async def write_enable(self) -> None:
        await self.transfer(OcahSpiOpcode.WRITE_ENABLE)

    async def write_disable(self) -> None:
        await self.transfer(OcahSpiOpcode.WRITE_DISABLE)

    async def page_program(self, addr: int, data: bytes) -> None:
        await self.transfer(OcahSpiOpcode.PAGE_PROGRAM, addr=addr, tx=bytes(data))

    async def sector_erase(self, addr: int) -> None:
        await self.transfer(OcahSpiOpcode.SECTOR_ERASE, addr=addr)

    async def read(self, addr: int, length: int) -> bytes:
        return await self.transfer(OcahSpiOpcode.READ, addr=addr, rx_len=length)

    async def fast_read(self, addr: int, length: int) -> bytes:
        return await self.transfer(OcahSpiOpcode.FAST_READ, addr=addr, dummy_bytes=1, rx_len=length)

    # ------------------------------------------------------------------
    # Bit timing (Mode 0: data changes on the falling edge, samples on the rising edge)
    # ------------------------------------------------------------------

    async def _shift_byte(self, value: int) -> int:
        received = 0
        for bit_index in range(7, -1, -1):
            self._mosi.value = (value >> bit_index) & 0x1
            await Timer(self.half_period_ns, _TIME_UNIT)
            self._sclk.value = 1
            await Timer(self.half_period_ns, _TIME_UNIT)
            received = (received << 1) | (int(self._miso.value) & 0x1)
            self._sclk.value = 0
        return received
