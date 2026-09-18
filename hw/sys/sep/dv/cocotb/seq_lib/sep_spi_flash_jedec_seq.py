# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan SPI-host JEDEC-ID sequence for the SEP OSS flow.

Drives the OpenTitan SPI host controller over the CPU-LSU AXI bus to issue a
JEDEC-ID (0x9F) command against the OSS flash BFM, then reads RXDATA and
ERROR_STATUS back with exact ``expected`` values (scoreboard value-checked). The
RXDATA / opcode assertions live in the test; this sequence exposes ``rxdata``.

Co-located with the SPI register-map constants so the test does not embed raw
addresses. Offsets mirror the OpenTitan spi_host register block.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence
from sep_reg_meta import SPI_CONTROLLER, sym

SPI_CONTROLLER_CTRL = sym("SPI_CONTROLLER_CTRL_REG_ADDR")
SPI_CONTROLLER_STATUS = sym("SPI_CONTROLLER_STATUS_REG_ADDR")
SPI_CONTROLLER_CFG = sym("SPI_CONTROLLER_CFG_REG_ADDR")
SPI_CONTROLLER_CSID = sym("SPI_CONTROLLER_CSID_REG_ADDR")
SPI_CONTROLLER_CMD = sym("SPI_CONTROLLER_CMD_REG_ADDR")
SPI_CONTROLLER_RXDATA = sym("SPI_CONTROLLER_RXDATA_REG_ADDR")
SPI_CONTROLLER_TXDATA = sym("SPI_CONTROLLER_TXDATA_REG_ADDR")
SPI_CONTROLLER_ERROR_STATUS = sym("SPI_CONTROLLER_ERROR_STATUS_REG_ADDR")

SPI_JEDEC_ID = 0x20BA18
SPI_RX_JEDEC_WORD = 0x0018BA20

STATUS_ACTIVE = SPI_CONTROLLER.field_mask("STATUS", "active")
STATUS_READY = SPI_CONTROLLER.field_mask("STATUS", "ready")
CTRL_ENABLE = (
    (0x7F << SPI_CONTROLLER.field_lsb("CTRL", "rx_watermark"))
    | SPI_CONTROLLER.field_mask("CTRL", "output_en")
    | SPI_CONTROLLER.field_mask("CTRL", "spien")
)
CFG_JEDEC = (
    (0x9 << SPI_CONTROLLER.field_lsb("CFG", "clkdiv"))
    | (0x2 << SPI_CONTROLLER.field_lsb("CFG", "csnidle"))
    | (0x2 << SPI_CONTROLLER.field_lsb("CFG", "csntrail"))
    | (0x2 << SPI_CONTROLLER.field_lsb("CFG", "csnlead"))
)
CMD_DIR_LSB = SPI_CONTROLLER.field_lsb("CMD", "direction")
CMD_LEN_LSB = SPI_CONTROLLER.field_lsb("CMD", "len")
CMD_CSAAT = SPI_CONTROLLER.field_mask("CMD", "csaat")
CMD_TX_CSAAT = (2 << CMD_DIR_LSB) | CMD_CSAAT
CMD_RX_LEN2 = (1 << CMD_DIR_LSB) | (2 << CMD_LEN_LSB)


class sep_spi_flash_jedec_seq(uvm_sequence):
    """Issue JEDEC-ID over the OpenTitan SPI host; exposes ``rxdata``."""

    def __init__(self, name: str = "sep_spi_flash_jedec_seq") -> None:
        super().__init__(name)
        self.rxdata = 0

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
        for _ in range(1000):
            status = await self._read(SPI_CONTROLLER_STATUS)
            if status & STATUS_READY:
                return status
        raise AssertionError("SPI controller did not become ready")

    async def _wait_idle(self) -> int:
        for _ in range(2000):
            status = await self._read(SPI_CONTROLLER_STATUS)
            if not (status & STATUS_ACTIVE):
                return status
        raise AssertionError("SPI controller did not become idle")

    async def body(self) -> None:
        await self._write(SPI_CONTROLLER_CTRL, CTRL_ENABLE)
        await self._write(SPI_CONTROLLER_CFG, CFG_JEDEC)
        await self._write(SPI_CONTROLLER_CSID, 0)
        await self._write(SPI_CONTROLLER_ERROR_STATUS, 0xFFFF_FFFF)

        await self._wait_ready()
        await self._write(SPI_CONTROLLER_TXDATA, 0x0000_009F)
        await self._write(SPI_CONTROLLER_CMD, CMD_TX_CSAAT)

        await self._wait_ready()
        await self._write(SPI_CONTROLLER_CMD, CMD_RX_LEN2)
        await self._wait_idle()
        self.rxdata = await self._read(SPI_CONTROLLER_RXDATA, SPI_RX_JEDEC_WORD)
        await self._read(SPI_CONTROLLER_ERROR_STATUS, 0)
