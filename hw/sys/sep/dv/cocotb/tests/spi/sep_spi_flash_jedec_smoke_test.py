# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OpenTitan SPI host sends JEDEC ID (0x9F) on the pads and returns the flash ID in RXDATA.

The flash BFM must log 0x9F as its last opcode, and RXDATA must equal the BFM's
ID bytes (CHK-JEDEC). Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from seq_lib.sep_spi_flash_jedec_seq import (
    SPI_JEDEC_ID,
    SPI_RX_JEDEC_WORD,
    sep_spi_flash_jedec_seq,
)


@pyuvm.test()
class sep_spi_flash_jedec_smoke_test(sep_base_test):
    """The flash BFM sees opcode 0x9F, and RXDATA holds the BFM's JEDEC ID word."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            jedec_id=SPI_JEDEC_ID,
            name="sep_spi_flash",
        )
        await flash.start()
        try:
            await self.bring_up_no_cpu()
            # No select step: the OT SPI host drives the pads directly.
            seq = sep_spi_flash_jedec_seq("spi_flash_jedec_seq")
            await self.start_seq(seq)
            transactions = flash.get_transactions()
            assert transactions, "SPI flash BFM saw no completed transactions"
            assert transactions[-1]["opcode"] == 0x9F, "SPI flash did not see JEDEC-ID opcode"
            assert seq.rxdata == SPI_RX_JEDEC_WORD, (
                f"unexpected JEDEC response 0x{seq.rxdata:08x}, expected 0x{SPI_RX_JEDEC_WORD:08x}"
            )
            self.logger.info("CHK-JEDEC PASS: opcode=0x9F rxdata=0x%08x", seq.rxdata)
        finally:
            await flash.stop()
