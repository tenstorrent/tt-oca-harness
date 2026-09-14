# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
ocah_spi_vip — OCAH-stable SPI/QSPI/OSPI flash BFM for cocotb testbenches.

This package provides a single, versioned Python API surface for emulating
NOR-flash devices and monitoring SPI bus traffic in OCAH cocotb tests.  All
classes accept and return plain Python ints; no internal VIP types leak out.

Primary exports
---------------
OcahSpiFlash      — SPI/QSPI/OSPI NOR-flash device BFM (generic pin set).
OcahSepSpiFlash   — SEP-specific subclass mapped to the SEP xSPI pad bundle.
OcahSpiMonitor    — Passive monitor for SPI command/address/data sequences.

Quick-start (single SPI)
------------------------
::

    from ocah_spi_vip import OcahSpiFlash

    @cocotb.test()
    async def test_jedec_id(dut):
        clk = Clock(dut.spi_clk, 10, units="ns")
        cocotb.start_soon(clk.start())

        flash = OcahSpiFlash(
            cs_n   = dut.spi_cs_n,
            sclk   = dut.spi_sclk,
            mosi   = dut.spi_mosi,
            miso   = dut.spi_miso,
            name   = "flash0",
            mode   = "single",
            jedec_id = 0x20BA18,   # generic NOR
        )
        flash.init_signals()
        await flash.start()
        # flash responds autonomously; drive the controller...

Quick-start (SEP xSPI)
-----------------------
::

    from ocah_spi_vip import OcahSepSpiFlash

    @cocotb.test()
    async def test_sep_flash(dut):
        flash = OcahSepSpiFlash(
            cs_n      = dut.spi_cs_n_o,
            sclk      = dut.spi_clk_o,
            dq_out    = dut.spi_txd_o,
            dq_in     = dut.spi_rxd_i,
            dq_oe_n   = dut.spi_dq_oe_n_o,
            rebar_o   = dut.spi_mem_rebar_opad_o,
            rebar_i   = dut.spi_mem_rebar_ipad_i,
            name      = "sep_flash",
            mode      = "quad",
        )
        flash.init_signals()
        await flash.start()

See ``examples/example_jedec_id.py`` for an annotated usage snippet.
"""

from .ocah_sep_spi_flash import OcahSepSpiFlash, OcahSepSpiFlashError
from .ocah_spi_flash import OcahSpiFlash, OcahSpiFlashError, SpiMode
from .ocah_spi_monitor import OcahSpiMonitor

__all__ = [
    # Flash device BFMs
    "OcahSpiFlash",
    "OcahSepSpiFlash",
    # Passive monitor
    "OcahSpiMonitor",
    # Error types
    "OcahSpiFlashError",
    "OcahSepSpiFlashError",
    # Mode enumeration
    "SpiMode",
]

__version__ = "0.1.0"
