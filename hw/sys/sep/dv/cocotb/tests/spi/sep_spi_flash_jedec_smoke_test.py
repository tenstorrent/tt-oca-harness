# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP OpenTitan SPI host JEDEC-ID smoke test.

The shared flash checker judges the device record (the identifier the device
streamed), the host readback (the identifier the OpenTitan SPI host received
equals what the device sent), and the opcode sequence (one READ JEDEC ID and
nothing else).
"""

from __future__ import annotations

import cocotb
import pyuvm
from ocah_spi_vip import OcahSpiFlash, OcahSpiFlashChecker, OcahSpiOpcode
from sep_base_test import sep_base_test
from seq_lib.sep_spi_flash_jedec_seq import SPI_JEDEC_ID, sep_spi_flash_jedec_seq

REQUIRED_EVIDENCE = ("CHK-SPI-JEDEC-ID", "CHK-SPI-HOST-JEDEC", "CHK-SPI-CMD-ORDER")


@pyuvm.test()
class sep_spi_flash_jedec_smoke_test(sep_base_test):
    """Issue JEDEC ID over the OpenTitan SPI host and OSS flash BFM."""

    required_evidence = REQUIRED_EVIDENCE

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
        checker = OcahSpiFlashChecker(
            name="sep_spi_flash_checker",
            flash=flash,
            required_ids=REQUIRED_EVIDENCE,
            logger=self.logger,
        )
        await flash.start()
        try:
            await self.bring_up_no_cpu()
            # No pad-mux step: this DUT drives the OT SPI host onto the pads
            # directly.
            seq = sep_spi_flash_jedec_seq("spi_flash_jedec_seq")
            await self.start_seq(seq)
        finally:
            await flash.stop()
        checker.replay()
        # RXDATA packs the three identifier bytes little-endian into one word.
        checker.check_host_jedec(int.from_bytes(seq.rxdata.to_bytes(4, "little")[:3], "big"))
        checker.check_command_order([OcahSpiOpcode.JEDEC_ID])
        checker.finalize()
