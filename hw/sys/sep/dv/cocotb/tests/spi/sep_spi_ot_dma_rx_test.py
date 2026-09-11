# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP OpenTitan-SPI RX -> Secure-DMA -> SRAM firmware-boot test (PyUVM).

OSS port of the reference suite ``sep_spi_ot_dma_rx_test``. Boots the VeeR EL2 core and runs
the spi_ot_dma_rx firmware: it configures the OpenTitan SPI host, arms the Secure
DMA in hardware-handshake mode (SRC = SPI RXDATA fixed/WRAP, DST = SRAM
incrementing), then issues a SPI flash READ. The SPI RX FIFO crossing its
watermark raises ``lsio_trigger``, which drains a chunk to SRAM via the DMA
hardware handshake -- an SPI + DMA + fabric + memory datapath that is internal to
bare ``sep`` (SPI-FIFO -> DMA).

Beyond the reference suite: the reference test clocks idle MISO (no flash model) and only
checks "DMA done + no SPI error". Here the OSS flash BFM is preloaded with a known
constant (0xA5) and the firmware value-checks every DMA-written SRAM word ==
0xA5A5A5A5, so the SPI->DMA->SRAM data path is proven, not just completion. The
firmware is self-checking (returns its error count; start.S emits PASS/FAIL magic
on the 0x8000_0000 mailbox), and the boot scoreboard gates on the PASS magic, the
banner, and ICCM execution. A SRAM == 0xA5A5A5A5 result can only come from the
BFM's preloaded flash over the SPI -> RX-FIFO -> lsio_trigger -> DMA path, so the
firmware self-check alone proves the datapath end-to-end: a different preload
byte makes the firmware report a SRAM mismatch and the run fails.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "spi_ot_dma_rx_test")
_ITCM_HEX = os.path.join(_FW_DIR, "spi_ot_dma_rx_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "spi_ot_dma_rx_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP SPI OT DMA RX test"

# Must match the firmware's RX_SIZE / RX_PATTERN (spi_ot_dma_rx_test.c). The
# firmware issues a flash READ (0x03) at address 0 and value-checks the result.
_RX_SIZE = 64
_RX_PATTERN = 0xA5


@pyuvm.test()
class sep_spi_ot_dma_rx_test(sep_base_test):
    """Boot VeeR EL2 and run the SPI-RX -> DMA -> SRAM firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        dut = cocotb.top
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_spi_rx_flash",
        )
        # Preload the known pattern the firmware reads back and value-checks.
        flash.write_memory(0, bytes([_RX_PATTERN]) * _RX_SIZE)
        await flash.start()
        try:
            # Override the boot scoreboard's expected banner here (after its own
            # build_phase, which resets it to the hello_world default).
            self.sb.expected_line = _BANNER
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                _DTCM_HEX,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
            # Evidence is the firmware's own value-check (gated by the boot
            # scoreboard's fw_pass magic): SRAM == 0xA5A5A5A5 can ONLY come from
            # the BFM's preloaded flash streamed over MISO -> SPI RX FIFO ->
            # lsio_trigger -> DMA -> SRAM, so a passing firmware run proves the
            # full SPI->DMA datapath end-to-end. flash.get_transactions() is not
            # evidence here: the BFM's open-ended 0x03 READ (_do_read loops
            # `while cs_n==0`) blocks awaiting a final SCK edge after the host
            # stops clocking, so the transaction is served on the wire but never
            # reaches _log_transaction. flash.read_memory() only echoes the
            # preload.
        finally:
            await flash.stop()
