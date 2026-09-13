# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Flash command set over the OpenTitan SPI host, driven through the CPU-LSU AXI bus.

``sep_spi_flash_ops_seq`` programs the host once, then issues one flash
command per call: the opcode, address, and payload are pushed into TXDATA as
32-bit words and clocked out by one TX segment; a command with a response
holds chip-select (CSAAT) across a following RX segment and drains RXDATA.
The host discards the unused bytes of a partial last TXDATA word at the end
of a segment, so a one-byte command needs one word. Every response the host
received is kept per opcode for the checker's host-side pairing
(``OcahSpiFlashChecker.check_host_responses``).

The body runs the scenario a ``SepSpiFlashOpsCfg`` describes so the test's
run hook stays a table of contents; ``skip_wren_before_program`` is the
negative-validation hook that leaves the functional program unprotected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from ocah_spi_vip import OcahSpiOpcode
from pyuvm import uvm_sequence
from sep_reg_meta import SPI_CONTROLLER

from seq_lib.sep_spi_host_csr_seq import (
    CFG,
    CMD,
    CSID,
    CTRL,
    ERROR_STATUS,
    RXDATA,
    ST_ACTIVE,
    ST_READY,
    STATUS,
    TXDATA,
)

__all__ = ["SepSpiFlashOpsCfg", "sep_spi_flash_ops_seq"]

# CTRL: SPIEN + OUTPUT_EN with a 0x7F TX watermark; CFG: clock divider 9 with
# the chip-select timing the reference firmware uses (SPI_CFG_CLKDIV9_CSN).
HOST_CTRL_ENABLE = 0xA000_007F
HOST_CFG_CLKDIV9_CSN = 0x0222_0009
_CMD_LEN_MASK = SPI_CONTROLLER.field_mask("CMD", "len")
_CMD_CSAAT = SPI_CONTROLLER.field_mask("CMD", "csaat")
_CMD_DIR_LSB = SPI_CONTROLLER.field_lsb("CMD", "direction")
_CMD_DIR_RX = 1 << _CMD_DIR_LSB
_CMD_DIR_TX = 2 << _CMD_DIR_LSB
_READY_POLLS = 1000
_IDLE_POLLS = 2000
_ADDR_BYTES = 3
_ERASED = 0xFF


@dataclass(frozen=True)
class SepSpiFlashOpsCfg:
    """One program-erase-readback scenario: the span, the two payloads, the negative hook."""

    addr: int
    data: bytes
    neighbour_addr: int
    neighbour_data: bytes
    skip_wren_before_program: bool = False
    expected_ops: tuple[int, ...] = field(default=(), compare=False)

    @property
    def length(self) -> int:
        return len(self.data)

    def command_order(self) -> list[int]:
        """The in-scope opcode sequence ``body`` puts on the wire."""
        functional_wren = [] if self.skip_wren_before_program else [OcahSpiOpcode.WRITE_ENABLE]
        return [
            OcahSpiOpcode.JEDEC_ID,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.WRITE_DISABLE,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            *functional_wren,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.FAST_READ,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.SECTOR_ERASE,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.READ_SR1,
        ]


class sep_spi_flash_ops_seq(uvm_sequence):
    """Program, read back, and erase against the flash device through the OpenTitan SPI host."""

    def __init__(self, name: str = "sep_spi_flash_ops_seq", cfg: SepSpiFlashOpsCfg | None = None):
        super().__init__(name)
        self.cfg = cfg
        self.jedec = 0
        self.blank_before: bytes = b""
        self.readback: bytes = b""
        self.fast_readback: bytes = b""
        self.neighbour_readback: bytes = b""
        self.erased: bytes = b""
        self.neighbour_after: bytes = b""
        self.error_status = 0
        self._responses: dict[int, list[bytes]] = {}

    # ------------------------------------------------------------------
    # Scenario
    # ------------------------------------------------------------------

    async def body(self) -> None:
        cfg = self.cfg
        if cfg is None:
            raise ValueError("sep_spi_flash_ops_seq needs a SepSpiFlashOpsCfg")
        await self.configure_host()
        self.jedec = await self.jedec_id()
        await self.read_status1()
        await self.write_enable()
        await self.read_status1()
        await self.write_disable()
        await self.read_status1()
        await self.page_program(cfg.addr, cfg.data)
        self.blank_before = await self.read(cfg.addr, cfg.length)
        if not cfg.skip_wren_before_program:
            await self.write_enable()
        await self.page_program(cfg.addr, cfg.data)
        self.readback = await self.read(cfg.addr, cfg.length)
        self.fast_readback = await self.fast_read(cfg.addr, cfg.length)
        await self.read_status1()
        await self.write_enable()
        await self.page_program(cfg.neighbour_addr, cfg.neighbour_data)
        self.neighbour_readback = await self.read(cfg.neighbour_addr, cfg.length)
        await self.write_enable()
        await self.sector_erase(cfg.addr)
        self.erased = await self.read(cfg.addr, cfg.length)
        self.neighbour_after = await self.read(cfg.neighbour_addr, cfg.length)
        await self.read_status1()
        self.error_status = await self._read(ERROR_STATUS, expected=0)

    # ------------------------------------------------------------------
    # Flash command set
    # ------------------------------------------------------------------

    async def configure_host(self) -> None:
        """Enable the host with the divider and chip-select timing of the reference flow."""
        await self._write(CTRL, HOST_CTRL_ENABLE)
        await self._write(CFG, HOST_CFG_CLKDIV9_CSN)
        await self._write(CSID, 0)
        await self._write(ERROR_STATUS, 0xFFFF_FFFF)

    async def jedec_id(self) -> int:
        data = await self._command(OcahSpiOpcode.JEDEC_ID, rx_len=3)
        return int.from_bytes(data, "big")

    async def read_status1(self) -> int:
        return (await self._command(OcahSpiOpcode.READ_SR1, rx_len=1))[0]

    async def read_status2(self) -> int:
        return (await self._command(OcahSpiOpcode.READ_SR2, rx_len=1))[0]

    async def write_enable(self) -> None:
        await self._command(OcahSpiOpcode.WRITE_ENABLE)

    async def write_disable(self) -> None:
        await self._command(OcahSpiOpcode.WRITE_DISABLE)

    async def page_program(self, addr: int, data: bytes) -> None:
        await self._command(OcahSpiOpcode.PAGE_PROGRAM, addr=addr, tx=bytes(data))

    async def sector_erase(self, addr: int) -> None:
        await self._command(OcahSpiOpcode.SECTOR_ERASE, addr=addr)

    async def read(self, addr: int, length: int) -> bytes:
        return await self._command(OcahSpiOpcode.READ, addr=addr, rx_len=length)

    async def fast_read(self, addr: int, length: int) -> bytes:
        return await self._command(OcahSpiOpcode.FAST_READ, addr=addr, dummy_bytes=1, rx_len=length)

    def responses(self, opcode: int) -> list[bytes]:
        """Every response the host received for ``opcode``, in order."""
        return list(self._responses.get(int(opcode), []))

    # ------------------------------------------------------------------
    # Host segment programming
    # ------------------------------------------------------------------

    async def _command(
        self,
        opcode: int,
        *,
        addr: int | None = None,
        dummy_bytes: int = 0,
        tx: bytes = b"",
        rx_len: int = 0,
    ) -> bytes:
        """One flash command: a TX segment, then an RX segment when a response is expected.

        ``rx_len`` bytes come back little-endian in RXDATA words; a partial last
        word is masked to the bytes the segment clocked.
        """
        header = bytearray([int(opcode) & 0xFF])
        if addr is not None:
            header += int(addr).to_bytes(_ADDR_BYTES, "big")
        header += bytes(dummy_bytes)
        header += bytes(tx)
        await self._wait_ready()
        for offset in range(0, len(header), 4):
            word = header[offset : offset + 4].ljust(4, b"\x00")
            await self._write(TXDATA, int.from_bytes(word, "little"))
        await self._write(CMD, _CMD_DIR_TX | (_CMD_CSAAT if rx_len else 0) | (len(header) - 1))
        received = bytearray()
        if rx_len:
            await self._wait_ready()
            await self._write(CMD, _CMD_DIR_RX | (rx_len - 1))
            await self._wait_idle()
            for offset in range(0, rx_len, 4):
                word = await self._read(RXDATA)
                received += word.to_bytes(4, "little")[: min(4, rx_len - offset)]
            self._responses.setdefault(int(opcode), []).append(bytes(received))
        else:
            await self._wait_idle()
        return bytes(received)

    async def _write(self, addr: int, data: int) -> None:
        item = SepAxiItem(f"wr_spi_0x{addr:08x}")
        item.op = SepAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)

    async def _read(self, addr: int, expected: int | None = None) -> int:
        item = SepAxiItem(f"rd_spi_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata

    async def _wait_ready(self) -> int:
        for _ in range(_READY_POLLS):
            status = await self._read(STATUS)
            if status & ST_READY:
                return status
        raise AssertionError("SPI host did not become ready")

    async def _wait_idle(self) -> int:
        for _ in range(_IDLE_POLLS):
            status = await self._read(STATUS)
            if not (status & ST_ACTIVE):
                return status
        raise AssertionError("SPI host did not become idle")
