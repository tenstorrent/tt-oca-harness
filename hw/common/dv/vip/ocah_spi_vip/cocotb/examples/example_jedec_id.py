# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
example_jedec_id.py — flash device, controller, monitor, and checker on one SPI connection.

Demonstrates:
  1. Instantiating OcahSpiFlash in single-SPI mode.
  2. Driving it with the package's own controller engine through
     OcahSpiMasterSequence (a bench with a real SPI host IP drives that IP
     instead and attaches only the device and the checker).
  3. Hooking a passive OcahSpiMonitor alongside the flash BFM.
  4. Judging the exchange with OcahSpiFlashChecker: the device streamed the
     configured identifier, the controller received what the device sent,
     the opcode sequence is exact, and the evidence finalizes.

This is not a stand-alone simulation test; it shows the API patterns that a
real DUT-level cocotb test would follow.  Replace the signal handles
(``dut.spi_cs_n``, etc.) with the actual signal paths in your testbench.  The
``--dut ocah_spi_vip`` selftests under ``../../dv/`` run this shape on a wire
harness.
"""

import cocotb
from cocotb.clock import Clock

from ocah_spi_vip import (
    OcahSpiFlash,
    OcahSpiFlashChecker,
    OcahSpiMasterBfm,
    OcahSpiMasterSequence,
    OcahSpiMonitor,
    OcahSpiOpcode,
)

TARGET_JEDEC_ID = 0xEF4018  # 24-bit JEDEC ID: manufacturer, type, capacity
REQUIRED_IDS = ("CHK-SPI-JEDEC-ID", "CHK-SPI-HOST-JEDEC", "CHK-SPI-CMD-ORDER")


@cocotb.test()
async def example_jedec_id(dut):
    """
    Issue READ JEDEC ID (0x9F) and judge the 3-byte response.

    Signal mapping assumed from testbench:
        dut.clk       — free-running reference clock (keeps the simulator ticking)
        dut.spi_cs_n  — active-low chip-select (controller drives this)
        dut.spi_sclk  — serial clock           (controller drives this)
        dut.spi_mosi  — data to flash           (controller drives this)
        dut.spi_miso  — data from flash         (flash drives this)
    """
    cocotb.start_soon(Clock(dut.clk, 4, "ns").start())

    # -----------------------------------------------------------------
    # Step 1: configure the flash BFM
    # -----------------------------------------------------------------
    flash = OcahSpiFlash(
        cs_n=dut.spi_cs_n,
        sclk=dut.spi_sclk,
        mosi=dut.spi_mosi,
        miso=dut.spi_miso,
        name="flash0",
        mode="single",
        jedec_id=TARGET_JEDEC_ID,
    )
    flash.init_signals()

    # -----------------------------------------------------------------
    # Step 2: the controller engine and its test-facing sequence
    # -----------------------------------------------------------------
    host = OcahSpiMasterBfm.from_prefix(dut, "spi", name="host0")
    host.init_signals()
    checker = OcahSpiFlashChecker(name="example_checker", flash=flash, required_ids=REQUIRED_IDS)
    seq = OcahSpiMasterSequence(host, checker)

    # -----------------------------------------------------------------
    # Step 3: attach a passive monitor and start the device
    # -----------------------------------------------------------------
    monitor = OcahSpiMonitor(
        cs_n=dut.spi_cs_n,
        sclk=dut.spi_sclk,
        mosi=dut.spi_mosi,
        miso=dut.spi_miso,
        name="spi_mon",
    )
    monitor.add_transaction_callback(lambda txn: cocotb.log.info("[monitor] %s", txn))
    await monitor.start()
    await flash.start()

    # -----------------------------------------------------------------
    # Step 4: one READ JEDEC ID frame
    # -----------------------------------------------------------------
    received_id = await seq.jedec_id()
    cocotb.log.info("controller received JEDEC=0x%06X", received_id)

    # -----------------------------------------------------------------
    # Step 5: judge and tear down
    # -----------------------------------------------------------------
    await monitor.stop()
    await flash.stop()
    checker.replay()  # CHK-SPI-JEDEC-ID: the device streamed the configured identifier
    seq.check_host_responses()  # CHK-SPI-HOST-JEDEC: the controller received what was sent
    checker.check_command_order([OcahSpiOpcode.JEDEC_ID])  # CHK-SPI-CMD-ORDER
    checker.finalize()
    cocotb.log.info("Monitor stats: %s", monitor.get_statistics())
