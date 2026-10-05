# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan SPI-host JEDEC-ID sequence for the SEP OSS flow.

Drives the OpenTitan SPI host controller over the CPU-LSU AXI bus to issue a
JEDEC-ID (0x9F) command against the OSS flash BFM, then reads RXDATA and
ERROR_STATUS back with exact ``expected`` values (scoreboard value-checked). The
RXDATA / opcode assertions live in the test; this sequence exposes ``rxdata``.

Co-located with the SPI register-map constants so the test does not embed raw
addresses. The SEP instantiates the upstream OpenTitan spi_host register block
(the SPI_CONTROLLER symbols are generated from the overlay spi_controller.rdl,
which follows the upstream spi_host register map), so register names and field
packing are the OpenTitan ones.
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

CMD_DIR_DUMMY = 0
CMD_DIR_RDONLY = 1
CMD_DIR_WRONLY = 2
CMD_DIR_BIDIR = 3
CMD_SPEED_STANDARD = 0


def _field(reg: str, field: str, value: int) -> int:
    """Place ``value`` in one generated SPI_CONTROLLER field; reject overflow."""
    mask = SPI_CONTROLLER.field_mask(reg, field)
    word = value << SPI_CONTROLLER.field_lsb(reg, field)
    if word & ~mask:
        raise ValueError(f"{reg}.{field}={value:#x} does not fit mask {mask:#x}")
    return word


def spi_command(
    direction: int, nbytes: int, *, csaat: bool = False, speed: int = CMD_SPEED_STANDARD
) -> int:
    """Pack one COMMAND word for a ``nbytes``-byte segment (LEN is bytes - 1)."""
    return (
        _field("COMMAND", "len", nbytes - 1)
        | _field("COMMAND", "direction", direction)
        | _field("COMMAND", "speed", speed)
        | _field("COMMAND", "csaat", int(csaat))
    )


# Host enabled with its outputs driven, RX watermark 0x7F, TX watermark 0.
SPI_CONTROL_ENABLE = (
    SPI_CONTROLLER.field_mask("CONTROL", "spien")
    | SPI_CONTROLLER.field_mask("CONTROL", "output_en")
    | _field("CONTROL", "rx_watermark", 0x7F)
)
# Mode 0 (CPOL = CPHA = 0), CLKDIV 9, two-cycle CS# lead / trail / idle.
SPI_CONFIGOPTS_MODE0 = (
    _field("CONFIGOPTS", "clkdiv", 9)
    | _field("CONFIGOPTS", "csnidle", 2)
    | _field("CONFIGOPTS", "csntrail", 2)
    | _field("CONFIGOPTS", "csnlead", 2)
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
        await self._write(SPI_CONTROLLER_CONTROL, SPI_CONTROL_ENABLE)
        await self._write(SPI_CONTROLLER_CONFIGOPTS, SPI_CONFIGOPTS_MODE0)
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
