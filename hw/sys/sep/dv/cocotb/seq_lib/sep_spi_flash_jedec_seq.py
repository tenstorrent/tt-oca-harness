# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan SPI-host JEDEC-ID sequence for the SEP OSS flow.

Drives the OpenTitan SPI host controller over the CPU-LSU AXI bus to issue a
JEDEC-ID (0x9F) command against the OSS flash BFM, then reads RXDATA and
ERROR_STATUS back with exact ``expected`` values (scoreboard value-checked). The
RXDATA / opcode assertions live in the test; this sequence exposes ``rxdata``.

Co-located with the SPI register-map constants so the test does not embed raw
addresses. The SEP instantiates the upstream OpenTitan spi_host register block
(the SPI_CONTROLLER symbols are generated from spi_host.hjson), so register
names and field packing are the OpenTitan ones.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence
from sep_reg_meta import SPI_CONTROLLER, sym

SPI_CONTROLLER_CONTROL = sym("SPI_CONTROLLER_CONTROL_REG_ADDR")
SPI_CONTROLLER_STATUS = sym("SPI_CONTROLLER_STATUS_REG_ADDR")
SPI_CONTROLLER_CONFIGOPTS = sym("SPI_CONTROLLER_CONFIGOPTS_REG_ADDR")
SPI_CONTROLLER_CSID = sym("SPI_CONTROLLER_CSID_REG_ADDR")
SPI_CONTROLLER_COMMAND = sym("SPI_CONTROLLER_COMMAND_REG_ADDR")
# RXDATA / TXDATA are single-entry windows in the upstream map, so the generated
# symbols carry the array-instance and window suffixes.
SPI_CONTROLLER_RXDATA = sym("SPI_CONTROLLER_RXDATA_0__MEM_BASE_ADDR")
SPI_CONTROLLER_TXDATA = sym("SPI_CONTROLLER_TXDATA_0__MEM_BASE_ADDR")
SPI_CONTROLLER_ERROR_STATUS = sym("SPI_CONTROLLER_ERROR_STATUS_REG_ADDR")

SPI_JEDEC_ID = 0x20BA18
SPI_RX_JEDEC_WORD = 0x0018BA20

STATUS_ACTIVE = SPI_CONTROLLER.field_mask("STATUS", "active")
STATUS_READY = SPI_CONTROLLER.field_mask("STATUS", "ready")

# COMMAND packing (OpenTitan spi_host): CSAAT[0], SPEED[2:1], DIRECTION[4:3],
# LEN[24:5]. LEN is the segment length in bytes minus one.
CMD_CSAAT = 1 << 0
CMD_SPEED_SHIFT = 1
CMD_DIRECTION_SHIFT = 3
CMD_LEN_SHIFT = 5
CMD_DIR_DUMMY = 0
CMD_DIR_RDONLY = 1
CMD_DIR_WRONLY = 2
CMD_DIR_BIDIR = 3
CMD_SPEED_STANDARD = 0


def spi_command(
    direction: int, nbytes: int, *, csaat: bool = False, speed: int = CMD_SPEED_STANDARD
) -> int:
    """Pack one COMMAND word for a ``nbytes``-byte segment."""
    return (
        ((nbytes - 1) << CMD_LEN_SHIFT)
        | (direction << CMD_DIRECTION_SHIFT)
        | (speed << CMD_SPEED_SHIFT)
        | (CMD_CSAAT if csaat else 0)
    )


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
        await self._write(SPI_CONTROLLER_CONTROL, 0xA000_007F)
        await self._write(SPI_CONTROLLER_CONFIGOPTS, 0x0222_0009)
        await self._write(SPI_CONTROLLER_CSID, 0)
        await self._write(SPI_CONTROLLER_ERROR_STATUS, 0xFFFF_FFFF)

        await self._wait_ready()
        await self._write(SPI_CONTROLLER_TXDATA, 0x0000_009F)
        # One-byte write of the JEDEC-ID opcode; hold CS# for the read segment.
        await self._write(SPI_CONTROLLER_COMMAND, spi_command(CMD_DIR_WRONLY, 1, csaat=True))

        await self._wait_ready()
        # Three-byte read of the ID; CS# deasserts when the segment ends.
        await self._write(SPI_CONTROLLER_COMMAND, spi_command(CMD_DIR_RDONLY, 3))
        await self._wait_idle()
        self.rxdata = await self._read(SPI_CONTROLLER_RXDATA, SPI_RX_JEDEC_WORD)
        await self._read(SPI_CONTROLLER_ERROR_STATUS, 0)
