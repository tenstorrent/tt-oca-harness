# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
ocah_spi_vip — OCAH-stable SPI flash device, controller, monitor, and checker for cocotb.

This package provides a single, versioned Python API surface for emulating a
NOR-flash device, driving one as a controller, monitoring SPI bus traffic, and
judging flash behaviour in OCAH cocotb tests.  All classes accept and return
plain Python ints and bytes; no internal VIP types leak out.

Primary exports
---------------
OcahSpiFlash            — SPI/QSPI/OSPI NOR-flash device BFM (generic pin set).
OcahSepSpiFlash         — SEP-specific subclass mapped to the SEP xSPI pad bundle.
OcahSpiMasterBfm        — Mode-0 SPI controller engine for benches without a host IP.
OcahSpiMasterSequence   — Test-facing operations over the controller engine.
OcahSpiMonitor          — Passive monitor for SPI command/address/data sequences.
OcahSpiFlashChecker     — Command, state, and memory checker over a flash reference model.
OcahSpiFlashRefModel    — The reference model the checker rebuilds from the wire.
OcahSpiOpcode           — Baseline command opcodes.

Quick-start (single SPI)
------------------------
::

    from ocah_spi_vip import OcahSpiFlash, OcahSpiFlashChecker

    @cocotb.test()
    async def test_jedec_id(dut):
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
        checker = OcahSpiFlashChecker(flash=flash, required_ids=("CHK-SPI-JEDEC-ID",))
        # drive the controller...
        checker.replay()
        checker.finalize()

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

See ``examples/`` for annotated usage snippets.
"""

from .ocah_sep_spi_flash import OcahSepSpiFlash, OcahSepSpiFlashError
from .ocah_spi_flash import OcahSpiFlash, OcahSpiFlashError
from .ocah_spi_flash_checker import OcahSpiFlashChecker, OcahSpiFlashRecord, OcahSpiFlashRefModel
from .ocah_spi_master_bfm import OcahSpiMasterBfm
from .ocah_spi_master_sequence import OcahSpiMasterSequence
from .ocah_spi_monitor import OcahSpiMonitor
from .ocah_spi_types import (
    IN_SCOPE_OPCODES,
    PAGE_SIZE,
    SECTOR_SIZE,
    SR1_BUSY,
    SR1_WEL,
    OcahSpiOpcode,
    SpiMode,
    opcode_name,
)

__all__ = [
    # Flash device BFMs
    "OcahSpiFlash",
    "OcahSepSpiFlash",
    # Controller side
    "OcahSpiMasterBfm",
    "OcahSpiMasterSequence",
    # Passive monitor
    "OcahSpiMonitor",
    # Checker and reference model
    "OcahSpiFlashChecker",
    "OcahSpiFlashRecord",
    "OcahSpiFlashRefModel",
    # Error types
    "OcahSpiFlashError",
    "OcahSepSpiFlashError",
    # Types and constants
    "IN_SCOPE_OPCODES",
    "PAGE_SIZE",
    "SECTOR_SIZE",
    "SR1_BUSY",
    "SR1_WEL",
    "OcahSpiOpcode",
    "SpiMode",
    "opcode_name",
]

__version__ = "0.2.0"
