# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP OpenTitan SPI host JEDEC-ID smoke test."""

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
    """Issue JEDEC ID over the OpenTitan SPI host and OSS flash BFM."""

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
            # No pad-mux step: this DUT drives the OT SPI host onto the pads
            # directly.
            seq = sep_spi_flash_jedec_seq("spi_flash_jedec_seq")
            await self.start_seq(seq)
            transactions = flash.get_transactions()
            assert transactions, "SPI flash BFM saw no completed transactions"
            assert transactions[-1]["opcode"] == 0x9F, "SPI flash did not see JEDEC-ID opcode"
            assert seq.rxdata == SPI_RX_JEDEC_WORD, (
                f"unexpected JEDEC response 0x{seq.rxdata:08x}, expected 0x{SPI_RX_JEDEC_WORD:08x}"
            )
        finally:
            await flash.stop()
