# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OpenTitan SPI host sends JEDEC ID (0x9F) on the pads and returns the flash ID in RXDATA.

The flash BFM must log 0x9F as its last opcode, and the RXDATA word must carry
the BFM's three ID bytes in wire order, in one in-word byte order, with its
fourth byte 0 (CHK-JEDEC-ID). The in-word order is not graded: the one
OBS-SPI-BYTEORDER line logs it. Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_spi_lane_responder import SepSpiByteOrder
from env.sep_spi_scoreboard import SepSpiScoreboard
from env.sep_spi_wire_monitor import SepSpiWireMonitor
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from seq_lib.sep_spi_flash_jedec_seq import SPI_JEDEC_ID, sep_spi_flash_jedec_seq


@pyuvm.test()
class sep_spi_flash_jedec_smoke_test(sep_base_test):
    """The flash BFM sees opcode 0x9F, and RXDATA holds the BFM's JEDEC ID bytes."""

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
        wire = await SepSpiWireMonitor(dut).start()
        order = SepSpiByteOrder()
        sb = SepSpiScoreboard(wire, flash, self.logger, seed=self.random_seed(), order=order)
        await flash.start()
        try:
            await self.bring_up_no_cpu()
            # No select step: the OT SPI host drives the pads directly.
            seq = sep_spi_flash_jedec_seq("spi_flash_jedec_seq")
            await self.start_seq(seq)
            transactions = flash.get_transactions()
            assert transactions, "SPI flash BFM saw no completed transactions"
            assert transactions[-1]["opcode"] == 0x9F, "SPI flash did not see JEDEC-ID opcode"
            # The flash model sends the ID most significant byte first.
            want = SPI_JEDEC_ID.to_bytes(3, "big")
            got = order.bytes_of([seq.rxdata], 3, expect=want, where="jedec", pad=True)
            if got != want:
                self.logger.error(
                    "CHK-JEDEC-ID FAIL: rxdata=0x%08x bytes=%s expected=%s pad=00",
                    seq.rxdata,
                    got.hex(),
                    want.hex(),
                )
                raise AssertionError(
                    f"CHK-JEDEC-ID FAIL: rxdata=0x{seq.rxdata:08x} carries {got.hex()}, "
                    f"expected {want.hex()} and a zero pad byte in one in-word order"
                )
            self.logger.info(
                "CHK-JEDEC-ID PASS: opcode=0x9F rxdata=0x%08x bytes=%s order=%s",
                seq.rxdata,
                got.hex(),
                order.order or "undecided",
            )
            sb.expect_rx(0x9F, got, source="dut", label="RXDATA")
        finally:
            await flash.stop()
        await wire.finish(self.logger, seed=self.random_seed(), flash=flash)
        sb.finish()
        order.log_obs(self.logger, self.random_seed())
