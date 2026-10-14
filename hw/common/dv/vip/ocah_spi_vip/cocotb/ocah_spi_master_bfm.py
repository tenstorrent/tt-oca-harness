# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Single-SPI controller engine for benches that have no SPI host IP.

``OcahSpiMasterBfm`` drives chip-select, clock, and MOSI and samples MISO, one
frame per command: opcode, optional address, optional dummy bytes, payload
bytes, then ``rx_len`` response bytes with MOSI held low. ``tail_bits`` (0 to
7) clocks that many bits of a further byte after the payload, so a test can end
a frame off a byte boundary. It is the master-side twin of the ``OcahSpiFlash``
device and the engine behind ``OcahSpiMasterSequence``. Non-UVM benches may use
it directly; tests go through the sequence.

The SPI mode defaults to Mode 0 (``cpol=0, cpha=0``): MOSI changes on the
falling edge and is sampled on the rising edge. ``set_mode`` selects any of
the four modes; ``OcahSpiFlash`` answers Mode 0 only. ``raw_frame`` clocks an
exact bit list in one chip-select frame, so a test can end a frame at any bit
of any phase, and ``drive`` sets the pins directly for wire-level stimulus.

The engine has no SV-UVM twin: the package ships the cocotb realization only.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
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
        cpol: int = 0,
        cpha: int = 0,
    ) -> None:
        self.name = name
        self.log = logging.getLogger(name)
        self._cs_n = cs_n
        self._sclk = sclk
        self._mosi = mosi
        self._miso = miso
        self.half_period_ns = half_period_ns
        self.addr_bytes = addr_bytes
        self.cpol = cpol & 1
        self.cpha = cpha & 1
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
        """Idle the bus: chip-select high, clock at the CPOL level, MOSI low."""
        self._cs_n.value = 1
        self._sclk.value = self.cpol
        self._mosi.value = 0

    def set_mode(self, cpol: int, cpha: int) -> None:
        """SPI mode of the next frames; the clock moves to the new idle level at once."""
        self.cpol = cpol & 1
        self.cpha = cpha & 1
        self._sclk.value = self.cpol

    async def drive(
        self,
        *,
        cs_n: Any = None,
        sclk: Any = None,
        mosi: Any = None,
        hold_ns: int | None = None,
    ) -> None:
        """Set the given pins in one time step, then wait ``hold_ns`` (default a half period).

        A value may be anything the handle accepts, ``"x"`` or ``"z"``
        included; a pin given as ``None`` keeps its value.
        """
        for handle, value in ((self._cs_n, cs_n), (self._sclk, sclk), (self._mosi, mosi)):
            if value is not None:
                handle.value = _pin_value(handle, value)
        await Timer(self.half_period_ns if hold_ns is None else hold_ns, _TIME_UNIT)

    async def raw_frame(self, bits: Sequence[int]) -> list[int]:
        """One chip-select frame that clocks exactly ``bits`` on MOSI; returns the MISO bits."""
        self._cs_n.value = 0
        await Timer(self.half_period_ns, _TIME_UNIT)
        received = [await self._clock_bit(int(bit) & 0x1) for bit in bits]
        await Timer(self.half_period_ns, _TIME_UNIT)
        self._cs_n.value = 1
        await Timer(self.half_period_ns, _TIME_UNIT)
        self.frames += 1
        self.log.debug("%s: raw frame bits=%d", self.name, len(bits))
        return received

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
        tail_bits: int = 0,
    ) -> bytes:
        """One frame: opcode, address, dummies, payload out, ``rx_len`` bytes in, then ``tail_bits`` bits."""
        if not 0 <= tail_bits < 8:
            raise ValueError(f"{self.name}: tail_bits={tail_bits} is outside 0..7")
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
        await self._shift_bits(0, tail_bits)
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
    # Bit timing: MOSI changes on the shift edge and is sampled on the other
    # ------------------------------------------------------------------

    async def _shift_byte(self, value: int) -> int:
        return await self._shift_bits(value, 8)

    async def _shift_bits(self, value: int, count: int) -> int:
        """Shift the top ``count`` bits of the byte ``value``, MSB first."""
        received = 0
        for bit_index in range(7, 7 - count, -1):
            received = (received << 1) | await self._clock_bit((value >> bit_index) & 0x1)
        return received

    async def _clock_bit(self, bit: int) -> int:
        """One SCK cycle that leaves and returns to the CPOL level; returns the MISO bit.

        CPHA 0: MOSI is set half a period before the leading edge and held
        through the trailing edge, where the next bit is set. CPHA 1: MOSI is
        set on the leading edge and sampled on the trailing edge.
        """
        active = 1 - self.cpol
        if self.cpha == 0:
            self._mosi.value = bit
            await Timer(self.half_period_ns, _TIME_UNIT)
            self._sclk.value = active
            await Timer(self.half_period_ns, _TIME_UNIT)
            received = int(self._miso.value) & 0x1
            self._sclk.value = self.cpol
        else:
            self._sclk.value = active
            self._mosi.value = bit
            await Timer(self.half_period_ns, _TIME_UNIT)
            received = int(self._miso.value) & 0x1
            self._sclk.value = self.cpol
            await Timer(self.half_period_ns, _TIME_UNIT)
        return received


def _pin_value(handle: Any, value: Any) -> Any:
    """``value`` as the handle takes it; ``"x"``/``"z"`` become a one-bit logic value."""
    if isinstance(value, str):
        try:
            from cocotb.types import Logic  # cocotb 2.x

            return Logic(value)
        except ImportError:  # cocotb 1.x
            from cocotb.binary import BinaryValue

            return BinaryValue(value.lower(), n_bits=len(handle))
    return value
